import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/assistant/assistant_controller.dart';
import 'package:personal_secretary/assistant/assistant_screen.dart';
import 'package:personal_secretary/assistant/fake_voice_recorder.dart';
import 'package:personal_secretary/assistant/voice_output_policy.dart';
import 'package:personal_secretary/assistant/voice_output_policy_controller.dart';
import 'package:personal_secretary/assistant/voice_output_policy_store.dart';
import 'package:personal_secretary/assistant/voice_recorder_exceptions.dart';
import 'package:personal_secretary/assistant/voice_temp_files.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/capture/capture_controller.dart';

Future<void> pumpAssistantFrames(WidgetTester tester, {int frames = 3}) async {
  for (var i = 0; i < frames; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

MockClient mockWithSpeech(Future<http.Response> Function(http.Request) inner) {
  return MockClient((request) async {
    if (request.url.path == '/assistant/speech') {
      return http.Response.bytes(
        [1, 2, 3, 4],
        200,
        headers: {'content-type': 'audio/mpeg'},
      );
    }
    return inner(request);
  });
}

void main() {
  const baseUrl = 'https://secretary.example';
  const token = 'assistant-token';

  AssistantController buildAssistant({
    required SecretaryApiClient apiClient,
    required AuthController auth,
    FakeVoiceRecorder? voiceRecorder,
    VoiceTempFiles? voiceTempFiles,
  }) {
    return AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: voiceRecorder ?? FakeVoiceRecorder(),
      voiceTempFiles:
          voiceTempFiles ??
          VoiceTempFiles(
            directory: Directory.systemTemp.createTempSync(
              'secretary_voice_test',
            ),
          ),
      voiceOutputPolicy: VoiceOutputPolicyController(
        authController: auth,
        store: VoiceOutputPolicyStore.memory(),
        initialPolicy: VoiceOutputPolicy.handsFreeEnabled,
      ),
    );
  }

  Widget buildAssistantScreen({
    required AssistantController assistant,
    required SecretaryApiClient apiClient,
    required AuthController auth,
  }) {
    return MaterialApp(
      home: AssistantScreen(
        controller: assistant,
        apiClient: apiClient,
        authController: auth,
        captureController: CaptureController(
          apiClient: apiClient,
          authController: auth,
        ),
      ),
    );
  }

  NotificationOut sampleNotification() {
    return NotificationOut(
      id: 'notif-1',
      title: 'Unread alert',
      priority: 'normal',
      status: 'unresolved',
      proposal: {},
      createdAt: '2026-08-28T08:00:00Z',
      updatedAt: '2026-08-28T08:00:00Z',
    );
  }

  test('voice flow transcribes and sends with notification context', () async {
    int transcribeCalls = 0;
    int assistantCalls = 0;
    Map<String, dynamic>? assistantBody;
    final mock = mockWithSpeech((request) async {
      if (request.url.path == '/assistant/transcribe') {
        transcribeCalls += 1;
        return http.Response.bytes(
          utf8.encode(jsonEncode({'text': 'Создай задачу разобраться с этим'})),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }
      if (request.url.path == '/assistant/message') {
        assistantCalls += 1;
        assistantBody = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(
          jsonEncode({
            'answer': 'Task proposed',
            'references': [],
            'affected_objects': [],
          }),
          200,
        );
      }
      return http.Response('{}', 404);
    });

    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final voiceRecorder = FakeVoiceRecorder();
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: auth,
      voiceRecorder: voiceRecorder,
    );
    assistant.setNotificationContext(sampleNotification());

    await assistant.startVoiceRecording();
    expect(assistant.voiceState, AssistantVoiceState.recording);
    await assistant.stopVoiceRecordingAndTranscribe();

    expect(transcribeCalls, 1);
    expect(assistantCalls, 1);
    expect(assistantBody?['context_notification_id'], 'notif-1');
    expect(assistantBody?['message'], 'Создай задачу разобраться с этим');
    expect(voiceRecorder.lastStartedPath, isNotNull);
    expect(await File(voiceRecorder.lastStartedPath!).exists(), isFalse);
    expect(assistant.pendingRetryMessage, isNull);
    assistant.dispose();
  });

  test('microphone permission denial does not upload', () async {
    int transcribeCalls = 0;
    final mock = mockWithSpeech((request) async {
      if (request.url.path == '/assistant/transcribe') {
        transcribeCalls += 1;
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final voiceRecorder = FakeVoiceRecorder();
    voiceRecorder.permissionGranted = false;
    voiceRecorder.requestPermissionResult = false;
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: auth,
      voiceRecorder: voiceRecorder,
    );

    await assistant.startVoiceRecording();

    expect(transcribeCalls, 0);
    expect(voiceRecorder.startCallCount, 0);
    expect(assistant.voiceState, AssistantVoiceState.error);
    assistant.dispose();
  });

  test('transcription failure does not call assistant message', () async {
    int assistantCalls = 0;
    final mock = mockWithSpeech((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return http.Response(
          jsonEncode({'detail': 'Transcription provider unavailable'}),
          502,
        );
      }
      if (request.url.path == '/assistant/message') {
        assistantCalls += 1;
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final voiceRecorder = FakeVoiceRecorder();
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: auth,
      voiceRecorder: voiceRecorder,
    );

    await assistant.startVoiceRecording();
    await assistant.stopVoiceRecordingAndTranscribe();

    expect(assistantCalls, 0);
    expect(assistant.voiceState, AssistantVoiceState.error);
    expect(await File(voiceRecorder.lastStartedPath!).exists(), isFalse);
    assistant.dispose();
  });

  test(
    'assistant failure after transcription preserves transcript for retry',
    () async {
      final mock = mockWithSpeech((request) async {
        if (request.url.path == '/assistant/transcribe') {
          return http.Response(jsonEncode({'text': 'Retry me'}), 200);
        }
        if (request.url.path == '/assistant/message') {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'detail': {
                  'code': 'assistant_internal',
                  'message':
                      'Секретарь не смог завершить запрос из-за внутренней ошибки.',
                },
              }),
            ),
            502,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        return http.Response('{}', 404);
      });
      final apiClient = SecretaryApiClient(httpClient: mock);
      apiClient.configure(baseUrl: baseUrl, token: token);
      final auth = AuthController(
        apiClient: apiClient,
        tokenStore: FakeTokenStore(),
        serverUrlStore: FakeServerUrlStore(),
      );
      auth.status = AuthStatus.authenticated;
      final assistant = buildAssistant(apiClient: apiClient, auth: auth);

      await assistant.startVoiceRecording();
      await assistant.stopVoiceRecordingAndTranscribe();

      expect(assistant.pendingRetryMessage, 'Retry me');
      assistant.dispose();
    },
  );

  testWidgets('assistant failure leaves transcript in text input', (
    tester,
  ) async {
    final mock = mockWithSpeech((request) async {
      if (request.url.path == '/assistant/message') {
        return http.Response.bytes(
          utf8.encode(
            jsonEncode({
              'detail': {
                'code': 'assistant_internal',
                'message':
                    'Секретарь не смог завершить запрос из-за внутренней ошибки.',
              },
            }),
          ),
          502,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final assistant = buildAssistant(apiClient: apiClient, auth: auth);

    await tester.pumpWidget(
      buildAssistantScreen(
        assistant: assistant,
        apiClient: apiClient,
        auth: auth,
      ),
    );
    await pumpAssistantFrames(tester);

    final sendFuture = assistant.sendMessage('Retry me');
    while (assistant.isSending) {
      await tester.pump(const Duration(milliseconds: 20));
    }
    await sendFuture;
    await pumpAssistantFrames(tester);

    expect(find.text('Retry me'), findsOneWidget);
    expect(find.text('Повторить'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
    assistant.dispose();
  });

  test('voice preserves object context', () async {
    Map<String, dynamic>? assistantBody;
    final mock = mockWithSpeech((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return http.Response(jsonEncode({'text': 'Voice question'}), 200);
      }
      if (request.url.path == '/assistant/message') {
        assistantBody = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(
          jsonEncode({
            'answer': 'ok',
            'references': [],
            'affected_objects': [],
          }),
          200,
        );
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final assistant = buildAssistant(apiClient: apiClient, auth: auth);
    assistant.setObjectContext(
      SecretaryObject(
        id: 'obj-ctx',
        kind: 'course',
        title: 'Intro Course',
        metadata: {},
        origin: 'user',
        state: 'confirmed',
        createdAt: '2026-08-28T08:00:00Z',
        updatedAt: '2026-08-28T08:00:00Z',
      ),
    );

    await assistant.startVoiceRecording();
    await assistant.stopVoiceRecordingAndTranscribe();

    expect(assistantBody?['context_object_id'], 'obj-ctx');
    expect(assistantBody?['context_notification_id'], isNull);
    assistant.dispose();
  });

  test('cancellation deletes temporary audio file', () async {
    final voiceRecorder = FakeVoiceRecorder();
    final apiClient = SecretaryApiClient(
      httpClient: mockWithSpeech((request) async => http.Response('{}', 404)),
    );
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: auth,
      voiceRecorder: voiceRecorder,
    );

    await assistant.startVoiceRecording();
    final path = voiceRecorder.lastStartedPath!;
    expect(await File(path).exists(), isTrue);
    await assistant.cancelVoiceRecording();
    expect(await File(path).exists(), isFalse);
    assistant.dispose();
  });

  test('concurrent recording start invokes recorder start once', () async {
    final voiceRecorder = FakeVoiceRecorder();
    voiceRecorder.startDelay = const Duration(milliseconds: 50);
    final apiClient = SecretaryApiClient(
      httpClient: mockWithSpeech((request) async => http.Response('{}', 404)),
    );
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: auth,
      voiceRecorder: voiceRecorder,
    );

    final first = assistant.startVoiceRecording();
    expect(assistant.voiceState, AssistantVoiceState.starting);
    final second = assistant.startVoiceRecording();
    await first;
    await second;
    expect(voiceRecorder.startCallCount, 1);
    await assistant.cancelVoiceRecording();
    assistant.dispose();
  });

  test(
    'concurrent stop invokes recorder stop and transcription once',
    () async {
      int transcribeCalls = 0;
      final voiceRecorder = FakeVoiceRecorder();
      voiceRecorder.stopDelay = const Duration(milliseconds: 50);
      final mock = mockWithSpeech((request) async {
        if (request.url.path == '/assistant/transcribe') {
          transcribeCalls += 1;
          return http.Response(jsonEncode({'text': 'once'}), 200);
        }
        if (request.url.path == '/assistant/message') {
          return http.Response(
            jsonEncode({
              'answer': 'ok',
              'references': [],
              'affected_objects': [],
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      });
      final apiClient = SecretaryApiClient(httpClient: mock);
      apiClient.configure(baseUrl: baseUrl, token: token);
      final auth = AuthController(
        apiClient: apiClient,
        tokenStore: FakeTokenStore(),
        serverUrlStore: FakeServerUrlStore(),
      );
      auth.status = AuthStatus.authenticated;
      final assistant = buildAssistant(
        apiClient: apiClient,
        auth: auth,
        voiceRecorder: voiceRecorder,
      );

      await assistant.startVoiceRecording();
      final first = assistant.stopVoiceRecordingAndTranscribe();
      expect(assistant.voiceState, AssistantVoiceState.transcribing);
      final second = assistant.stopVoiceRecordingAndTranscribe();
      await first;
      await second;
      expect(voiceRecorder.stopCallCount, 1);
      expect(transcribeCalls, 1);
      assistant.dispose();
    },
  );

  testWidgets('text send still works while voice is idle', (tester) async {
    int assistantCalls = 0;
    final mock = mockWithSpeech((request) async {
      if (request.url.path == '/assistant/message') {
        assistantCalls += 1;
        return http.Response(
          jsonEncode({
            'answer': 'typed ok',
            'references': [],
            'affected_objects': [],
          }),
          200,
        );
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final assistant = buildAssistant(apiClient: apiClient, auth: auth);

    await tester.pumpWidget(
      buildAssistantScreen(
        assistant: assistant,
        apiClient: apiClient,
        auth: auth,
      ),
    );
    await pumpAssistantFrames(tester);

    await tester.enterText(
      find.byKey(const Key('assistant_input')),
      'typed text',
    );
    await tester.tap(find.widgetWithText(FilledButton, 'Отправить'));
    while (assistant.isSending) {
      await tester.pump(const Duration(milliseconds: 20));
    }
    await pumpAssistantFrames(tester);

    expect(assistantCalls, 1);
    expect(find.text('typed ok'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
    assistant.dispose();
  });

  test('recording state is set after startVoiceRecording', () async {
    final apiClient = SecretaryApiClient(
      httpClient: mockWithSpeech((request) async => http.Response('{}', 404)),
    );
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final assistant = buildAssistant(apiClient: apiClient, auth: auth);

    await assistant.startVoiceRecording();

    expect(assistant.voiceState, AssistantVoiceState.recording);
    await assistant.cancelVoiceRecording();
    expect(assistant.voiceState, AssistantVoiceState.idle);
    assistant.dispose();
  });

  test('transcribing state is active while transcription runs', () async {
    final mock = mockWithSpeech((request) async {
      if (request.url.path == '/assistant/transcribe') {
        await Future<void>.delayed(const Duration(milliseconds: 50));
        return http.Response(jsonEncode({'text': 'late transcript'}), 200);
      }
      if (request.url.path == '/assistant/message') {
        return http.Response(
          jsonEncode({
            'answer': 'done',
            'references': [],
            'affected_objects': [],
          }),
          200,
        );
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final assistant = buildAssistant(apiClient: apiClient, auth: auth);

    await assistant.startVoiceRecording();
    final stopFuture = assistant.stopVoiceRecordingAndTranscribe();
    await Future<void>.delayed(const Duration(milliseconds: 10));
    expect(assistant.voiceState, AssistantVoiceState.transcribing);
    await stopFuture;
    expect(assistant.voiceState, AssistantVoiceState.idle);
    assistant.dispose();
  });

  test('sendMessage is blocked while recording', () async {
    int assistantCalls = 0;
    final mock = mockWithSpeech((request) async {
      if (request.url.path == '/assistant/message') {
        assistantCalls += 1;
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final assistant = buildAssistant(apiClient: apiClient, auth: auth);

    await assistant.startVoiceRecording();
    expect(assistant.isVoiceBusy, isTrue);
    await assistant.sendMessage('blocked text');

    expect(assistantCalls, 0);
    await assistant.cancelVoiceRecording();
    assistant.dispose();
  });

  test('sendMessage is blocked while transcribing', () async {
    int assistantCalls = 0;
    final voiceRecorder = FakeVoiceRecorder();
    voiceRecorder.stopDelay = const Duration(milliseconds: 50);
    final mock = mockWithSpeech((request) async {
      if (request.url.path == '/assistant/transcribe') {
        await Future<void>.delayed(const Duration(milliseconds: 50));
        return http.Response(jsonEncode({'text': 'voice text'}), 200);
      }
      if (request.url.path == '/assistant/message') {
        assistantCalls += 1;
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: auth,
      voiceRecorder: voiceRecorder,
    );

    await assistant.startVoiceRecording();
    final stopFuture = assistant.stopVoiceRecordingAndTranscribe();
    await Future<void>.delayed(const Duration(milliseconds: 10));
    expect(assistant.voiceState, AssistantVoiceState.transcribing);
    await assistant.sendMessage('blocked text');

    await stopFuture;
    expect(assistantCalls, 1);
    assistant.dispose();
  });

  test('permission check exception becomes safe voice error', () async {
    final voiceRecorder = FakeVoiceRecorder();
    voiceRecorder.throwOnHasPermission = true;
    final apiClient = SecretaryApiClient(
      httpClient: mockWithSpeech((request) async => http.Response('{}', 404)),
    );
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: auth,
      voiceRecorder: voiceRecorder,
    );

    await assistant.startVoiceRecording();

    expect(assistant.voiceState, AssistantVoiceState.error);
    expect(assistant.voiceErrorMessage, 'Voice recording could not start.');
    expect(voiceRecorder.startCallCount, 0);
    assistant.dispose();
  });

  test('start failure cleans up partially created temp file', () async {
    final voiceRecorder = FakeVoiceRecorder();
    voiceRecorder.failStartAfterWrite = true;
    final apiClient = SecretaryApiClient(
      httpClient: mockWithSpeech((request) async => http.Response('{}', 404)),
    );
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: auth,
      voiceRecorder: voiceRecorder,
    );

    await assistant.startVoiceRecording();

    expect(assistant.voiceState, AssistantVoiceState.error);
    expect(voiceRecorder.lastStartedPath, isNotNull);
    expect(await File(voiceRecorder.lastStartedPath!).exists(), isFalse);
    assistant.dispose();
  });

  test('transcript preserved when Assistant send is already active', () async {
    int assistantCalls = 0;
    final mock = mockWithSpeech((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return http.Response(jsonEncode({'text': 'overlap transcript'}), 200);
      }
      if (request.url.path == '/assistant/message') {
        assistantCalls += 1;
        return http.Response(
          jsonEncode({
            'answer': 'ok',
            'references': [],
            'affected_objects': [],
          }),
          200,
        );
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final assistant = buildAssistant(apiClient: apiClient, auth: auth);

    await assistant.startVoiceRecording();
    assistant.sendState = AssistantSendState.sending;
    await assistant.stopVoiceRecordingAndTranscribe();

    expect(assistant.pendingRetryMessage, 'overlap transcript');
    expect(assistantCalls, 0);
    assistant.dispose();
  });

  test(
    'cancel during in-flight start stops recorder and cleans temp file',
    () async {
      final voiceRecorder = FakeVoiceRecorder();
      voiceRecorder.startDelay = const Duration(milliseconds: 50);
      final apiClient = SecretaryApiClient(
        httpClient: mockWithSpeech((request) async => http.Response('{}', 404)),
      );
      apiClient.configure(baseUrl: baseUrl, token: token);
      final auth = AuthController(
        apiClient: apiClient,
        tokenStore: FakeTokenStore(),
        serverUrlStore: FakeServerUrlStore(),
      );
      auth.status = AuthStatus.authenticated;
      final assistant = buildAssistant(
        apiClient: apiClient,
        auth: auth,
        voiceRecorder: voiceRecorder,
      );

      final startFuture = assistant.startVoiceRecording();
      expect(assistant.voiceState, AssistantVoiceState.starting);
      while (voiceRecorder.startCallCount == 0) {
        await Future<void>.delayed(const Duration(milliseconds: 1));
      }
      await assistant.cancelVoiceRecording();
      await startFuture;

      expect(voiceRecorder.startCallCount, 1);
      expect(voiceRecorder.cancelCallCount, greaterThanOrEqualTo(1));
      expect(voiceRecorder.isRecording, isFalse);
      expect(assistant.voiceState, AssistantVoiceState.idle);
      expect(voiceRecorder.lastStartedPath, isNotNull);
      expect(await File(voiceRecorder.lastStartedPath!).exists(), isFalse);
      assistant.dispose();
    },
  );

  test(
    'reset during in-flight start invalidates startup without API calls',
    () async {
      int transcribeCalls = 0;
      int assistantCalls = 0;
      final voiceRecorder = FakeVoiceRecorder();
      voiceRecorder.startDelay = const Duration(milliseconds: 50);
      final mock = mockWithSpeech((request) async {
        if (request.url.path == '/assistant/transcribe') {
          transcribeCalls += 1;
        }
        if (request.url.path == '/assistant/message') {
          assistantCalls += 1;
        }
        return http.Response('{}', 404);
      });
      final apiClient = SecretaryApiClient(httpClient: mock);
      apiClient.configure(baseUrl: baseUrl, token: token);
      final auth = AuthController(
        apiClient: apiClient,
        tokenStore: FakeTokenStore(),
        serverUrlStore: FakeServerUrlStore(),
      );
      auth.status = AuthStatus.authenticated;
      final assistant = buildAssistant(
        apiClient: apiClient,
        auth: auth,
        voiceRecorder: voiceRecorder,
      );

      final startFuture = assistant.startVoiceRecording();
      expect(assistant.voiceState, AssistantVoiceState.starting);
      while (voiceRecorder.startCallCount == 0) {
        await Future<void>.delayed(const Duration(milliseconds: 1));
      }
      assistant.resetSession();
      await startFuture;

      expect(voiceRecorder.isRecording, isFalse);
      expect(assistant.voiceState, AssistantVoiceState.idle);
      expect(voiceRecorder.lastStartedPath, isNotNull);
      expect(await File(voiceRecorder.lastStartedPath!).exists(), isFalse);
      expect(transcribeCalls, 0);
      expect(assistantCalls, 0);
      assistant.dispose();
    },
  );

  test('cancel during start blocks immediate restart until settled', () async {
    final voiceRecorder = FakeVoiceRecorder();
    voiceRecorder.startDelay = const Duration(milliseconds: 50);
    final apiClient = SecretaryApiClient(
      httpClient: mockWithSpeech((request) async => http.Response('{}', 404)),
    );
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: auth,
      voiceRecorder: voiceRecorder,
    );

    final startFutureA = assistant.startVoiceRecording();
    expect(assistant.voiceState, AssistantVoiceState.starting);
    while (voiceRecorder.startCallCount == 0) {
      await Future<void>.delayed(const Duration(milliseconds: 1));
    }
    await assistant.cancelVoiceRecording();

    await assistant.startVoiceRecording();
    expect(voiceRecorder.startCallCount, 1);
    expect(assistant.isVoiceBusy, isTrue);

    await startFutureA;

    expect(voiceRecorder.cancelCallCount, greaterThanOrEqualTo(1));
    expect(voiceRecorder.isRecording, isFalse);
    expect(assistant.voiceState, AssistantVoiceState.idle);
    expect(assistant.isVoiceBusy, isFalse);
    expect(voiceRecorder.lastStartedPath, isNotNull);
    expect(await File(voiceRecorder.lastStartedPath!).exists(), isFalse);

    await assistant.startVoiceRecording();
    expect(voiceRecorder.startCallCount, 2);
    expect(assistant.voiceState, AssistantVoiceState.recording);
    await assistant.cancelVoiceRecording();
    assistant.dispose();
  });

  test('reset during start blocks immediate restart until settled', () async {
    final voiceRecorder = FakeVoiceRecorder();
    voiceRecorder.startDelay = const Duration(milliseconds: 50);
    final apiClient = SecretaryApiClient(
      httpClient: mockWithSpeech((request) async => http.Response('{}', 404)),
    );
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: auth,
      voiceRecorder: voiceRecorder,
    );

    final startFutureA = assistant.startVoiceRecording();
    expect(assistant.voiceState, AssistantVoiceState.starting);
    while (voiceRecorder.startCallCount == 0) {
      await Future<void>.delayed(const Duration(milliseconds: 1));
    }
    assistant.resetSession();

    await assistant.startVoiceRecording();
    expect(voiceRecorder.startCallCount, 1);
    expect(assistant.isVoiceBusy, isTrue);

    await startFutureA;

    expect(voiceRecorder.isRecording, isFalse);
    expect(assistant.voiceState, AssistantVoiceState.idle);
    expect(assistant.isVoiceBusy, isFalse);
    expect(voiceRecorder.lastStartedPath, isNotNull);
    expect(await File(voiceRecorder.lastStartedPath!).exists(), isFalse);

    await assistant.startVoiceRecording();
    expect(voiceRecorder.startCallCount, 2);
    expect(assistant.voiceState, AssistantVoiceState.recording);
    await assistant.cancelVoiceRecording();
    assistant.dispose();
  });

  testWidgets('permission denial shows safe message', (tester) async {
    final voiceRecorder = FakeVoiceRecorder();
    voiceRecorder.permissionGranted = false;
    voiceRecorder.requestPermissionResult = false;
    final apiClient = SecretaryApiClient(
      httpClient: mockWithSpeech((request) async => http.Response('{}', 404)),
    );
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: auth,
      voiceRecorder: voiceRecorder,
    );

    await tester.pumpWidget(
      buildAssistantScreen(
        assistant: assistant,
        apiClient: apiClient,
        auth: auth,
      ),
    );
    await pumpAssistantFrames(tester);

    await assistant.startVoiceRecording();
    await pumpAssistantFrames(tester);

    expect(find.textContaining('Microphone permission'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
    assistant.dispose();
  });

  test('unsupported encoder shows recoverable error', () async {
    final voiceRecorder = FakeVoiceRecorder();
    voiceRecorder.throwEncoderUnsupported = true;
    final apiClient = SecretaryApiClient(
      httpClient: mockWithSpeech((request) async => http.Response('{}', 404)),
    );
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: auth,
      voiceRecorder: voiceRecorder,
    );

    await assistant.startVoiceRecording();

    expect(assistant.voiceState, AssistantVoiceState.error);
    expect(
      assistant.voiceErrorMessage,
      const VoiceRecorderEncoderUnsupported().message,
    );
    assistant.dispose();
  });

  test('successful recording uploads matching filename', () async {
    String? transcribeBody;
    Map<String, dynamic>? assistantBody;
    final voiceRecorder = FakeVoiceRecorder(audioBytes: [1, 2, 3, 4]);
    voiceRecorder.recordingFileExtension = 'm4a';
    voiceRecorder.recordingContentType = 'audio/mp4';
    final mock = mockWithSpeech((request) async {
      if (request.url.path == '/assistant/transcribe') {
        transcribeBody = utf8.decode(request.bodyBytes, allowMalformed: true);
        return http.Response(jsonEncode({'text': 'voice transcript'}), 200);
      }
      if (request.url.path == '/assistant/message') {
        assistantBody = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(
          jsonEncode({
            'answer': 'ok',
            'references': [],
            'affected_objects': [],
          }),
          200,
        );
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: auth,
      voiceRecorder: voiceRecorder,
    );

    await assistant.startVoiceRecording();
    await assistant.stopVoiceRecordingAndTranscribe();

    expect(transcribeBody, contains('secretary_voice.m4a'));
    expect(assistantBody?['message'], 'voice transcript');
    assistant.dispose();
  });
}
