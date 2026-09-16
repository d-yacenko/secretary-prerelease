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
import 'package:personal_secretary/assistant/speech_text.dart';
import 'package:personal_secretary/assistant/voice_confirmation.dart';
import 'package:personal_secretary/assistant/voice_invocation_source.dart';
import 'package:personal_secretary/assistant/voice_recorder_exceptions.dart';
import 'package:personal_secretary/assistant/voice_output_policy.dart';
import 'package:personal_secretary/assistant/voice_output_policy_controller.dart';
import 'package:personal_secretary/assistant/voice_output_policy_store.dart';
import 'package:personal_secretary/assistant/voice_temp_files.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';

void main() {
  const baseUrl = 'https://secretary.example';
  const token = 'voice-a-token';

  late Directory tempDir;

  setUp(() {
    tempDir = Directory.systemTemp.createTempSync('secretary_voice_a_test');
  });

  tearDown(() {
    if (tempDir.existsSync()) {
      tempDir.deleteSync(recursive: true);
    }
  });

  Map<String, dynamic> assistantAnswer(String answer) {
    return {'answer': answer, 'references': [], 'affected_objects': []};
  }

  Map<String, dynamic> pendingCommunicationPlan({
    String planId = 'plan-email',
    String toolName = 'send_email',
    Map<String, dynamic>? arguments,
    String answer = 'Могу отправить письмо.',
  }) {
    return {
      'answer': answer,
      'references': [],
      'affected_objects': [],
      'pending_action_plan': {
        'id': planId,
        'status': 'pending',
        'expires_at': '2026-09-13T12:00:00Z',
        'actions': [
          {
            'tool_name': toolName,
            'arguments':
                arguments ??
                {
                  'to': ['ivan@example.com'],
                  'subject': 'Статус',
                  'body': 'Пришлю завтра.',
                },
          },
        ],
      },
    };
  }

  AssistantController buildAssistant({
    required SecretaryApiClient apiClient,
    required AuthController auth,
    FakeVoiceRecorder? voiceRecorder,
    FakeSpeechPlayer? speechPlayer,
  }) {
    return AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: voiceRecorder ?? FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(directory: tempDir),
      speechPlayer: speechPlayer ?? FakeSpeechPlayer(),
      voiceOutputPolicy: VoiceOutputPolicyController(
        authController: auth,
        store: VoiceOutputPolicyStore.memory(),
        initialPolicy: VoiceOutputPolicy.handsFreeEnabled,
      ),
    );
  }

  AuthController buildAuth(SecretaryApiClient apiClient) {
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    return auth;
  }

  Future<void> runHandsFreeUtterance(AssistantController assistant) async {
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.hardwareButton,
    );
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.hardwareButton,
    );
  }

  Future<void> startHandsFree(AssistantController assistant) {
    return assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.hardwareButton,
    );
  }

  Future<void> stopHandsFree(AssistantController assistant) {
    return assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.hardwareButton,
    );
  }

  http.Response speechOk() {
    return http.Response.bytes(
      [1, 2, 3, 4],
      200,
      headers: {'content-type': 'audio/mpeg'},
    );
  }

  http.Response jsonResponse(Object body, [int status = 200]) {
    return http.Response.bytes(
      utf8.encode(jsonEncode(body)),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );
  }

  Future<void> waitUntil(
    bool Function() condition, {
    Duration timeout = const Duration(seconds: 3),
  }) async {
    final end = DateTime.now().add(timeout);
    while (!condition()) {
      if (DateTime.now().isAfter(end)) {
        fail('timed out waiting for condition');
      }
      await Future<void>.delayed(const Duration(milliseconds: 5));
    }
  }

  test('confirmation parser is fail-closed', () {
    expect(parseVoiceConfirmation('Да'), VoiceConfirmation.approve);
    expect(parseVoiceConfirmation('  ДА.  '), VoiceConfirmation.approve);
    expect(parseVoiceConfirmation('отправляй'), VoiceConfirmation.approve);
    expect(parseVoiceConfirmation('подтверждаю'), VoiceConfirmation.approve);
    expect(parseVoiceConfirmation('да отправляй'), VoiceConfirmation.approve);
    expect(parseVoiceConfirmation('Нет'), VoiceConfirmation.reject);
    expect(parseVoiceConfirmation('не отправляй'), VoiceConfirmation.reject);
    expect(parseVoiceConfirmation('отмена'), VoiceConfirmation.reject);
    expect(
      parseVoiceConfirmation('да, но измени текст'),
      VoiceConfirmation.unknown,
    );
    expect(parseVoiceConfirmation('наверное да'), VoiceConfirmation.unknown);
    expect(parseVoiceConfirmation('может быть'), VoiceConfirmation.unknown);
    expect(parseVoiceConfirmation('yes'), VoiceConfirmation.unknown);
  });

  test('long speech is chunked in order at paragraph bounds', () {
    final paragraph = 'А' * 1200;
    final text = '$paragraph\n\n$paragraph\n\n$paragraph';
    final chunks = chunkSpeechText(text);
    expect(chunks.length, 2);
    expect(
      chunks.every((chunk) => chunk.length <= maxSpeechInputChars),
      isTrue,
    );
    expect(chunks.join(), contains('А'));
    expect(
      prepareSpeechText('**Важно** и [почта](https://x.test)'),
      'Важно и почта',
    );
  });

  test('send_email voice preview uses frozen arguments not prose', () {
    final action = PendingAction.fromJson({
      'tool_name': 'send_email',
      'arguments': {
        'to': ['ivan@example.com'],
        'subject': 'Статус',
        'body': 'Точное тело из плана.',
      },
    });
    expect(action.voiceNarrationText, contains('Кому: ivan@example.com'));
    expect(action.voiceNarrationText, contains('Тема: Статус'));
    expect(action.voiceNarrationText, contains('Точное тело из плана.'));
    expect(PendingAction.planVoicePreview([action]), contains('Отправить?'));
  });

  test('create_task is not voice-approvable', () {
    final action = PendingAction.fromJson({
      'tool_name': 'create_task',
      'arguments': {'title': 'Дело'},
    });
    expect(action.voiceNarrationText, isNull);
    expect(PendingAction.planIsVoiceApprovable([action]), isFalse);
  });

  test('voice idle-recording-transcribing-thinking-speaking-idle', () async {
    final speechPlayer = FakeSpeechPlayer(completeImmediately: false);
    var releaseMessage = false;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return jsonResponse({'text': 'Какая свежая почта?'});
      }
      if (request.url.path == '/assistant/message') {
        while (!releaseMessage) {
          await Future<void>.delayed(const Duration(milliseconds: 5));
        }
        return jsonResponse(assistantAnswer('Писем нет.'));
      }
      if (request.url.path == '/assistant/speech') {
        return speechOk();
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

    expect(assistant.voiceState, AssistantVoiceState.idle);
    await startHandsFree(assistant);
    expect(assistant.voiceState, AssistantVoiceState.recording);
    final turn = stopHandsFree(assistant);
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(
      assistant.voiceState == AssistantVoiceState.transcribing ||
          assistant.voiceState == AssistantVoiceState.thinking,
      isTrue,
    );
    releaseMessage = true;
    await waitUntil(() => assistant.voiceState == AssistantVoiceState.speaking);
    await waitUntil(() => speechPlayer.playCount > 0);
    speechPlayer.completeHeldPlay();
    await turn;
    expect(assistant.voiceState, AssistantVoiceState.idle);
    assistant.dispose();
  });

  test(
    'voice transcript uses the same sendAssistantMessage path and is visible',
    () async {
      String? sentMessage;
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/transcribe') {
          return jsonResponse({'text': 'Какая свежая почта?'});
        }
        if (request.url.path == '/assistant/message') {
          sentMessage =
              (jsonDecode(request.body) as Map<String, dynamic>)['message']
                  as String;
          return jsonResponse(assistantAnswer('Свежих писем нет.'));
        }
        if (request.url.path == '/assistant/speech') {
          return speechOk();
        }
        return http.Response('{}', 404);
      });
      final apiClient = SecretaryApiClient(httpClient: mock);
      apiClient.configure(baseUrl: baseUrl, token: token);
      final assistant = buildAssistant(
        apiClient: apiClient,
        auth: buildAuth(apiClient),
      );
      await assistant.startVoiceRecording();
      await assistant.stopVoiceRecordingAndTranscribe();
      expect(sentMessage, 'Какая свежая почта?');
      expect(assistant.messages.first.role, 'user');
      expect(assistant.messages.first.content, 'Какая свежая почта?');
      assistant.dispose();
    },
  );

  test('voice-origin answer requests speech; typed answer does not', () async {
    final speechBodies = <String>[];
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return jsonResponse({'text': 'Какая свежая почта?'});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse(assistantAnswer('Свежих писем нет.'));
      }
      if (request.url.path == '/assistant/speech') {
        speechBodies.add(utf8.decode(request.bodyBytes));
        return speechOk();
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: buildAuth(apiClient),
    );
    await assistant.sendMessage('Напечатанный вопрос');
    expect(speechBodies, isEmpty);
    await runHandsFreeUtterance(assistant);
    expect(speechBodies, isNotEmpty);
    expect(speechBodies.first, contains('Свежих писем нет.'));
    assistant.dispose();
  });

  test('long voice response is synthesized in chunk order', () async {
    final paragraph = 'Б' * 1200;
    final answer = '$paragraph\n\n$paragraph\n\n$paragraph';
    final speechTexts = <String>[];
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return jsonResponse({'text': 'Прочитай письмо'});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse(assistantAnswer(answer));
      }
      if (request.url.path == '/assistant/speech') {
        final body =
            jsonDecode(utf8.decode(request.bodyBytes)) as Map<String, dynamic>;
        speechTexts.add(body['text'] as String);
        return speechOk();
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: buildAuth(apiClient),
    );
    await runHandsFreeUtterance(assistant);
    expect(speechTexts.length, greaterThan(1));
    expect(
      speechTexts.every((text) => text.length <= maxSpeechInputChars),
      isTrue,
    );
    assistant.dispose();
  });

  test(
    'mic during speaking stops playback, clears queue, starts recording',
    () async {
      final speechPlayer = FakeSpeechPlayer(completeImmediately: false);
      var speechCalls = 0;
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/transcribe') {
          return jsonResponse({'text': 'Какая свежая почта?'});
        }
        if (request.url.path == '/assistant/message') {
          return jsonResponse(
            assistantAnswer('${'В' * 1200}\n\n${'В' * 1200}\n\n${'В' * 1200}'),
          );
        }
        if (request.url.path == '/assistant/speech') {
          speechCalls += 1;
          return speechOk();
        }
        return http.Response('{}', 404);
      });
      final apiClient = SecretaryApiClient(httpClient: mock);
      apiClient.configure(baseUrl: baseUrl, token: token);
      final recorder = FakeVoiceRecorder();
      final assistant = buildAssistant(
        apiClient: apiClient,
        auth: buildAuth(apiClient),
        voiceRecorder: recorder,
        speechPlayer: speechPlayer,
      );
      final turn = () async {
        await runHandsFreeUtterance(assistant);
      }();
      await waitUntil(
        () => assistant.voiceState == AssistantVoiceState.speaking,
      );
      final firstSpeechCalls = speechCalls;
      await assistant.startVoiceRecording();
      expect(speechPlayer.stopCount, greaterThan(0));
      expect(assistant.voiceState, AssistantVoiceState.recording);
      expect(recorder.startCallCount, greaterThanOrEqualTo(2));
      speechPlayer.completeHeldPlay();
      await turn;
      expect(speechCalls, firstSpeechCalls);
      assistant.dispose();
    },
  );

  test('stop speaking leaves conversation intact', () async {
    final speechPlayer = FakeSpeechPlayer(completeImmediately: false);
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return jsonResponse({'text': 'Какая свежая почта?'});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse(assistantAnswer('Писем нет.'));
      }
      if (request.url.path == '/assistant/speech') {
        return speechOk();
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
    final turn = () async {
      await runHandsFreeUtterance(assistant);
    }();
    await waitUntil(() => assistant.voiceState == AssistantVoiceState.speaking);
    await assistant.stopSpeaking();
    expect(assistant.messages.length, 2);
    expect(assistant.hasPendingActionPlan, isFalse);
    expect(speechPlayer.stopCount, greaterThan(0));
    await turn;
    assistant.dispose();
  });

  test('reset and dispose stop playback and delete temp audio', () async {
    final speechPlayer = FakeSpeechPlayer(completeImmediately: false);
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return jsonResponse({'text': 'Какая свежая почта?'});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse(assistantAnswer('Писем нет.'));
      }
      if (request.url.path == '/assistant/speech') {
        return speechOk();
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
    final turn = () async {
      await runHandsFreeUtterance(assistant);
    }();
    await waitUntil(() => assistant.voiceState == AssistantVoiceState.speaking);
    await waitUntil(() => speechPlayer.playCount > 0);
    await waitUntil(
      () => tempDir.listSync().whereType<File>().any(
        (file) => file.path.endsWith('.mp3'),
      ),
    );
    final leftover = tempDir
        .listSync()
        .whereType<File>()
        .where((file) => file.path.endsWith('.mp3'))
        .toList();
    expect(leftover, isNotEmpty);
    assistant.resetSession();
    await waitUntil(() => speechPlayer.stopCount > 0);
    await waitUntil(() => leftover.every((file) => !file.existsSync()));
    assistant.dispose();
    await waitUntil(() => speechPlayer.disposeCount == 1);
    await turn;
  });

  test(
    'voice pending communication plan narrates frozen args and does not write',
    () async {
      var approveCalls = 0;
      final speechTexts = <String>[];
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/transcribe') {
          return jsonResponse({'text': 'Ответь, что пришлю завтра'});
        }
        if (request.url.path == '/assistant/message') {
          return jsonResponse(pendingCommunicationPlan());
        }
        if (request.url.path.contains('/approve')) {
          approveCalls += 1;
          return http.Response('{}', 500);
        }
        if (request.url.path == '/assistant/speech') {
          final body =
              jsonDecode(utf8.decode(request.bodyBytes))
                  as Map<String, dynamic>;
          speechTexts.add(body['text'] as String);
          return speechOk();
        }
        return http.Response('{}', 404);
      });
      final apiClient = SecretaryApiClient(httpClient: mock);
      apiClient.configure(baseUrl: baseUrl, token: token);
      final assistant = buildAssistant(
        apiClient: apiClient,
        auth: buildAuth(apiClient),
      );
      await runHandsFreeUtterance(assistant);
      expect(assistant.hasPendingActionPlan, isTrue);
      expect(approveCalls, 0);
      expect(speechTexts.join('\n'), contains('Кому: ivan@example.com'));
      expect(speechTexts.join('\n'), contains('Пришлю завтра.'));
      expect(speechTexts.join('\n'), isNot(contains('Могу отправить письмо.')));
      assistant.dispose();
    },
  );

  test('Да does not approve until narration finishes', () async {
    var transcripts = <String>['Ответь Иванову', 'Да'];
    var approveCalls = 0;
    final speechPlayer = FakeSpeechPlayer(completeImmediately: false);
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        final text = transcripts.isEmpty ? 'Да' : transcripts.removeAt(0);
        return jsonResponse({'text': text});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse(pendingCommunicationPlan());
      }
      if (request.url.path.contains('/approve')) {
        approveCalls += 1;
        return http.Response('{}', 500);
      }
      if (request.url.path == '/assistant/speech') {
        return speechOk();
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
    final first = () async {
      await runHandsFreeUtterance(assistant);
    }();
    await waitUntil(() => assistant.voiceState == AssistantVoiceState.speaking);
    await assistant.startVoiceRecording();
    speechPlayer.completeImmediately = true;
    await assistant.stopVoiceRecordingAndTranscribe();
    expect(approveCalls, 0);
    expect(assistant.hasPendingActionPlan, isTrue);
    speechPlayer.completeHeldPlay();
    await first;
    assistant.dispose();
  });

  test(
    'after narration finishes exact Да approves once and rapid repeats do not',
    () async {
      var transcripts = <String>['Ответь Иванову', 'Да'];
      var approveCalls = 0;
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/transcribe') {
          final text = transcripts.isEmpty ? 'Да' : transcripts.removeAt(0);
          return jsonResponse({'text': text});
        }
        if (request.url.path == '/assistant/message') {
          return jsonResponse(pendingCommunicationPlan());
        }
        if (request.url.path.contains('/approve')) {
          approveCalls += 1;
          return jsonResponse({
            'id': 'plan-email',
            'status': 'executed',
            'expires_at': '2026-09-13T12:00:00Z',
            'actions': [],
          });
        }
        if (request.url.path.contains('/resume')) {
          return jsonResponse({
            'answer': 'Письмо отправлено.',
            'affected_objects': [],
          });
        }
        if (request.url.path == '/assistant/speech') {
          return speechOk();
        }
        return http.Response('{}', 404);
      });
      final apiClient = SecretaryApiClient(httpClient: mock);
      apiClient.configure(baseUrl: baseUrl, token: token);
      final assistant = buildAssistant(
        apiClient: apiClient,
        auth: buildAuth(apiClient),
      );
      await runHandsFreeUtterance(assistant);
      expect(assistant.hasPendingActionPlan, isTrue);
      final pendingIndex = assistant.messages.lastIndexWhere(
        (message) =>
            message.actionPlan?.cardState == ActionPlanCardState.pending,
      );
      await runHandsFreeUtterance(assistant);
      expect(approveCalls, 1);
      await Future.wait([
        assistant.approveActionPlanAt(pendingIndex),
        assistant.approveActionPlanAt(pendingIndex),
      ]);
      expect(approveCalls, 1);
      assistant.dispose();
    },
  );

  test('exact Нет rejects with zero approve', () async {
    var transcripts = <String>['Ответь Иванову', 'Нет'];
    var approveCalls = 0;
    var rejectCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        final text = transcripts.removeAt(0);
        return jsonResponse({'text': text});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse(pendingCommunicationPlan());
      }
      if (request.url.path.contains('/approve')) {
        approveCalls += 1;
        return http.Response('{}', 500);
      }
      if (request.url.path.contains('/reject')) {
        rejectCalls += 1;
        return jsonResponse({
          'id': 'plan-email',
          'status': 'rejected',
          'expires_at': '2026-09-13T12:00:00Z',
          'actions': [],
        });
      }
      if (request.url.path == '/assistant/speech') {
        return speechOk();
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: buildAuth(apiClient),
    );
    await assistant.startVoiceRecording();
    await assistant.stopVoiceRecordingAndTranscribe();
    await assistant.startVoiceRecording();
    await assistant.stopVoiceRecordingAndTranscribe();
    expect(approveCalls, 0);
    expect(rejectCalls, 1);
    expect(assistant.hasPendingActionPlan, isFalse);
    assistant.dispose();
  });

  test(
    'ambiguous confirmation does not approve, reject, or call Assistant',
    () async {
      var transcripts = <String>['Ответь Иванову', 'да, но измени текст'];
      var approveCalls = 0;
      var rejectCalls = 0;
      var messageCalls = 0;
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/transcribe') {
          return jsonResponse({'text': transcripts.removeAt(0)});
        }
        if (request.url.path == '/assistant/message') {
          messageCalls += 1;
          return jsonResponse(pendingCommunicationPlan());
        }
        if (request.url.path.contains('/approve')) {
          approveCalls += 1;
        }
        if (request.url.path.contains('/reject')) {
          rejectCalls += 1;
        }
        if (request.url.path == '/assistant/speech') {
          return speechOk();
        }
        return http.Response('{}', 404);
      });
      final apiClient = SecretaryApiClient(httpClient: mock);
      apiClient.configure(baseUrl: baseUrl, token: token);
      final assistant = buildAssistant(
        apiClient: apiClient,
        auth: buildAuth(apiClient),
      );
      await assistant.startVoiceRecording();
      await assistant.stopVoiceRecordingAndTranscribe();
      await assistant.startVoiceRecording();
      await assistant.stopVoiceRecordingAndTranscribe();
      expect(messageCalls, 1);
      expect(approveCalls, 0);
      expect(rejectCalls, 0);
      expect(assistant.hasPendingActionPlan, isTrue);
      expect(assistant.isInputBlocked, isTrue);
      assistant.dispose();
    },
  );

  test('send_message is voice-approvable after narration', () async {
    var approveCalls = 0;
    final speechTexts = <String>[];
    var transcripts = <String>['Ответь в Telegram', 'Да'];
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return jsonResponse({'text': transcripts.removeAt(0)});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse(
          pendingCommunicationPlan(
            toolName: 'send_message',
            arguments: {
              'provider': 'telegram',
              'mode': 'reply',
              'body': 'Точное исходящее тело',
              'route': {'chat_display_name': 'Ivan'},
            },
          ),
        );
      }
      if (request.url.path.contains('/approve')) {
        approveCalls += 1;
        return jsonResponse({
          'id': 'plan-email',
          'status': 'executed',
          'expires_at': '2026-09-13T12:00:00Z',
          'actions': [],
        });
      }
      if (request.url.path.contains('/resume')) {
        return jsonResponse({
          'answer': 'Сообщение отправлено.',
          'affected_objects': [],
        });
      }
      if (request.url.path == '/assistant/speech') {
        final body =
            jsonDecode(utf8.decode(request.bodyBytes)) as Map<String, dynamic>;
        speechTexts.add(body['text'] as String);
        return speechOk();
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: buildAuth(apiClient),
    );
    await runHandsFreeUtterance(assistant);
    expect(speechTexts.join('\n'), contains('Telegram'));
    expect(speechTexts.join('\n'), contains('Ivan'));
    expect(speechTexts.join('\n'), contains('Точное исходящее тело'));
    await runHandsFreeUtterance(assistant);
    expect(approveCalls, 1);
    assistant.dispose();
  });

  test(
    'unsupported create_task plan keeps visual card and disables voice approve',
    () async {
      var approveCalls = 0;
      var transcripts = <String>['Создай задачу', 'Да'];
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/transcribe') {
          return jsonResponse({'text': transcripts.removeAt(0)});
        }
        if (request.url.path == '/assistant/message') {
          return jsonResponse({
            'answer': 'Могу создать задачу.',
            'references': [],
            'affected_objects': [],
            'pending_action_plan': {
              'id': 'plan-task',
              'status': 'pending',
              'expires_at': '2026-09-13T12:00:00Z',
              'actions': [
                {
                  'tool_name': 'create_task',
                  'arguments': {'title': 'Разобрать письмо'},
                },
              ],
            },
          });
        }
        if (request.url.path.contains('/approve')) {
          approveCalls += 1;
        }
        if (request.url.path == '/assistant/speech') {
          return speechOk();
        }
        return http.Response('{}', 404);
      });
      final apiClient = SecretaryApiClient(httpClient: mock);
      apiClient.configure(baseUrl: baseUrl, token: token);
      final assistant = buildAssistant(
        apiClient: apiClient,
        auth: buildAuth(apiClient),
      );
      await assistant.startVoiceRecording();
      await assistant.stopVoiceRecordingAndTranscribe();
      expect(assistant.hasPendingActionPlan, isTrue);
      await assistant.startVoiceRecording();
      await assistant.stopVoiceRecordingAndTranscribe();
      expect(approveCalls, 0);
      expect(assistant.hasPendingActionPlan, isTrue);
      assistant.dispose();
    },
  );

  test(
    'executed plan resume answer is spoken; reject speech is accurate',
    () async {
      final speechTexts = <String>[];
      var transcripts = <String>['Ответь Иванову', 'Нет'];
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/transcribe') {
          return jsonResponse({'text': transcripts.removeAt(0)});
        }
        if (request.url.path == '/assistant/message') {
          return jsonResponse(pendingCommunicationPlan());
        }
        if (request.url.path.contains('/reject')) {
          return jsonResponse({
            'id': 'plan-email',
            'status': 'rejected',
            'expires_at': '2026-09-13T12:00:00Z',
            'actions': [],
          });
        }
        if (request.url.path == '/assistant/speech') {
          final body =
              jsonDecode(utf8.decode(request.bodyBytes))
                  as Map<String, dynamic>;
          speechTexts.add(body['text'] as String);
          return speechOk();
        }
        return http.Response('{}', 404);
      });
      final apiClient = SecretaryApiClient(httpClient: mock);
      apiClient.configure(baseUrl: baseUrl, token: token);
      final assistant = buildAssistant(
        apiClient: apiClient,
        auth: buildAuth(apiClient),
      );
      await runHandsFreeUtterance(assistant);
      await runHandsFreeUtterance(assistant);
      expect(speechTexts, contains(voiceRejectedSpeech));
      assistant.dispose();
    },
  );

  test(
    'resume failure after execute speaks completed-without-summary',
    () async {
      var transcripts = <String>['Ответь Иванову', 'Да'];
      final speechTexts = <String>[];
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/transcribe') {
          return jsonResponse({'text': transcripts.removeAt(0)});
        }
        if (request.url.path == '/assistant/message') {
          return jsonResponse(pendingCommunicationPlan());
        }
        if (request.url.path.contains('/approve')) {
          return jsonResponse({
            'id': 'plan-email',
            'status': 'executed',
            'expires_at': '2026-09-13T12:00:00Z',
            'actions': [],
          });
        }
        if (request.url.path.contains('/resume')) {
          return http.Response('{"detail":"boom"}', 502);
        }
        if (request.url.path == '/assistant/speech') {
          final body =
              jsonDecode(utf8.decode(request.bodyBytes))
                  as Map<String, dynamic>;
          speechTexts.add(body['text'] as String);
          return speechOk();
        }
        return http.Response('{}', 404);
      });
      final apiClient = SecretaryApiClient(httpClient: mock);
      apiClient.configure(baseUrl: baseUrl, token: token);
      final assistant = buildAssistant(
        apiClient: apiClient,
        auth: buildAuth(apiClient),
      );
      await runHandsFreeUtterance(assistant);
      await runHandsFreeUtterance(assistant);
      expect(
        assistant.messages.last.actionPlan?.cardState,
        ActionPlanCardState.completed,
      );
      expect(speechTexts, contains(voiceResumeFailedSpeech));
      assistant.dispose();
    },
  );

  test('TTS error does not destroy chat or pending plan', () async {
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return jsonResponse({'text': 'Ответь Иванову'});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse(pendingCommunicationPlan());
      }
      if (request.url.path == '/assistant/speech') {
        return jsonResponse({'detail': 'Speech provider unavailable'}, 502);
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: buildAuth(apiClient),
    );
    await runHandsFreeUtterance(assistant);
    expect(assistant.messages.length, 2);
    expect(assistant.hasPendingActionPlan, isTrue);
    expect(assistant.voiceState, AssistantVoiceState.error);
    assistant.dispose();
  });

  test(
    'STT error still allows retry and does not send Assistant message',
    () async {
      var messageCalls = 0;
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/transcribe') {
          return jsonResponse({
            'detail': 'Transcription provider unavailable',
          }, 502);
        }
        if (request.url.path == '/assistant/message') {
          messageCalls += 1;
        }
        return http.Response('{}', 404);
      });
      final apiClient = SecretaryApiClient(httpClient: mock);
      apiClient.configure(baseUrl: baseUrl, token: token);
      final assistant = buildAssistant(
        apiClient: apiClient,
        auth: buildAuth(apiClient),
      );
      await assistant.startVoiceRecording();
      await assistant.stopVoiceRecordingAndTranscribe();
      expect(messageCalls, 0);
      expect(assistant.voiceState, AssistantVoiceState.error);
      assistant.dispose();
    },
  );

  test('Android mic permission denial remains handled', () async {
    var transcribeCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        transcribeCalls += 1;
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final recorder = FakeVoiceRecorder()
      ..permissionGranted = false
      ..requestPermissionResult = false;
    final assistant = buildAssistant(
      apiClient: apiClient,
      auth: buildAuth(apiClient),
      voiceRecorder: recorder,
    );
    await assistant.startVoiceRecording();
    expect(transcribeCalls, 0);
    expect(assistant.voiceState, AssistantVoiceState.error);
    expect(
      assistant.voiceErrorMessage,
      const VoiceRecorderPermissionDenied().message,
    );
    assistant.dispose();
  });
}
