import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/assistant/assistant_controller.dart';
import 'package:personal_secretary/assistant/driving_silence_monitor.dart';
import 'package:personal_secretary/assistant/fake_speech_player.dart';
import 'package:personal_secretary/assistant/fake_voice_recorder.dart';
import 'package:personal_secretary/assistant/voice_capture_diagnostics.dart';
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
  const token = 'drive-silence-token';

  late Directory tempDir;

  setUp(() {
    VoiceCaptureDiagnostics.resetForTest();
    tempDir = Directory.systemTemp.createTempSync('secretary_drive_silence');
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

  AssistantController buildAssistant({
    required SecretaryApiClient apiClient,
    required FakeVoiceRecorder recorder,
    FakeSpeechPlayer? speechPlayer,
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
      voiceRecorder: recorder,
      voiceTempFiles: VoiceTempFiles(directory: tempDir),
      speechPlayer: speechPlayer ?? FakeSpeechPlayer(),
      voiceOutputPolicy: VoiceOutputPolicyController(
        authController: auth,
        store: VoiceOutputPolicyStore.memory(),
        initialPolicy: VoiceOutputPolicy.handsFreeEnabled,
      ),
      lockScreenSession: true,
    );
  }

  Future<void> waitUntil(bool Function() condition) async {
    final end = DateTime.now().add(const Duration(seconds: 8));
    while (!condition()) {
      if (DateTime.now().isAfter(end)) {
        fail('timed out waiting for condition');
      }
      await Future<void>.delayed(const Duration(milliseconds: 10));
    }
  }

  List<String> diagnosticEvents() {
    return VoiceCaptureDiagnostics.events
        .map((event) => event['event'] as String)
        .toList();
  }

  test('adaptive VAD does not treat amplitude 0 as speech', () {
    final vad = DrivingAmplitudeVad();
    expect(vad.isSpeech(0), isFalse);
    expect(vad.isSpeech(0), isFalse);
    expect(vad.isSpeech(-80), isFalse);
    expect(vad.isSpeech(-12), isTrue);
  });

  test('speech then 3s silence stops once via canonical path', () async {
    var transcribeCalls = 0;
    final recorder = FakeVoiceRecorder();
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        transcribeCalls += 1;
        return jsonResponse({'text': 'что нового'});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse({
          'answer': 'ok',
          'references': [],
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
    final assistant = buildAssistant(apiClient: apiClient, recorder: recorder);
    assistant.lockScreenVoiceEnabled = true;
    await assistant.startVoiceRecording(
      source: VoiceInvocationSource.lockScreenLauncher,
    );
    recorder.emitAmplitude(-80);
    recorder.emitAmplitude(-12);
    recorder.emitAmplitude(-80);
    expect(recorder.stopCallCount, 0);
    await Future<void>.delayed(const Duration(seconds: 3, milliseconds: 80));
    await waitUntil(() => recorder.stopCallCount == 1);
    expect(transcribeCalls, 1);
    expect(diagnosticEvents(), contains('silence_monitor_started'));
    expect(diagnosticEvents(), contains('speech_detected'));
    expect(diagnosticEvents(), contains('silence_auto_stop_triggered'));
    expect(diagnosticEvents(), contains('stop_trigger'));
    assistant.dispose();
  });

  test('2.9s silence after speech does not stop', () async {
    final recorder = FakeVoiceRecorder();
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return jsonResponse({'text': 'x'});
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final assistant = buildAssistant(apiClient: apiClient, recorder: recorder);
    await assistant.startVoiceRecording(
      source: VoiceInvocationSource.lockScreenLauncher,
    );
    recorder.emitAmplitude(-80);
    recorder.emitAmplitude(-12);
    recorder.emitAmplitude(-80);
    await Future<void>.delayed(const Duration(milliseconds: 2900));
    expect(recorder.stopCallCount, 0);
    expect(assistant.voiceState, AssistantVoiceState.recording);
    await assistant.cancelVoiceRecording();
    assistant.dispose();
  });

  test('speech after silence resets the 3s interval', () async {
    final recorder = FakeVoiceRecorder();
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return jsonResponse({'text': 'x'});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse({
          'answer': 'ok',
          'references': [],
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
    final assistant = buildAssistant(apiClient: apiClient, recorder: recorder);
    await assistant.startVoiceRecording(
      source: VoiceInvocationSource.lockScreenLauncher,
    );
    recorder.emitAmplitude(-80);
    recorder.emitAmplitude(-12);
    recorder.emitAmplitude(-80);
    await Future<void>.delayed(const Duration(milliseconds: 2000));
    recorder.emitAmplitude(-12);
    recorder.emitAmplitude(-80);
    await Future<void>.delayed(const Duration(milliseconds: 2900));
    expect(recorder.stopCallCount, 0);
    await Future<void>.delayed(const Duration(milliseconds: 200));
    await waitUntil(() => recorder.stopCallCount == 1);
    assistant.dispose();
  });

  test('no speech does not auto-stop after 3s', () async {
    final recorder = FakeVoiceRecorder();
    final mock = MockClient((_) async => http.Response('{}', 404));
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final assistant = buildAssistant(apiClient: apiClient, recorder: recorder);
    await assistant.startVoiceRecording(
      source: VoiceInvocationSource.lockScreenLauncher,
    );
    recorder.emitAmplitude(0);
    recorder.emitAmplitude(-90);
    recorder.emitAmplitude(-80);
    await Future<void>.delayed(const Duration(seconds: 3, milliseconds: 80));
    expect(recorder.stopCallCount, 0);
    expect(assistant.voiceState, AssistantVoiceState.recording);
    expect(diagnosticEvents(), isNot(contains('speech_detected')));
    expect(diagnosticEvents(), isNot(contains('silence_auto_stop_triggered')));
    await assistant.cancelVoiceRecording();
    assistant.dispose();
  });

  test('manual stop before timeout is a single canonical stop', () async {
    var transcribeCalls = 0;
    final recorder = FakeVoiceRecorder();
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        transcribeCalls += 1;
        return jsonResponse({'text': 'x'});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse({
          'answer': 'ok',
          'references': [],
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
    final assistant = buildAssistant(apiClient: apiClient, recorder: recorder);
    await assistant.startVoiceRecording(
      source: VoiceInvocationSource.lockScreenLauncher,
    );
    recorder.emitAmplitude(-12);
    recorder.emitAmplitude(-80);
    await assistant.stopVoiceRecordingAndTranscribe();
    await Future<void>.delayed(const Duration(seconds: 3, milliseconds: 50));
    expect(recorder.stopCallCount, 1);
    expect(transcribeCalls, 1);
    expect(diagnosticEvents(), contains('silence_monitor_cancelled'));
    assistant.dispose();
  });

  test('simultaneous manual and auto stop still stops once', () async {
    var transcribeCalls = 0;
    final recorder = FakeVoiceRecorder();
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        transcribeCalls += 1;
        return jsonResponse({'text': 'x'});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse({
          'answer': 'ok',
          'references': [],
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
    final assistant = buildAssistant(apiClient: apiClient, recorder: recorder);
    await assistant.startVoiceRecording(
      source: VoiceInvocationSource.lockScreenLauncher,
    );
    recorder.emitAmplitude(-80);
    recorder.emitAmplitude(-12);
    recorder.emitAmplitude(-80);
    await Future<void>.delayed(const Duration(milliseconds: 2980));
    final manual = assistant.stopVoiceRecordingAndTranscribe();
    await Future<void>.delayed(const Duration(milliseconds: 80));
    await manual;
    await assistant.stopVoiceRecordingAndTranscribe();
    expect(recorder.stopCallCount, 1);
    expect(transcribeCalls, 1);
    assistant.dispose();
  });

  test('screenMic is unchanged and does not auto-stop', () async {
    final recorder = FakeVoiceRecorder();
    final mock = MockClient((_) async => http.Response('{}', 404));
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final assistant = buildAssistant(apiClient: apiClient, recorder: recorder);
    await assistant.startVoiceRecording(
      source: VoiceInvocationSource.screenMic,
    );
    recorder.emitAmplitude(-12);
    recorder.emitAmplitude(-80);
    await Future<void>.delayed(const Duration(seconds: 3, milliseconds: 50));
    expect(recorder.stopCallCount, 0);
    expect(diagnosticEvents(), isNot(contains('silence_monitor_started')));
    await assistant.cancelVoiceRecording();
    assistant.dispose();
  });

  test('hardware trigger is unchanged and does not auto-stop', () async {
    final recorder = FakeVoiceRecorder();
    final mock = MockClient((_) async => http.Response('{}', 404));
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final assistant = buildAssistant(apiClient: apiClient, recorder: recorder);
    assistant.lockScreenVoiceEnabled = true;
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.hardwareButton,
    );
    expect(assistant.voiceState, AssistantVoiceState.recording);
    recorder.emitAmplitude(-12);
    recorder.emitAmplitude(-80);
    await Future<void>.delayed(const Duration(seconds: 3, milliseconds: 50));
    expect(recorder.stopCallCount, 0);
    expect(diagnosticEvents(), isNot(contains('silence_monitor_started')));
    await assistant.cancelVoiceRecording();
    assistant.dispose();
  });

  test('pending-plan Да works through auto-stop', () async {
    var transcripts = <String>['Ответь Иванову', 'Да'];
    var approveCalls = 0;
    final recorder = FakeVoiceRecorder();
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        final text = transcripts.isEmpty ? 'Да' : transcripts.removeAt(0);
        return jsonResponse({'text': text});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse({
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
        });
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
    final assistant = buildAssistant(apiClient: apiClient, recorder: recorder);
    assistant.keyguardLocked = true;
    assistant.lockScreenVoiceEnabled = true;
    assistant.setDrivingSession(authorized: true, sessionId: 'drive-1');
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.lockScreenLauncher,
    );
    recorder.emitAmplitude(-80);
    recorder.emitAmplitude(-12);
    recorder.emitAmplitude(-80);
    await Future<void>.delayed(const Duration(seconds: 3, milliseconds: 80));
    await waitUntil(() => assistant.hasPendingActionPlan);
    expect(assistant.voiceApprovalArmed, isTrue);
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.lockScreenLauncher,
    );
    recorder.emitAmplitude(-80);
    recorder.emitAmplitude(-12);
    recorder.emitAmplitude(-80);
    await Future<void>.delayed(const Duration(seconds: 3, milliseconds: 80));
    await waitUntil(() => approveCalls == 1);
    expect(recorder.stopCallCount, 2);
    assistant.dispose();
  });

  test('Android minSdk remains 23', () {
    final gradle = File('android/app/build.gradle.kts').readAsStringSync();
    expect(gradle, contains('android.defaultConfig.minSdk = 23'));
  });
}
