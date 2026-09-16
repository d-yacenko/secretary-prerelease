import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/assistant/assistant_controller.dart';
import 'package:personal_secretary/assistant/fake_speech_player.dart';
import 'package:personal_secretary/assistant/fake_voice_recorder.dart';
import 'package:personal_secretary/assistant/voice_invocation_source.dart';
import 'package:personal_secretary/assistant/voice_capture_diagnostics.dart';
import 'package:personal_secretary/assistant/voice_output_policy.dart';
import 'package:personal_secretary/assistant/voice_output_policy_controller.dart';
import 'package:personal_secretary/assistant/voice_output_policy_store.dart';
import 'package:personal_secretary/assistant/voice_temp_files.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';

void main() {
  const baseUrl = 'https://secretary.example';
  const token = 'inbox-review-completion-token';

  late Directory tempDir;

  setUp(() {
    VoiceCaptureDiagnostics.resetForTest();
    tempDir = Directory.systemTemp.createTempSync(
      'secretary_inbox_review_r4r4',
    );
  });

  tearDown(() {
    if (tempDir.existsSync()) {
      tempDir.deleteSync(recursive: true);
    }
  });

  http.Response jsonResponse(Object body, [int status = 200]) {
    return http.Response.bytes(
      utf8.encode(jsonEncode(body)),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );
  }

  http.Response speechOk() {
    return http.Response.bytes(
      [1, 2, 3, 4],
      200,
      headers: {'content-type': 'audio/mpeg'},
    );
  }

  Map<String, dynamic> receiptJson({
    String topId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  }) {
    return {
      'anchor_before_object_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      'anchor_before_feed_at': '2026-09-14T12:00:00Z',
      'snapshot_top_object_id': topId,
      'snapshot_top_feed_at': '2026-09-14T15:00:00Z',
      'total_count': 3,
    };
  }

  Map<String, dynamic> assistantAnswer({
    String answer = 'Новых писем 25.',
    Map<String, dynamic>? receipt,
  }) {
    return {
      'answer': answer,
      'references': [],
      'affected_objects': [],
      if (receipt != null) 'inbox_review_receipt': receipt,
    };
  }

  UserMe userMe(String id) {
    return UserMe(id: id, displayName: id, createdAt: '2026-01-01T00:00:00Z');
  }

  AuthController buildAuth(SecretaryApiClient apiClient, {String? userId}) {
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    if (userId != null) {
      auth.user = userMe(userId);
    }
    return auth;
  }

  AssistantController buildAssistant({
    required SecretaryApiClient apiClient,
    required AuthController auth,
    VoiceOutputPolicy policy = VoiceOutputPolicy.handsFreeEnabled,
    VoiceOutputPolicyController? voiceOutputPolicy,
    FakeSpeechPlayer? speechPlayer,
  }) {
    return AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(directory: tempDir),
      speechPlayer: speechPlayer ?? FakeSpeechPlayer(),
      voiceOutputPolicy:
          voiceOutputPolicy ??
          VoiceOutputPolicyController(
            authController: auth,
            store: VoiceOutputPolicyStore.memory(),
            initialPolicy: policy,
          ),
    );
  }

  Future<void> waitUntil(bool Function() condition) async {
    final end = DateTime.now().add(const Duration(seconds: 3));
    while (!condition()) {
      if (DateTime.now().isAfter(end)) {
        fail('timed out waiting for condition');
      }
      await Future<void>.delayed(const Duration(milliseconds: 10));
    }
  }

  test(
    'hands-free verified receipt plus complete playback posts completion CAS',
    () async {
      final completeBodies = <Map<String, dynamic>>[];
      final putCalls = <String>[];
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/message') {
          return jsonResponse(assistantAnswer(receipt: receiptJson()));
        }
        if (request.url.path == '/assistant/speech') {
          return speechOk();
        }
        if (request.method == 'POST' &&
            request.url.path == '/inbox/review-marker/complete') {
          completeBodies.add(
            jsonDecode(utf8.decode(request.bodyBytes)) as Map<String, dynamic>,
          );
          return jsonResponse({
            'status': 'advanced',
            'review_marker': {
              'anchor_feed_at': '2026-09-14T15:00:00Z',
              'anchor_object_id': 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
              'updated_at': '2026-09-14T16:00:00Z',
            },
          });
        }
        if (request.url.path == '/inbox/review-marker') {
          putCalls.add(request.method);
        }
        return http.Response('{}', 404);
      });
      final apiClient = SecretaryApiClient(httpClient: mock);
      apiClient.configure(baseUrl: baseUrl, token: token);
      final assistant = buildAssistant(
        apiClient: apiClient,
        auth: buildAuth(apiClient),
      );
      await assistant.sendMessage(
        'что нового?',
        source: VoiceInvocationSource.hardwareButton,
      );
      expect(completeBodies, hasLength(1));
      expect(
        completeBodies.single['snapshot_top_object_id'],
        'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      );
      expect(putCalls, isEmpty);
      expect(
        VoiceCaptureDiagnostics.events.map((event) => event['event']),
        containsAll(<String>[
          'assistant_response_review_receipt_received',
          'inbox_review_receipt_stored',
          'playback_started',
          'playback_completed',
          'inbox_review_completion_started',
          'inbox_review_completion_result',
        ]),
      );
      assistant.dispose();
    },
  );

  test(
    'lockScreenLauncher verified receipt plus complete playback posts CAS',
    () async {
      final completeBodies = <Map<String, dynamic>>[];
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/message') {
          return jsonResponse(assistantAnswer(receipt: receiptJson()));
        }
        if (request.url.path == '/assistant/speech') {
          return speechOk();
        }
        if (request.method == 'POST' &&
            request.url.path == '/inbox/review-marker/complete') {
          completeBodies.add(
            jsonDecode(utf8.decode(request.bodyBytes)) as Map<String, dynamic>,
          );
          return jsonResponse({
            'status': 'advanced',
            'review_marker': {
              'anchor_feed_at': '2026-09-14T15:00:00Z',
              'anchor_object_id': 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
              'updated_at': '2026-09-14T16:00:00Z',
            },
          });
        }
        return http.Response('{}', 404);
      });
      final apiClient = SecretaryApiClient(httpClient: mock);
      apiClient.configure(baseUrl: baseUrl, token: token);
      final assistant = buildAssistant(
        apiClient: apiClient,
        auth: buildAuth(apiClient),
      );
      await assistant.sendMessage(
        'что нового?',
        source: VoiceInvocationSource.lockScreenLauncher,
      );
      expect(completeBodies, hasLength(1));
      assistant.dispose();
    },
  );

  test(
    'lockScreenLauncher playback interrupt does not complete the marker',
    () async {
      var completeCalls = 0;
      final speechPlayer = FakeSpeechPlayer(completeImmediately: false);
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/message') {
          return jsonResponse(assistantAnswer(receipt: receiptJson()));
        }
        if (request.url.path == '/assistant/speech') {
          return speechOk();
        }
        if (request.url.path == '/inbox/review-marker/complete') {
          completeCalls += 1;
          return jsonResponse({'status': 'advanced'});
        }
        return http.Response('{}', 404);
      });
      final apiClient = SecretaryApiClient(httpClient: mock);
      apiClient.configure(baseUrl: baseUrl, token: token);
      final assistant = buildAssistant(
        apiClient: apiClient,
        auth: buildAuth(apiClient),
        speechPlayer: speechPlayer,
      );
      final turn = assistant.sendMessage(
        'что нового?',
        source: VoiceInvocationSource.lockScreenLauncher,
      );
      await waitUntil(() => speechPlayer.playCount > 0);
      await assistant.stopSpeaking();
      await turn;
      expect(completeCalls, 0);
      assistant.dispose();
    },
  );

  test('playback interrupt does not complete the marker', () async {
    var completeCalls = 0;
    final speechPlayer = FakeSpeechPlayer(completeImmediately: false);
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        return jsonResponse(assistantAnswer(receipt: receiptJson()));
      }
      if (request.url.path == '/assistant/speech') {
        return speechOk();
      }
      if (request.url.path == '/inbox/review-marker/complete') {
        completeCalls += 1;
        return jsonResponse({'status': 'advanced'});
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: buildAuth(apiClient),
      speechPlayer: speechPlayer,
    );
    final turn = assistant.sendMessage(
      'что нового?',
      source: VoiceInvocationSource.hardwareButton,
    );
    await waitUntil(() => speechPlayer.playCount > 0);
    await assistant.stopSpeaking();
    await turn;
    expect(completeCalls, 0);
    assistant.dispose();
  });

  test('TTS synthesis failure does not complete the marker', () async {
    var completeCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        return jsonResponse(assistantAnswer(receipt: receiptJson()));
      }
      if (request.url.path == '/assistant/speech') {
        return http.Response('nope', 502);
      }
      if (request.url.path == '/inbox/review-marker/complete') {
        completeCalls += 1;
        return jsonResponse({'status': 'advanced'});
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: buildAuth(apiClient),
    );
    await assistant.sendMessage(
      'что нового?',
      source: VoiceInvocationSource.hardwareButton,
    );
    expect(completeCalls, 0);
    assistant.dispose();
  });

  test('playback failure does not complete the marker', () async {
    var completeCalls = 0;
    final speechPlayer = FakeSpeechPlayer()..failNextPlay = true;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        return jsonResponse(assistantAnswer(receipt: receiptJson()));
      }
      if (request.url.path == '/assistant/speech') {
        return speechOk();
      }
      if (request.url.path == '/inbox/review-marker/complete') {
        completeCalls += 1;
        return jsonResponse({'status': 'advanced'});
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: buildAuth(apiClient),
      speechPlayer: speechPlayer,
    );
    await assistant.sendMessage(
      'что нового?',
      source: VoiceInvocationSource.hardwareButton,
    );
    expect(completeCalls, 0);
    assistant.dispose();
  });

  test('screen mic with default handsFreeEnabled does not complete', () async {
    var completeCalls = 0;
    var speechCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        return jsonResponse(assistantAnswer(receipt: receiptJson()));
      }
      if (request.url.path == '/assistant/speech') {
        speechCalls += 1;
        return speechOk();
      }
      if (request.url.path == '/inbox/review-marker/complete') {
        completeCalls += 1;
        return jsonResponse({'status': 'advanced'});
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: buildAuth(apiClient),
    );
    await assistant.sendMessage(
      'что нового?',
      source: VoiceInvocationSource.screenMic,
    );
    expect(speechCalls, 0);
    expect(completeCalls, 0);
    assistant.dispose();
  });

  test(
    'legacy all_voice_input screenMic review does not complete the marker',
    () async {
      var completeCalls = 0;
      var speechCalls = 0;
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/message') {
          return jsonResponse(assistantAnswer(receipt: receiptJson()));
        }
        if (request.url.path == '/assistant/speech') {
          speechCalls += 1;
          return speechOk();
        }
        if (request.url.path == '/inbox/review-marker/complete') {
          completeCalls += 1;
          return jsonResponse({'status': 'advanced'});
        }
        return http.Response('{}', 404);
      });
      final apiClient = SecretaryApiClient(httpClient: mock);
      apiClient.configure(baseUrl: baseUrl, token: token);
      final auth = buildAuth(apiClient);
      auth.user = UserMe(
        id: 'user-legacy',
        displayName: 'legacy',
        createdAt: '2026-01-01T00:00:00Z',
      );
      final store = VoiceOutputPolicyStore.memory(
        initial: {
          VoiceOutputPolicyStore.prefKeyForUser('user-legacy'):
              VoiceOutputPolicyStore.legacyAllVoiceInput,
        },
      );
      final policy = VoiceOutputPolicyController(
        authController: auth,
        store: store,
      );
      await policy.attach();
      expect(policy.policy, VoiceOutputPolicy.handsFreeEnabled);
      final assistant = buildAssistant(
        apiClient: apiClient,
        auth: auth,
        voiceOutputPolicy: policy,
      );
      await assistant.sendMessage(
        'что нового?',
        source: VoiceInvocationSource.screenMic,
      );
      expect(speechCalls, 0);
      expect(completeCalls, 0);
      assistant.dispose();
    },
  );

  test('never policy never auto-completes', () async {
    var completeCalls = 0;
    var speechCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        return jsonResponse(assistantAnswer(receipt: receiptJson()));
      }
      if (request.url.path == '/assistant/speech') {
        speechCalls += 1;
        return speechOk();
      }
      if (request.url.path == '/inbox/review-marker/complete') {
        completeCalls += 1;
        return jsonResponse({'status': 'advanced'});
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: buildAuth(apiClient),
      policy: VoiceOutputPolicy.never,
    );
    await assistant.sendMessage(
      'что нового?',
      source: VoiceInvocationSource.hardwareButton,
    );
    expect(speechCalls, 0);
    expect(completeCalls, 0);
    assistant.dispose();
  });

  test(
    'completion payload keeps frozen snapshot top, not a later arrival',
    () async {
      Map<String, dynamic>? completeBody;
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/message') {
          return jsonResponse(
            assistantAnswer(
              receipt: receiptJson(
                topId: 'n3n3n3n3-n3n3-43n3-83n3-n3n3n3n3n3n3',
              ),
            ),
          );
        }
        if (request.url.path == '/assistant/speech') {
          return speechOk();
        }
        if (request.url.path == '/inbox/review-marker/complete') {
          completeBody =
              jsonDecode(utf8.decode(request.bodyBytes))
                  as Map<String, dynamic>;
          return jsonResponse({'status': 'advanced'});
        }
        return http.Response('{}', 404);
      });
      final apiClient = SecretaryApiClient(httpClient: mock);
      apiClient.configure(baseUrl: baseUrl, token: token);
      final assistant = buildAssistant(
        apiClient: apiClient,
        auth: buildAuth(apiClient),
      );
      await assistant.sendMessage(
        'что нового?',
        source: VoiceInvocationSource.hardwareButton,
      );
      expect(completeBody, isNotNull);
      expect(
        completeBody!['snapshot_top_object_id'],
        'n3n3n3n3-n3n3-43n3-83n3-n3n3n3n3n3n3',
      );
      expect(completeBody!.containsKey('after_object_id'), isFalse);
      assistant.dispose();
    },
  );

  test(
    'already-current complete response is not followed by a regressing PUT',
    () async {
      final methods = <String>[];
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/message') {
          return jsonResponse(assistantAnswer(receipt: receiptJson()));
        }
        if (request.url.path == '/assistant/speech') {
          return speechOk();
        }
        if (request.url.path == '/inbox/review-marker/complete') {
          methods.add('${request.method} complete');
          return jsonResponse({'status': 'already_current'});
        }
        if (request.url.path == '/inbox/review-marker') {
          methods.add('${request.method} marker');
          return jsonResponse({
            'anchor_feed_at': '2026-09-14T18:00:00Z',
            'anchor_object_id': 'cccccccccccccccc-cccc-4ccc-8ccc-cccccccccccc',
            'updated_at': '2026-09-14T18:00:00Z',
          });
        }
        return http.Response('{}', 404);
      });
      final apiClient = SecretaryApiClient(httpClient: mock);
      apiClient.configure(baseUrl: baseUrl, token: token);
      final assistant = buildAssistant(
        apiClient: apiClient,
        auth: buildAuth(apiClient),
      );
      await assistant.sendMessage(
        'что нового?',
        source: VoiceInvocationSource.hardwareButton,
      );
      expect(methods, ['POST complete']);
      assistant.dispose();
    },
  );

  test('incompatible complete conflict is not overwritten by PUT', () async {
    final methods = <String>[];
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        return jsonResponse(assistantAnswer(receipt: receiptJson()));
      }
      if (request.url.path == '/assistant/speech') {
        return speechOk();
      }
      if (request.url.path == '/inbox/review-marker/complete') {
        methods.add('${request.method} complete');
        return jsonResponse({'status': 'conflict'});
      }
      if (request.url.path == '/inbox/review-marker') {
        methods.add('${request.method} marker');
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: buildAuth(apiClient),
    );
    await assistant.sendMessage(
      'что нового?',
      source: VoiceInvocationSource.hardwareButton,
    );
    expect(methods, ['POST complete']);
    assistant.dispose();
  });

  test(
    'explicit marker PUT remains independent of review completion',
    () async {
      var putCalls = 0;
      final mock = MockClient((request) async {
        if (request.method == 'PUT' &&
            request.url.path == '/inbox/review-marker') {
          putCalls += 1;
          final body =
              jsonDecode(utf8.decode(request.bodyBytes))
                  as Map<String, dynamic>;
          expect(
            body['after_object_id'],
            'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
          );
          return jsonResponse({
            'anchor_feed_at': '2026-09-14T12:00:00Z',
            'anchor_object_id': 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
            'updated_at': '2026-09-14T12:00:00Z',
          });
        }
        return http.Response('{}', 404);
      });
      final apiClient = SecretaryApiClient(httpClient: mock);
      apiClient.configure(baseUrl: baseUrl, token: token);
      final saved = await apiClient.putInboxReviewMarker(
        'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
      );
      expect(putCalls, 1);
      expect(saved.anchorObjectId, 'dddddddd-dddd-4ddd-8ddd-dddddddddddd');
    },
  );

  test('complete API failure stays fail-closed and records a safe diagnostic', () async {
    var completeCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        return jsonResponse(assistantAnswer(receipt: receiptJson()));
      }
      if (request.url.path == '/assistant/speech') {
        return speechOk();
      }
      if (request.url.path == '/inbox/review-marker/complete') {
        completeCalls += 1;
        return http.Response('nope', 502);
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: buildAuth(apiClient),
    );
    await assistant.sendMessage(
      'перечисли все новые сообщения',
      source: VoiceInvocationSource.hardwareButton,
    );
    expect(completeCalls, 1);
    expect(
      VoiceCaptureDiagnostics.events.map((event) => event['event']),
      containsAll(<String>[
        'assistant_response_review_receipt_received',
        'inbox_review_receipt_stored',
        'playback_completed',
        'inbox_review_completion_started',
        'inbox_review_completion_failed',
      ]),
    );
    expect(
      VoiceCaptureDiagnostics.events
          .where((event) => event['event'] == 'inbox_review_completion_failed')
          .single['failure'],
      'api',
    );
    assistant.dispose();
  });
}
