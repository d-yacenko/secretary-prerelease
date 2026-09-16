import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/assistant/assistant_controller.dart';
import 'package:personal_secretary/assistant/fake_speech_player.dart';
import 'package:personal_secretary/assistant/fake_voice_recorder.dart';
import 'package:personal_secretary/assistant/voice_invocation_source.dart';
import 'package:personal_secretary/assistant/voice_temp_files.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';

void main() {
  const baseUrl = 'https://secretary.example';
  const token = 'lock-voice-token';

  late Directory tempDir;

  setUp(() {
    tempDir = Directory.systemTemp.createTempSync('secretary_lock_voice_test');
  });

  tearDown(() {
    if (tempDir.existsSync()) {
      tempDir.deleteSync(recursive: true);
    }
  });

  http.Response jsonResponse(Object body) {
    return http.Response.bytes(
      utf8.encode(jsonEncode(body)),
      200,
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

  Map<String, dynamic> pendingCommunicationPlan() {
    return {
      'answer': 'Могу отправить письмо.',
      'references': [],
      'affected_objects': [],
      'pending_action_plan': {
        'id': 'plan-email',
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

  AssistantController buildAssistant({
    required SecretaryApiClient apiClient,
    bool lockScreenSession = true,
    FakeVoiceRecorder? voiceRecorder,
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
      voiceRecorder: voiceRecorder ?? FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(directory: tempDir),
      speechPlayer: FakeSpeechPlayer(),
      lockScreenSession: lockScreenSession,
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

  test('Да does not approve a locked lock-screen session', () async {
    var transcripts = <String>['Ответь Иванову', 'Да'];
    var approveCalls = 0;
    final spoken = <String>[];
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
        spoken.add(utf8.decode(request.bodyBytes));
        return speechOk();
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final assistant = buildAssistant(apiClient: apiClient);
    assistant.keyguardLocked = true;
    assistant.lockScreenVoiceEnabled = true;
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.systemAssistant,
    );
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.systemAssistant,
    );
    await waitUntil(() => assistant.hasPendingActionPlan);
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.systemAssistant,
    );
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.systemAssistant,
    );
    await waitUntil(() => spoken.isNotEmpty);
    expect(approveCalls, 0);
    expect(assistant.hasPendingActionPlan, isTrue);
    expect(spoken.join('\n'), contains('разблокировать'));
    expect(spoken.join('\n'), isNot(contains('Пришлю завтра.')));
    assistant.dispose();
  });

  test('visual approve is blocked while keyguard is locked', () async {
    var approveCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return jsonResponse({'text': 'Ответь Иванову'});
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
    final assistant = buildAssistant(apiClient: apiClient);
    assistant.keyguardLocked = true;
    assistant.lockScreenVoiceEnabled = true;
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.systemAssistant,
    );
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.systemAssistant,
    );
    await waitUntil(() => assistant.hasPendingActionPlan);
    await assistant.approveActionPlanAt(1);
    expect(approveCalls, 0);
    assistant.dispose();
  });

  test('lockScreenLauncher external write remains blocked while locked', () async {
    var approveCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return jsonResponse({'text': 'Ответь Иванову'});
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
    final assistant = buildAssistant(apiClient: apiClient);
    assistant.keyguardLocked = true;
    assistant.lockScreenVoiceEnabled = true;
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.lockScreenLauncher,
    );
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.lockScreenLauncher,
    );
    await waitUntil(() => assistant.hasPendingActionPlan);
    await assistant.approveActionPlanAt(1);
    expect(approveCalls, 0);
    expect(assistant.blocksExternalWrite, isTrue);
    assistant.dispose();
  });

  test('exact Нет still rejects while locked', () async {
    var transcripts = <String>['Ответь Иванову', 'Нет'];
    var approveCalls = 0;
    var rejectCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        final text = transcripts.isEmpty ? 'Нет' : transcripts.removeAt(0);
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
    final assistant = buildAssistant(apiClient: apiClient);
    assistant.keyguardLocked = true;
    assistant.lockScreenVoiceEnabled = true;
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.systemAssistant,
    );
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.systemAssistant,
    );
    await waitUntil(() => assistant.hasPendingActionPlan);
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.systemAssistant,
    );
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.systemAssistant,
    );
    await waitUntil(() => rejectCalls == 1);
    expect(approveCalls, 0);
    expect(assistant.hasPendingActionPlan, isFalse);
    assistant.dispose();
  });

  test('locked session without opt-in does not start recording', () async {
    final recorder = FakeVoiceRecorder();
    final mock = MockClient((request) async => http.Response('{}', 404));
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final assistant = buildAssistant(
      apiClient: apiClient,
      voiceRecorder: recorder,
    );
    assistant.keyguardLocked = true;
    assistant.lockScreenVoiceEnabled = false;
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.systemAssistant,
    );
    expect(recorder.startCallCount, 0);
    expect(assistant.voiceState, AssistantVoiceState.idle);
    assistant.dispose();
  });

  test('visual approve works after unlock', () async {
    var approveCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return jsonResponse({'text': 'Ответь Иванову'});
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
    final assistant = buildAssistant(apiClient: apiClient);
    assistant.keyguardLocked = true;
    assistant.lockScreenVoiceEnabled = true;
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.systemAssistant,
    );
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.systemAssistant,
    );
    await waitUntil(() => assistant.hasPendingActionPlan);
    await assistant.approveActionPlanAt(1);
    expect(approveCalls, 0);
    assistant.keyguardLocked = false;
    await assistant.approveActionPlanAt(1);
    expect(approveCalls, 1);
    assistant.dispose();
  });
}
