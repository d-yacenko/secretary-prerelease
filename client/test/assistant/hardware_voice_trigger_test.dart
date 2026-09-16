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
import 'package:personal_secretary/assistant/voice_local_feedback.dart';
import 'package:personal_secretary/assistant/voice_temp_files.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';

void main() {
  const baseUrl = 'https://secretary.example';
  const token = 'hw-voice-token';

  late Directory tempDir;

  setUp(() {
    tempDir = Directory.systemTemp.createTempSync('secretary_hw_voice_test');
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
    FakeVoiceRecorder? recorder,
    FakeSpeechPlayer? speechPlayer,
    VoiceLocalFeedback? voiceFeedback,
    bool lockScreenSession = false,
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
      voiceRecorder: recorder ?? FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(directory: tempDir),
      speechPlayer: speechPlayer ?? FakeSpeechPlayer(),
      voiceFeedback: voiceFeedback,
      lockScreenSession: lockScreenSession,
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
      await Future<void>.delayed(const Duration(milliseconds: 10));
    }
  }

  test('hardware trigger idle starts recording', () async {
    final recorder = FakeVoiceRecorder();
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((_) async => http.Response('{}', 404)),
    );
    apiClient.configure(baseUrl: baseUrl, token: token);
    final assistant = buildAssistant(apiClient: apiClient, recorder: recorder);
    expect(assistant.voiceState, AssistantVoiceState.idle);
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.hardwareButton,
    );
    expect(assistant.voiceState, AssistantVoiceState.recording);
    expect(recorder.startCallCount, 1);
    assistant.dispose();
  });

  test('hardware trigger recording stops and transcribes', () async {
    String? sent;
    final recorder = FakeVoiceRecorder();
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return jsonResponse({'text': 'привет'});
      }
      if (request.url.path == '/assistant/message') {
        sent =
            (jsonDecode(request.body) as Map<String, dynamic>)['message']
                as String;
        return jsonResponse({
          'answer': 'ок',
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
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.hardwareButton,
    );
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.hardwareButton,
    );
    expect(sent, 'привет');
    expect(recorder.stopCallCount, 1);
    assistant.dispose();
  });

  test('hardware trigger speaking stops TTS then starts recording', () async {
    final recorder = FakeVoiceRecorder();
    final speechPlayer = FakeSpeechPlayer(completeImmediately: false);
    var releaseMessage = false;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return jsonResponse({'text': 'вопрос'});
      }
      if (request.url.path == '/assistant/message') {
        while (!releaseMessage) {
          await Future<void>.delayed(const Duration(milliseconds: 5));
        }
        return jsonResponse({
          'answer': 'ответ',
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
    final assistant = buildAssistant(
      apiClient: apiClient,
      recorder: recorder,
      speechPlayer: speechPlayer,
    );
    final turn = () async {
      await assistant.handleVoiceTrigger(
        source: VoiceInvocationSource.hardwareButton,
      );
      await assistant.handleVoiceTrigger(
        source: VoiceInvocationSource.hardwareButton,
      );
    }();
    releaseMessage = true;
    await waitUntil(() => assistant.voiceState == AssistantVoiceState.speaking);
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.hardwareButton,
    );
    expect(speechPlayer.stopCount, greaterThan(0));
    expect(assistant.voiceState, AssistantVoiceState.recording);
    expect(recorder.startCallCount, greaterThanOrEqualTo(2));
    speechPlayer.completeHeldPlay();
    await turn;
    assistant.dispose();
  });

  test(
    'hardware trigger during transcribing does not duplicate the turn',
    () async {
      final recorder = FakeVoiceRecorder(audioBytes: [1, 2, 3]);
      recorder.stopDelay = const Duration(milliseconds: 80);
      var transcribeCalls = 0;
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/transcribe') {
          transcribeCalls += 1;
          await Future<void>.delayed(const Duration(milliseconds: 80));
          return jsonResponse({'text': 'раз'});
        }
        if (request.url.path == '/assistant/message') {
          return jsonResponse({
            'answer': 'два',
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
      final assistant = buildAssistant(
        apiClient: apiClient,
        recorder: recorder,
      );
      await assistant.handleVoiceTrigger(
        source: VoiceInvocationSource.hardwareButton,
      );
      final stop = assistant.handleVoiceTrigger(
        source: VoiceInvocationSource.hardwareButton,
      );
      await Future<void>.delayed(const Duration(milliseconds: 20));
      await assistant.handleVoiceTrigger(
        source: VoiceInvocationSource.hardwareButton,
      );
      await assistant.handleVoiceTrigger(
        source: VoiceInvocationSource.hardwareButton,
      );
      await stop;
      expect(recorder.startCallCount, 1);
      expect(transcribeCalls, 1);
      assistant.dispose();
    },
  );

  test(
    'hardware trigger with pending plan uses voice confirmation path',
    () async {
      var transcripts = <String>['отправь письмо', 'нет'];
      var rejectCalls = 0;
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/transcribe') {
          final text = transcripts.isEmpty ? 'нет' : transcripts.removeAt(0);
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
      await waitUntil(() => rejectCalls == 1);
      expect(assistant.hasPendingActionPlan, isFalse);
      assistant.dispose();
    },
  );

  test(
    'ack plays immediately and ready completes before recorder start',
    () async {
      final recorder = FakeVoiceRecorder();
      final cues = RecordingVoiceLocalFeedback(
        isRecorderActive: () => recorder.isRecording,
      );
      var readyBeforeStart = 0;
      recorder.onStart = () => readyBeforeStart = cues.readyCount;
      final apiClient = SecretaryApiClient(
        httpClient: MockClient((_) async => http.Response('{}', 404)),
      );
      apiClient.configure(baseUrl: baseUrl, token: token);
      final assistant = buildAssistant(
        apiClient: apiClient,
        recorder: recorder,
        voiceFeedback: cues,
      );
      await assistant.handleVoiceTrigger(
        source: VoiceInvocationSource.hardwareButton,
      );
      expect(cues.ackCount, 1);
      expect(cues.readyCount, 1);
      expect(readyBeforeStart, 1);
      expect(recorder.startCallCount, 1);
      expect(cues.mediaWhileRecording, isEmpty);
      assistant.dispose();

      final skipped = RecordingVoiceLocalFeedback();
      final second = buildAssistant(
        apiClient: apiClient,
        recorder: FakeVoiceRecorder(),
        voiceFeedback: skipped,
      );
      await second.handleVoiceTrigger(
        source: VoiceInvocationSource.hardwareButton,
        startCueAlreadyPlayed: true,
      );
      expect(skipped.ackCount, 0);
      expect(skipped.readyCount, 1);
      second.dispose();
    },
  );

  test(
    'ready cue is not played when microphone permission is denied',
    () async {
      final cues = RecordingVoiceLocalFeedback();
      final recorder = FakeVoiceRecorder()
        ..permissionGranted = false
        ..requestPermissionResult = false;
      final apiClient = SecretaryApiClient(
        httpClient: MockClient((_) async => http.Response('{}', 404)),
      );
      apiClient.configure(baseUrl: baseUrl, token: token);
      final assistant = buildAssistant(
        apiClient: apiClient,
        recorder: recorder,
        voiceFeedback: cues,
      );
      await assistant.handleVoiceTrigger(
        source: VoiceInvocationSource.hardwareButton,
      );
      expect(cues.ackCount, 1);
      expect(cues.readyCount, 0);
      expect(assistant.voiceState, AssistantVoiceState.error);
      assistant.dispose();
    },
  );

  test('hands-free ready cue may play before a later start failure', () async {
    final cues = RecordingVoiceLocalFeedback();
    final recorder = FakeVoiceRecorder()..failStart = true;
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((_) async => http.Response('{}', 404)),
    );
    apiClient.configure(baseUrl: baseUrl, token: token);
    final assistant = buildAssistant(
      apiClient: apiClient,
      recorder: recorder,
      voiceFeedback: cues,
    );
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.hardwareButton,
    );
    expect(cues.ackCount, 1);
    expect(cues.readyCount, 1);
    expect(assistant.voiceState, AssistantVoiceState.error);
    assistant.dispose();
  });

  test('stop cue plays only after the recorder has stopped', () async {
    final recorder = FakeVoiceRecorder();
    final cues = RecordingVoiceLocalFeedback(
      isRecorderActive: () => recorder.isRecording,
    );
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return jsonResponse({'text': 'привет'});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse({
          'answer': 'ок',
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
    final assistant = buildAssistant(
      apiClient: apiClient,
      recorder: recorder,
      voiceFeedback: cues,
    );
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.hardwareButton,
    );
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.hardwareButton,
    );
    await waitUntil(() => cues.stopCount == 1);
    expect(cues.stopCount, 1);
    expect(cues.mediaWhileRecording, isEmpty);
    assistant.dispose();
  });

  test('native stop cue is not doubled by Flutter', () async {
    final cues = RecordingVoiceLocalFeedback();
    final recorder = FakeVoiceRecorder();
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return jsonResponse({'text': 'привет'});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse({
          'answer': 'ок',
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
    final assistant = buildAssistant(
      apiClient: apiClient,
      recorder: recorder,
      voiceFeedback: cues,
    );
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.hardwareButton,
      startCueAlreadyPlayed: true,
    );
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.hardwareButton,
      startCueAlreadyPlayed: true,
      stopCueAlreadyPlayed: true,
    );
    await waitUntil(() => recorder.stopCallCount == 1);
    expect(cues.ackCount, 0);
    expect(cues.readyCount, 1);
    expect(cues.stopCount, 0);
    assistant.dispose();
  });
}
