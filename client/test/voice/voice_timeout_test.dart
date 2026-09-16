import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/assistant/assistant_controller.dart';
import 'package:personal_secretary/assistant/fake_voice_recorder.dart';
import 'package:personal_secretary/assistant/voice_temp_files.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/capture/capture_controller.dart';
import 'package:personal_secretary/voice/voice_transcription_controller.dart';

void main() {
  const baseUrl = 'https://secretary.example';
  const token = 'voice-timeout-token';

  SecretaryApiClient buildApi(MockClient mock) {
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    return apiClient;
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

  test('assistant automatic stop transcribes and sends message', () async {
    int transcribeCalls = 0;
    int assistantCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        transcribeCalls += 1;
        return http.Response.bytes(
          utf8.encode(jsonEncode({'text': 'автоматическая диктовка'})),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
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
      if (request.url.path == '/assistant/speech') {
        return http.Response.bytes(
          [1, 2, 3],
          200,
          headers: {'content-type': 'audio/mpeg'},
        );
      }
      return http.Response('{}', 404);
    });
    final apiClient = buildApi(mock);
    final auth = buildAuth(apiClient);
    final voice = VoiceTranscriptionController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(
        directory: Directory.systemTemp.createTempSync(
          'voice_timeout_assistant',
        ),
      ),
      maxRecordingDuration: const Duration(milliseconds: 80),
      enableAutoStopInTests: true,
    );
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceController: voice,
    );

    await assistant.startVoiceRecording();
    expect(assistant.voiceState, AssistantVoiceState.recording);
    await Future<void>.delayed(const Duration(milliseconds: 150));
    final deadline = DateTime.now().add(const Duration(seconds: 3));
    while (assistant.voiceState == AssistantVoiceState.transcribing ||
        assistant.voiceState == AssistantVoiceState.thinking ||
        assistant.voiceState == AssistantVoiceState.speaking) {
      if (DateTime.now().isAfter(deadline)) {
        fail(
          'assistant voice did not return to idle, state=${assistant.voiceState}',
        );
      }
      await Future<void>.delayed(const Duration(milliseconds: 20));
    }

    expect(transcribeCalls, 1);
    expect(assistantCalls, 1);
    expect(assistant.voiceState, AssistantVoiceState.idle);
    expect(
      assistant.messages.any((m) => m.content == 'автоматическая диктовка'),
      isTrue,
    );
  });

  test('capture automatic stop appends transcript to draft text', () async {
    int transcribeCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        transcribeCalls += 1;
        return http.Response.bytes(
          utf8.encode(jsonEncode({'text': 'голосовая заметка'})),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }
      return http.Response('{}', 404);
    });
    final apiClient = buildApi(mock);
    final auth = buildAuth(apiClient);
    final voice = VoiceTranscriptionController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(
        directory: Directory.systemTemp.createTempSync('voice_timeout_capture'),
      ),
      maxRecordingDuration: const Duration(milliseconds: 80),
      enableAutoStopInTests: true,
    );
    final capture = CaptureController(
      apiClient: apiClient,
      authController: auth,
      voiceController: voice,
    );
    capture.setText('уже есть');

    await capture.startVoiceRecording();
    expect(capture.voiceState, VoiceState.recording);
    await Future<void>.delayed(const Duration(milliseconds: 150));
    while (capture.voiceState == VoiceState.transcribing) {
      await Future<void>.delayed(const Duration(milliseconds: 20));
    }

    expect(transcribeCalls, 1);
    expect(capture.draft.text, 'уже есть голосовая заметка');
    expect(capture.voiceState, VoiceState.idle);
  });
}
