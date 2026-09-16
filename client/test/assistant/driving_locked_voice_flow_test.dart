import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/assistant/assistant_controller.dart';
import 'package:personal_secretary/assistant/fake_speech_player.dart';
import 'package:personal_secretary/assistant/fake_voice_recorder.dart';
import 'package:personal_secretary/assistant/voice_confirmation.dart';
import 'package:personal_secretary/assistant/voice_invocation_source.dart';
import 'package:personal_secretary/assistant/voice_output_policy.dart';
import 'package:personal_secretary/assistant/voice_output_policy_controller.dart';
import 'package:personal_secretary/assistant/voice_output_policy_store.dart';
import 'package:personal_secretary/assistant/voice_temp_files.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';

void main() {
  const baseUrl = 'https://secretary.example';
  const token = 'drive-voice-token';
  const sessionId = 'drive-1';

  late Directory tempDir;

  setUp(() {
    tempDir = Directory.systemTemp.createTempSync('secretary_drive_voice');
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

  Map<String, dynamic> emailPlan({String planId = 'plan-email'}) {
    return {
      'answer': 'Могу отправить письмо.',
      'references': [],
      'affected_objects': [],
      'pending_action_plan': {
        'id': planId,
        'status': 'pending',
        'expires_at': '2026-09-13T12:00:00Z',
        'actions': [
          {
            'tool_name': 'send_email',
            'arguments': {
              'to': ['ivan@example.com'],
              'subject': 'Статус',
              'body': 'Пришлю завтра.',
            },
          },
        ],
      },
    };
  }

  Map<String, dynamic> messagePlan() {
    return {
      'answer': 'Могу отправить сообщение.',
      'references': [],
      'affected_objects': [],
      'pending_action_plan': {
        'id': 'plan-message',
        'status': 'pending',
        'expires_at': '2026-09-13T12:00:00Z',
        'actions': [
          {
            'tool_name': 'send_message',
            'arguments': {
              'provider': 'telegram',
              'mode': 'reply',
              'body': 'Точное исходящее тело',
              'route': {'chat_display_name': 'Ivan'},
            },
          },
        ],
      },
    };
  }

  AssistantController buildAssistant({
    required SecretaryApiClient apiClient,
    FakeSpeechPlayer? speechPlayer,
    bool lockScreenSession = true,
  }) {
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    return AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(directory: tempDir),
      speechPlayer: speechPlayer ?? FakeSpeechPlayer(),
      voiceOutputPolicy: VoiceOutputPolicyController(
        authController: auth,
        store: VoiceOutputPolicyStore.memory(),
        initialPolicy: VoiceOutputPolicy.handsFreeEnabled,
      ),
      lockScreenSession: lockScreenSession,
    );
  }

  void armDriving(AssistantController assistant, {String id = sessionId}) {
    assistant.keyguardLocked = true;
    assistant.lockScreenVoiceEnabled = true;
    assistant.setDrivingSession(authorized: true, sessionId: id);
  }

  Future<void> runLauncher(AssistantController assistant) async {
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.lockScreenLauncher,
    );
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.lockScreenLauncher,
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

  String speechText(http.Request request) {
    final body =
        jsonDecode(utf8.decode(request.bodyBytes)) as Map<String, dynamic>;
    return body['text'] as String;
  }

  test('authorized locked send_email narrates then Да executes', () async {
    var transcripts = <String>['Ответь Иванову', 'Да'];
    var approveCalls = 0;
    final spoken = <String>[];
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        final text = transcripts.isEmpty ? 'Да' : transcripts.removeAt(0);
        return jsonResponse({'text': text});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse(emailPlan());
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
        spoken.add(speechText(request));
        return speechOk();
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final assistant = buildAssistant(apiClient: apiClient);
    armDriving(assistant);
    await runLauncher(assistant);
    await waitUntil(() => assistant.hasPendingActionPlan);
    expect(spoken.join('\n'), contains('Кому: ivan@example.com'));
    expect(spoken.join('\n'), contains('Пришлю завтра.'));
    expect(spoken.join('\n'), contains('Отправить?'));
    expect(spoken.join('\n'), isNot(contains('разблокировать')));
    expect(spoken.join('\n'), isNot(contains('Могу отправить письмо.')));
    expect(assistant.voiceApprovalArmed, isTrue);
    await runLauncher(assistant);
    await waitUntil(() => approveCalls == 1);
    expect(assistant.keyguardLocked, isTrue);
    expect(assistant.hasPendingActionPlan, isFalse);
    expect(spoken.join('\n'), contains('Письмо отправлено.'));
    assistant.dispose();
  });

  test('authorized locked send_email exact Нет rejects', () async {
    var transcripts = <String>['Ответь Иванову', 'Нет'];
    var approveCalls = 0;
    var rejectCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        final text = transcripts.isEmpty ? 'Нет' : transcripts.removeAt(0);
        return jsonResponse({'text': text});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse(emailPlan());
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
    final assistant = buildAssistant(apiClient: apiClient);
    armDriving(assistant);
    await runLauncher(assistant);
    await waitUntil(() => assistant.hasPendingActionPlan);
    await runLauncher(assistant);
    await waitUntil(() => rejectCalls == 1);
    expect(approveCalls, 0);
    expect(assistant.hasPendingActionPlan, isFalse);
    assistant.dispose();
  });

  test('interrupted narration plus Да does not execute', () async {
    var transcripts = <String>['Ответь Иванову', 'Да'];
    var approveCalls = 0;
    final speechPlayer = FakeSpeechPlayer(completeImmediately: false);
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        final text = transcripts.isEmpty ? 'Да' : transcripts.removeAt(0);
        return jsonResponse({'text': text});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse(emailPlan());
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
      speechPlayer: speechPlayer,
    );
    armDriving(assistant);
    final first = runLauncher(assistant);
    await waitUntil(() => assistant.voiceState == AssistantVoiceState.speaking);
    expect(assistant.voiceApprovalArmed, isFalse);
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.lockScreenLauncher,
    );
    speechPlayer.completeImmediately = true;
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.lockScreenLauncher,
    );
    await waitUntil(() => transcripts.isEmpty || approveCalls > 0);
    expect(approveCalls, 0);
    expect(assistant.hasPendingActionPlan, isTrue);
    speechPlayer.completeHeldPlay();
    await first;
    assistant.dispose();
  });

  test('TTS error plus Да does not execute', () async {
    var transcripts = <String>['Ответь Иванову', 'Да'];
    var approveCalls = 0;
    final speechPlayer = FakeSpeechPlayer()..failNextPlay = true;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        final text = transcripts.isEmpty ? 'Да' : transcripts.removeAt(0);
        return jsonResponse({'text': text});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse(emailPlan());
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
      speechPlayer: speechPlayer,
    );
    armDriving(assistant);
    await runLauncher(assistant);
    await waitUntil(() => assistant.hasPendingActionPlan);
    expect(assistant.voiceApprovalArmed, isFalse);
    expect(assistant.voiceState, AssistantVoiceState.error);
    assistant.clearVoiceError();
    await runLauncher(assistant);
    await waitUntil(() => transcripts.isEmpty || approveCalls > 0);
    expect(approveCalls, 0);
    assistant.dispose();
  });

  test('authorized locked send_message narrates then Да executes', () async {
    var transcripts = <String>['Ответь в Telegram', 'Да'];
    var approveCalls = 0;
    final spoken = <String>[];
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        final text = transcripts.isEmpty ? 'Да' : transcripts.removeAt(0);
        return jsonResponse({'text': text});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse(messagePlan());
      }
      if (request.url.path.contains('/approve')) {
        approveCalls += 1;
        return jsonResponse({
          'id': 'plan-message',
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
        spoken.add(speechText(request));
        return speechOk();
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final assistant = buildAssistant(apiClient: apiClient);
    armDriving(assistant);
    await runLauncher(assistant);
    await waitUntil(() => assistant.hasPendingActionPlan);
    expect(spoken.join('\n'), contains('Telegram'));
    expect(spoken.join('\n'), contains('Ivan'));
    expect(spoken.join('\n'), contains('Точное исходящее тело'));
    expect(spoken.join('\n'), contains('Отправить?'));
    expect(assistant.voiceApprovalArmed, isTrue);
    await runLauncher(assistant);
    await waitUntil(() => approveCalls == 1);
    expect(assistant.keyguardLocked, isTrue);
    assistant.dispose();
  });

  test('unsupported and mixed locked plans stay blocked', () async {
    Future<void> expectBlocked(Map<String, dynamic> planJson) async {
      var transcripts = <String>['Сделай это', 'Да'];
      var approveCalls = 0;
      final spoken = <String>[];
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/transcribe') {
          final text = transcripts.isEmpty ? 'Да' : transcripts.removeAt(0);
          return jsonResponse({'text': text});
        }
        if (request.url.path == '/assistant/message') {
          return jsonResponse(planJson);
        }
        if (request.url.path.contains('/approve')) {
          approveCalls += 1;
          return http.Response('{}', 500);
        }
        if (request.url.path == '/assistant/speech') {
          spoken.add(speechText(request));
          return speechOk();
        }
        return http.Response('{}', 404);
      });
      final apiClient = SecretaryApiClient(httpClient: mock);
      apiClient.configure(baseUrl: baseUrl, token: token);
      final assistant = buildAssistant(apiClient: apiClient);
      armDriving(assistant);
      await runLauncher(assistant);
      await waitUntil(() => assistant.hasPendingActionPlan);
      expect(spoken.join('\n'), contains('разблокировать'));
      await runLauncher(assistant);
      await waitUntil(() => transcripts.isEmpty || spoken.length > 1);
      expect(approveCalls, 0);
      expect(assistant.hasPendingActionPlan, isTrue);
      assistant.dispose();
    }

    await expectBlocked({
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
    await expectBlocked({
      'answer': 'Могу отправить и создать.',
      'references': [],
      'affected_objects': [],
      'pending_action_plan': {
        'id': 'plan-mixed',
        'status': 'pending',
        'expires_at': '2026-09-13T12:00:00Z',
        'actions': [
          {
            'tool_name': 'send_email',
            'arguments': {
              'to': ['ivan@example.com'],
              'subject': 'Статус',
              'body': 'Пришлю завтра.',
            },
          },
          {
            'tool_name': 'create_task',
            'arguments': {'title': 'Разобрать письмо'},
          },
        ],
      },
    });
    await expectBlocked({
      'answer': 'Могу удалить задачу.',
      'references': [],
      'affected_objects': [],
      'pending_action_plan': {
        'id': 'plan-delete',
        'status': 'pending',
        'expires_at': '2026-09-13T12:00:00Z',
        'actions': [
          {
            'tool_name': 'delete_task',
            'arguments': {'title': 'Старая задача'},
          },
        ],
      },
    });
  });

  test('screenMic and typed plans cannot leak into driving approval', () async {
    Future<void> expectNoApprove(VoiceInvocationSource source) async {
      var transcripts = <String>['Да'];
      var approveCalls = 0;
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/transcribe') {
          final text = transcripts.isEmpty ? 'Да' : transcripts.removeAt(0);
          return jsonResponse({'text': text});
        }
        if (request.url.path == '/assistant/message') {
          return jsonResponse(emailPlan());
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
      final assistant = buildAssistant(apiClient: apiClient);
      armDriving(assistant);
      await assistant.sendMessage('Ответь Иванову', source: source);
      await waitUntil(() => assistant.hasPendingActionPlan);
      await runLauncher(assistant);
      await waitUntil(() => transcripts.isEmpty || approveCalls > 0);
      expect(approveCalls, 0);
      expect(assistant.hasPendingActionPlan, isTrue);
      assistant.dispose();
    }

    await expectNoApprove(VoiceInvocationSource.screenMic);
    await expectNoApprove(VoiceInvocationSource.typed);
  });

  test('previous driving session plan cannot leak into a new session', () async {
    var transcripts = <String>['Ответь Иванову', 'Да'];
    var approveCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        final text = transcripts.isEmpty ? 'Да' : transcripts.removeAt(0);
        return jsonResponse({'text': text});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse(emailPlan());
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
    final assistant = buildAssistant(apiClient: apiClient);
    armDriving(assistant, id: 'sess-a');
    await runLauncher(assistant);
    await waitUntil(() => assistant.hasPendingActionPlan);
    assistant.setDrivingSession(authorized: true, sessionId: 'sess-b');
    assistant.keyguardLocked = true;
    await runLauncher(assistant);
    await waitUntil(() => transcripts.isEmpty || approveCalls > 0);
    expect(approveCalls, 0);
    expect(assistant.hasPendingActionPlan, isTrue);
    assistant.dispose();
  });

  test('generic visual approve while locked remains blocked', () async {
    var approveCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return jsonResponse({'text': 'Ответь Иванову'});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse(emailPlan());
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
    final assistant = buildAssistant(apiClient: apiClient);
    armDriving(assistant);
    await runLauncher(assistant);
    await waitUntil(() => assistant.hasPendingActionPlan);
    await assistant.approveActionPlanAt(1);
    expect(approveCalls, 0);
    expect(assistant.blocksExternalWrite, isTrue);
    assistant.dispose();
  });

  test('unlocked normal voice confirmation is unchanged', () async {
    var transcripts = <String>['Ответь Иванову', 'Да'];
    var approveCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        final text = transcripts.isEmpty ? 'Да' : transcripts.removeAt(0);
        return jsonResponse({'text': text});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse(emailPlan());
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
      lockScreenSession: false,
    );
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.hardwareButton,
    );
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.hardwareButton,
    );
    await waitUntil(() => assistant.hasPendingActionPlan);
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.hardwareButton,
    );
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.hardwareButton,
    );
    await waitUntil(() => approveCalls == 1);
    assistant.dispose();
  });

  test('voice confirmation parser remains exact', () {
    expect(parseVoiceConfirmation('Да'), VoiceConfirmation.approve);
    expect(parseVoiceConfirmation('Нет'), VoiceConfirmation.reject);
    expect(parseVoiceConfirmation('наверное да'), VoiceConfirmation.unknown);
  });
}
