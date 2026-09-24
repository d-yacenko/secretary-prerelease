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
  const token = 'voice-failure-token';
  const roundLimitMessage =
      'Секретарю не хватило лимита шагов, чтобы завершить поиск. Попробуйте повторить или немного уточнить запрос.';

  late Directory tempDir;

  setUp(() {
    tempDir = Directory.systemTemp.createTempSync('secretary_voice_failure');
  });

  tearDown(() {
    if (tempDir.existsSync()) {
      tempDir.deleteSync(recursive: true);
    }
  });

  AssistantController build({
    required SecretaryApiClient apiClient,
    required RecordingVoiceLocalFeedback cues,
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
      speechPlayer: FakeSpeechPlayer(),
      voiceFeedback: cues,
    );
  }

  Future<void> voiceTurn(AssistantController assistant) async {
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.hardwareButton,
    );
    await assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.hardwareButton,
    );
  }

  test('voice round-limit stays visible and plays one failure cue', () async {
    var messageCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return http.Response(
          jsonEncode({'text': 'найди письма'}),
          200,
          headers: {'content-type': 'application/json'},
        );
      }
      if (request.url.path == '/assistant/message') {
        messageCalls += 1;
        if (messageCalls > 1) {
          return http.Response(
            jsonEncode({
              'answer': 'нашёл',
              'references': [],
              'affected_objects': [],
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        return http.Response(
          jsonEncode({
            'detail': {
              'code': 'assistant_round_limit',
              'message': roundLimitMessage,
            },
          }),
          422,
          headers: {'content-type': 'application/json'},
        );
      }
      return http.Response('{}', 404);
    });
    final api = SecretaryApiClient(httpClient: mock)
      ..configure(baseUrl: baseUrl, token: token);
    final cues = RecordingVoiceLocalFeedback();
    final assistant = build(apiClient: api, cues: cues);
    await voiceTurn(assistant);
    expect(assistant.voiceState, AssistantVoiceState.error);
    expect(assistant.sendState, AssistantSendState.error);
    expect(assistant.voiceErrorMessage, roundLimitMessage);
    expect(assistant.errorMessage, roundLimitMessage);
    expect(cues.errorCount, 1);
    expect(assistant.messages, isEmpty);
    expect(assistant.pendingRetryMessage, 'найди письма');

    await assistant.sendMessage(assistant.pendingRetryMessage!);
    expect(messageCalls, 2);
    expect(cues.errorCount, 1);
    expect(
      assistant.messages
          .where((message) => message.role == 'user')
          .map((message) => message.content)
          .toList(),
      ['найди письма'],
    );
    assistant.dispose();
  });

  test(
    'voice network and auth failures stay visible with one cue each',
    () async {
      var mode = 'network';
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/transcribe') {
          return http.Response(
            jsonEncode({'text': 'вопрос'}),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        if (request.url.path == '/assistant/message') {
          if (mode == 'network') {
            throw http.ClientException('offline');
          }
          return http.Response(
            jsonEncode({
              'detail': {'message': 'Authentication failed'},
            }),
            401,
            headers: {'content-type': 'application/json'},
          );
        }
        return http.Response('{}', 404);
      });
      final api = SecretaryApiClient(httpClient: mock)
        ..configure(baseUrl: baseUrl, token: token);
      final cues = RecordingVoiceLocalFeedback();
      final assistant = build(apiClient: api, cues: cues);
      await voiceTurn(assistant);
      expect(assistant.voiceState, AssistantVoiceState.error);
      expect(assistant.voiceErrorMessage, isNotEmpty);
      expect(cues.errorCount, 1);
      expect(assistant.messages, isEmpty);

      mode = 'auth';
      await assistant.handleVoiceTrigger(
        source: VoiceInvocationSource.hardwareButton,
      );
      expect(assistant.voiceErrorMessage, isNull);
      await assistant.handleVoiceTrigger(
        source: VoiceInvocationSource.hardwareButton,
      );
      expect(assistant.voiceState, AssistantVoiceState.error);
      expect(assistant.voiceErrorMessage, 'Authentication failed');
      expect(cues.errorCount, 2);
      expect(assistant.messages, isEmpty);
      assistant.dispose();
    },
  );

  test(
    'typed failure keeps screen error and does not play a voice cue',
    () async {
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/message') {
          return http.Response(
            jsonEncode({
              'detail': {
                'code': 'assistant_round_limit',
                'message': roundLimitMessage,
              },
            }),
            422,
            headers: {'content-type': 'application/json'},
          );
        }
        return http.Response('{}', 404);
      });
      final api = SecretaryApiClient(httpClient: mock)
        ..configure(baseUrl: baseUrl, token: token);
      final cues = RecordingVoiceLocalFeedback();
      final assistant = build(apiClient: api, cues: cues);
      await assistant.sendMessage('текстом');
      expect(assistant.sendState, AssistantSendState.error);
      expect(assistant.errorMessage, roundLimitMessage);
      expect(assistant.voiceState, AssistantVoiceState.idle);
      expect(cues.errorCount, 0);
      expect(assistant.messages, isEmpty);
      assistant.dispose();
    },
  );

  test(
    'successful voice turn speaks and does not play the failure cue',
    () async {
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/transcribe') {
          return http.Response(
            jsonEncode({'text': 'привет'}),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        if (request.url.path == '/assistant/message') {
          return http.Response(
            jsonEncode({
              'answer': 'ок',
              'references': [],
              'affected_objects': [],
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        if (request.url.path == '/assistant/speech') {
          return http.Response.bytes(
            [1, 2, 3, 4],
            200,
            headers: {'content-type': 'audio/mpeg'},
          );
        }
        return http.Response('{}', 404);
      });
      final api = SecretaryApiClient(httpClient: mock)
        ..configure(baseUrl: baseUrl, token: token);
      final cues = RecordingVoiceLocalFeedback();
      final assistant = build(apiClient: api, cues: cues);
      await voiceTurn(assistant);
      expect(cues.errorCount, 0);
      expect(assistant.messages, hasLength(2));
      expect(assistant.voiceState, isNot(AssistantVoiceState.error));
      assistant.dispose();
    },
  );

  test('screen-mic output-limit stays visible and plays one failure cue', () async {
    const outputLimitMessage =
        'Секретарю не хватило лимита ответа, чтобы закончить формулировку. Попробуйте повторить или сузить запрос.';
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return http.Response(
          jsonEncode({'text': 'найди письма'}),
          200,
          headers: {'content-type': 'application/json'},
        );
      }
      if (request.url.path == '/assistant/message') {
        return http.Response(
          jsonEncode({
            'detail': {
              'code': 'assistant_output_limit',
              'message': outputLimitMessage,
            },
          }),
          422,
          headers: {'content-type': 'application/json'},
        );
      }
      return http.Response('{}', 404);
    });
    final api = SecretaryApiClient(httpClient: mock)
      ..configure(baseUrl: baseUrl, token: token);
    final cues = RecordingVoiceLocalFeedback();
    final assistant = build(apiClient: api, cues: cues);
    await assistant.handleVoiceTrigger(source: VoiceInvocationSource.screenMic);
    await assistant.handleVoiceTrigger(source: VoiceInvocationSource.screenMic);
    expect(assistant.voiceState, AssistantVoiceState.error);
    expect(assistant.sendState, AssistantSendState.error);
    expect(assistant.voiceErrorMessage, outputLimitMessage);
    expect(cues.errorCount, 1);
    expect(assistant.messages, isEmpty);
    assistant.dispose();
  });
}
