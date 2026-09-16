import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_error.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/assistant/assistant_controller.dart';
import 'package:personal_secretary/assistant/fake_voice_recorder.dart';
import 'package:personal_secretary/assistant/voice_invocation_source.dart';
import 'package:personal_secretary/assistant/voice_temp_files.dart';
import 'package:personal_secretary/assistant/wav_inspect.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/voice/voice_transcription_controller.dart';

import 'pcm_wav_fixture.dart';

void main() {
  const baseUrl = 'https://secretary.example';
  const token = 'voice-short-wav-token';

  late Directory tempDir;

  setUp(() {
    tempDir = Directory.systemTemp.createTempSync('secretary_short_wav');
  });

  tearDown(() {
    if (tempDir.existsSync()) {
      tempDir.deleteSync(recursive: true);
    }
  });

  AuthController buildAuth(SecretaryApiClient apiClient) {
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    return auth;
  }

  test(
    'phone-sized 80 ms WAV fails locally on screen mic and hardware',
    () async {
      var transcribeCalls = 0;
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/transcribe') {
          transcribeCalls += 1;
          return http.Response('{}', 500);
        }
        return http.Response('{}', 404);
      });
      final apiClient = SecretaryApiClient(httpClient: mock);
      apiClient.configure(baseUrl: baseUrl, token: token);
      final shortWav = pcmWavBytes(durationMs: 80);
      expect(inspectWav(shortWav)!.durationMs, 80);

      Future<void> run(VoiceInvocationSource source) async {
        transcribeCalls = 0;
        final recorder = FakeVoiceRecorder(audioBytes: shortWav);
        final assistant = AssistantController(
          apiClient: apiClient,
          authController: buildAuth(apiClient),
          voiceRecorder: recorder,
          voiceTempFiles: VoiceTempFiles(directory: tempDir),
        );
        if (source == VoiceInvocationSource.screenMic) {
          await assistant.startVoiceRecording();
          await assistant.stopVoiceRecordingAndTranscribe();
        } else {
          await assistant.handleVoiceTrigger(source: source);
          await assistant.handleVoiceTrigger(source: source);
        }
        expect(transcribeCalls, 0);
        expect(assistant.voiceState, AssistantVoiceState.error);
        expect(
          assistant.voiceErrorMessage,
          transcriptionUnexpectedlyShortMessage(80),
        );
        assistant.dispose();
      }

      await run(VoiceInvocationSource.screenMic);
      await run(VoiceInvocationSource.hardwareButton);
    },
  );

  test(
    'WAV at duration floor still uses the shared transcribe pipeline',
    () async {
      var transcribeCalls = 0;
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/transcribe') {
          transcribeCalls += 1;
          return http.Response.bytes(
            utf8.encode(jsonEncode({'text': 'короткая фраза'})),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
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
      final recorder = FakeVoiceRecorder(
        audioBytes: pcmWavBytes(durationMs: minTranscribableWavDurationMs),
      );
      final assistant = AssistantController(
        apiClient: apiClient,
        authController: buildAuth(apiClient),
        voiceRecorder: recorder,
        voiceTempFiles: VoiceTempFiles(directory: tempDir),
      );
      await assistant.startVoiceRecording();
      await assistant.stopVoiceRecordingAndTranscribe();
      expect(transcribeCalls, 1);
      expect(assistant.messages.first.content, 'короткая фраза');
      assistant.dispose();
    },
  );

  test('typed 422 transcription_audio_invalid stays user-safe', () async {
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return http.Response.bytes(
          utf8.encode(
            jsonEncode({
              'detail': {
                'code': transcriptionAudioInvalidCode,
                'message': transcriptionAudioInvalidMessage,
              },
            }),
          ),
          422,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final voice = VoiceTranscriptionController(
      apiClient: apiClient,
      authController: buildAuth(apiClient),
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(directory: tempDir),
    );
    await voice.startRecording();
    await voice.stopAndTranscribe(onTranscript: (_) async {});
    expect(voice.voiceState, VoiceState.error);
    expect(voice.voiceErrorMessage, transcriptionAudioInvalidMessage);
    voice.dispose();
  });

  test('short WAV error copy includes duration', () {
    expect(
      transcriptionUnexpectedlyShortMessage(320),
      'Запись неожиданно получилась 0,32 с. Повторите попытку.',
    );
  });
}
