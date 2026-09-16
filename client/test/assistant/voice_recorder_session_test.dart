import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/assistant/assistant_controller.dart';
import 'package:personal_secretary/assistant/fake_speech_player.dart';
import 'package:personal_secretary/assistant/fake_voice_recorder.dart';
import 'package:personal_secretary/assistant/recording_file_finalize.dart';
import 'package:personal_secretary/assistant/voice_capture_diagnostics.dart';
import 'package:personal_secretary/assistant/voice_invocation_source.dart';
import 'package:personal_secretary/assistant/voice_local_feedback.dart';
import 'package:personal_secretary/assistant/voice_output_policy.dart';
import 'package:personal_secretary/assistant/voice_output_policy_controller.dart';
import 'package:personal_secretary/assistant/voice_output_policy_store.dart';
import 'package:personal_secretary/assistant/voice_temp_files.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/voice/voice_transcription_controller.dart';

import 'pcm_wav_fixture.dart';

void main() {
  const baseUrl = 'https://secretary.example';
  const token = 'voice-session-token';

  late Directory tempDir;

  setUp(() {
    tempDir = Directory.systemTemp.createTempSync('secretary_voice_session');
    VoiceCaptureDiagnostics.resetForTest();
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

  AuthController buildAuth(SecretaryApiClient apiClient) {
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    return auth;
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

  AssistantController buildAssistant({
    required SecretaryApiClient apiClient,
    FakeVoiceRecorder? recorder,
    FakeSpeechPlayer? speechPlayer,
    VoiceLocalFeedback? voiceFeedback,
    VoiceOutputPolicy policy = VoiceOutputPolicy.handsFreeEnabled,
    VoiceTranscriptionController? voiceController,
  }) {
    final auth = buildAuth(apiClient);
    return AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: recorder ?? FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(directory: tempDir),
      voiceController: voiceController,
      speechPlayer: speechPlayer ?? FakeSpeechPlayer(),
      voiceFeedback: voiceFeedback,
      voiceOutputPolicy: VoiceOutputPolicyController(
        authController: auth,
        store: VoiceOutputPolicyStore.memory(),
        initialPolicy: policy,
      ),
    );
  }

  test('three consecutive turns reuse the recorder', () async {
    final answers = ['список писем', 'уточните папку', 'готово'];
    var turn = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return jsonResponse({'text': 'фраза ${turn + 1}'});
      }
      if (request.url.path == '/assistant/message') {
        final answer = answers[turn.clamp(0, answers.length - 1)];
        turn += 1;
        return jsonResponse({
          'answer': answer,
          'references': [],
          'affected_objects': [],
        });
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final recorder = FakeVoiceRecorder();
    final assistant = buildAssistant(apiClient: apiClient, recorder: recorder);
    for (var i = 0; i < 3; i++) {
      await assistant.handleVoiceTrigger();
      await assistant.handleVoiceTrigger();
      await waitUntil(() => assistant.voiceState == AssistantVoiceState.idle);
    }
    expect(recorder.startCallCount, 3);
    expect(recorder.stopCallCount, 3);
    expect(assistant.messages.where((m) => m.role == 'assistant').length, 3);
    assistant.dispose();
  });

  test('TTS between turns is released before the next recording', () async {
    var speechCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return jsonResponse({'text': 'привет'});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse({
          'answer': 'ответ',
          'references': [],
          'affected_objects': [],
        });
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
    final speech = FakeSpeechPlayer();
    final assistant = buildAssistant(
      apiClient: apiClient,
      recorder: recorder,
      speechPlayer: speech,
    );
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.hardwareButton,
    );
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.hardwareButton,
    );
    await waitUntil(() => assistant.voiceState == AssistantVoiceState.idle);
    expect(speechCalls, 1);
    final stopsAfterTts = speech.stopCount;
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.hardwareButton,
    );
    expect(speech.stopCount, greaterThan(stopsAfterTts));
    expect(assistant.voiceState, AssistantVoiceState.recording);
    assistant.dispose();
  });

  test('interrupted TTS starts a fresh recording', () async {
    final speech = FakeSpeechPlayer(completeImmediately: false);
    var releaseMessage = false;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return jsonResponse({'text': 'привет'});
      }
      if (request.url.path == '/assistant/message') {
        while (!releaseMessage) {
          await Future<void>.delayed(const Duration(milliseconds: 10));
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
    final recorder = FakeVoiceRecorder();
    final assistant = buildAssistant(
      apiClient: apiClient,
      recorder: recorder,
      speechPlayer: speech,
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
    expect(speech.stopCount, greaterThan(0));
    expect(assistant.voiceState, AssistantVoiceState.recording);
    speech.completeHeldPlay();
    await turn;
    assistant.dispose();
  });

  test(
    'screen mic does not play an audible ready cue or TTS by default',
    () async {
      var speechCalls = 0;
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/transcribe') {
          return jsonResponse({'text': 'привет'});
        }
        if (request.url.path == '/assistant/message') {
          return jsonResponse({
            'answer': 'текстом',
            'references': [],
            'affected_objects': [],
          });
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
      final cues = RecordingVoiceLocalFeedback(
        isRecorderActive: () => recorder.isRecording,
      );
      final assistant = buildAssistant(
        apiClient: apiClient,
        recorder: recorder,
        voiceFeedback: cues,
      );
      await assistant.handleVoiceTrigger();
      expect(cues.readyCount, 0);
      await assistant.handleVoiceTrigger();
      await waitUntil(() => assistant.voiceState == AssistantVoiceState.idle);
      expect(speechCalls, 0);
      expect(cues.mediaWhileRecording, isEmpty);
      assistant.dispose();
    },
  );

  test('AudioPlayer cues never start while the recorder is active', () async {
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
    expect(cues.readyCount, 1);
    expect(cues.stopCount, 1);
    expect(cues.mediaWhileRecording, isEmpty);
    assistant.dispose();
  });

  test(
    'second trigger during starting is ignored, not a premature stop',
    () async {
      final recorder = FakeVoiceRecorder()
        ..startDelay = const Duration(milliseconds: 80);
      final apiClient = SecretaryApiClient(
        httpClient: MockClient((_) async => http.Response('{}', 404)),
      );
      apiClient.configure(baseUrl: baseUrl, token: token);
      final assistant = buildAssistant(
        apiClient: apiClient,
        recorder: recorder,
      );
      final start = assistant.handleVoiceTrigger();
      await waitUntil(
        () => assistant.voiceState == AssistantVoiceState.starting,
      );
      await assistant.handleVoiceTrigger();
      await start;
      expect(assistant.voiceState, AssistantVoiceState.recording);
      expect(recorder.startCallCount, 1);
      expect(recorder.stopCallCount, 0);
      final triggerStates = VoiceCaptureDiagnostics.events
          .where((event) => event['event'] == 'handleVoiceTrigger')
          .map((event) => event['state'])
          .toList();
      expect(triggerStates, contains('starting'));
      assistant.dispose();
    },
  );

  test('file that grows after stop is read after it stabilizes', () async {
    var uploadedBytes = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        uploadedBytes = request.bodyBytes.length;
        return jsonResponse({'text': 'длинная фраза'});
      }
      if (request.url.path == '/assistant/message') {
        return jsonResponse({
          'answer': 'ок',
          'references': [],
          'affected_objects': [],
        });
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = buildAuth(apiClient);
    final shortWav = pcmWavBytes(durationMs: 80);
    final longWav = pcmWavBytes(durationMs: 3000);
    final recorder = FakeVoiceRecorder(audioBytes: shortWav)
      ..bytesAfterStop = longWav
      ..growAfterStopDelay = const Duration(milliseconds: 20);
    final voice = VoiceTranscriptionController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: recorder,
      voiceTempFiles: VoiceTempFiles(directory: tempDir),
      enableFileFinalizeWait: true,
    );
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceController: voice,
      voiceTempFiles: VoiceTempFiles(directory: tempDir),
      speechPlayer: FakeSpeechPlayer(),
    );
    await assistant.startVoiceRecording();
    await assistant.stopVoiceRecordingAndTranscribe();
    await waitUntil(() => assistant.messages.isNotEmpty);
    expect(uploadedBytes, greaterThan(shortWav.length));
    expect(uploadedBytes, greaterThanOrEqualTo(longWav.length));
    assistant.dispose();
  });

  test('bounded finalize helper returns once the file stops growing', () async {
    final file = File('${tempDir.path}/grow.wav');
    await file.writeAsBytes(pcmWavBytes(durationMs: 80), flush: true);
    unawaited(
      Future<void>.delayed(const Duration(milliseconds: 20), () {
        file.writeAsBytesSync(pcmWavBytes(durationMs: 500));
      }),
    );
    final samples = await waitUntilRecordingFileFinalized(file);
    expect(samples.length, greaterThanOrEqualTo(2));
    expect(samples.last.bytes, pcmWavBytes(durationMs: 500).length);
    expect(samples.first.bytes, lessThan(samples.last.bytes));
  });
}
