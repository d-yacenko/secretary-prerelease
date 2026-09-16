import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/assistant/fake_voice_recorder.dart';
import 'package:personal_secretary/assistant/voice_temp_files.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/capture/capture_controller.dart';
import 'package:personal_secretary/capture/capture_draft.dart';
import 'package:personal_secretary/objects/object_detail_screen.dart';
import 'package:personal_secretary/voice/voice_transcription_controller.dart';

void main() {
  const baseUrl = 'https://secretary.example';
  const token = 'capture-token';

  CaptureController buildController(MockClient mock) {
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    return CaptureController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(
        directory: Directory.systemTemp.createTempSync('capture_voice_test'),
      ),
    );
  }

  test('blank text cannot submit', () async {
    final controller = buildController(MockClient((request) async {
      return http.Response('{}', 201);
    }));
    controller.setText('   ');
    await controller.submit();
    expect(controller.submitState, CaptureSubmitState.validationError);
  });

  test('exact whitespace and text preserved in request', () async {
    Map<String, dynamic>? body;
    final controller = buildController(MockClient((request) async {
      body = jsonDecode(request.body) as Map<String, dynamic>;
      return http.Response(
        jsonEncode({
          'task_id': 't1',
          'context_edge_ids': [],
          'dependency_edge_ids': [],
        }),
        201,
      );
    }));
    controller.setText('  leading space');
    await controller.submit();
    expect(body!['text'], '  leading space');
  });

  test('title is optional', () async {
    Map<String, dynamic>? body;
    final controller = buildController(MockClient((request) async {
      body = jsonDecode(request.body) as Map<String, dynamic>;
      return http.Response(
        jsonEncode({
          'task_id': 't1',
          'context_edge_ids': [],
          'dependency_edge_ids': [],
        }),
        201,
      );
    }));
    controller.setText('task body');
    await controller.submit();
    expect(body!.containsKey('title'), isFalse);
  });

  test('max length validation blocks submit', () async {
    final controller = buildController(MockClient((request) async {
      return http.Response('{}', 201);
    }));
    controller.setText('x' * (CaptureDraft.maxTextLength + 1));
    expect(controller.draft.canSubmit, isFalse);

    controller.setText('ok');
    controller.setTitle('t' * (CaptureDraft.maxTitleLength + 1));
    expect(controller.draft.canSubmit, isFalse);
  });

  test('submit disabled while request pending', () async {
    final controller = buildController(MockClient((request) async {
      await Future<void>.delayed(const Duration(milliseconds: 100));
      return http.Response(
        jsonEncode({
          'task_id': 't1',
          'context_edge_ids': [],
          'dependency_edge_ids': [],
        }),
        201,
      );
    }));
    controller.setText('task');
    final first = controller.submit();
    expect(controller.submitState, CaptureSubmitState.submitting);
    await first;
  });

  test('success clears draft', () async {
    final controller = buildController(MockClient((request) async {
      return http.Response(
        jsonEncode({
          'task_id': 'task-42',
          'context_edge_ids': [],
          'dependency_edge_ids': [],
        }),
        201,
      );
    }));
    controller.setText('done task');
    await controller.submit();
    expect(controller.submitState, CaptureSubmitState.success);
    expect(controller.draft.text, isEmpty);
    expect(controller.lastResult?.taskId, 'task-42');
  });

  test('failure preserves draft', () async {
    final controller = buildController(MockClient((request) async {
      return http.Response(jsonEncode({'detail': 'validation failed'}), 422);
    }));
    controller.setText('keep me');
    await controller.submit();
    expect(controller.draft.text, 'keep me');
    expect(controller.submitState, CaptureSubmitState.validationError);
  });

  test('capture library has no OpenAI/LLM client references', () {
    final captureDir = Directory('lib/capture');
    final blocked = RegExp(r'openai|chatgpt|gpt-', caseSensitive: false);
    for (final entity in captureDir.listSync()) {
      if (entity is! File || !entity.path.endsWith('.dart')) continue;
      final content = entity.readAsStringSync();
      expect(blocked.hasMatch(content), isFalse, reason: entity.path);
    }
  });

  test('capture draft preserves exact text in API request', () {
    final draft = CaptureDraft(text: '  spaced  ');
    final json = draft.toRequest().toJson();
    expect(jsonEncode(json['text']), jsonEncode('  spaced  '));
  });

  group('capture session boundary', () {
    CaptureController buildCaptureController(AuthController auth) {
      return CaptureController(
        apiClient: auth.apiClient,
        authController: auth,
      );
    }

    test('clears draft after forget token and re-authentication as another user', () async {
      var currentUserId = 'user-a';
      final mock = MockClient((request) async {
        if (request.url.path.endsWith('/me')) {
          return http.Response(
            jsonEncode({
              'id': currentUserId,
              'display_name': currentUserId,
              'created_at': '2026-01-01T00:00:00Z',
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      });

      final tokenStore = FakeTokenStore();
      final serverUrlStore = FakeServerUrlStore();
      final auth = AuthController(
        apiClient: SecretaryApiClient(httpClient: mock),
        tokenStore: tokenStore,
        serverUrlStore: serverUrlStore,
      );
      final capture = buildCaptureController(auth);
      auth.onSessionTerminated = capture.resetSession;

      auth.apiClient.configure(baseUrl: baseUrl, token: 'token-a');
      await auth.initialize();
      capture.mergeDraft(
        CaptureDraft(
          text: 'user A secret',
          title: 'A title',
          contextObjectIds: ['ctx-a'],
          contextRefs: [
            CaptureContextRef(id: 'ctx-a', title: 'Context A', kind: 'email'),
          ],
          dependsOnIds: ['dep-a'],
        ),
      );

      await auth.forgetToken();
      currentUserId = 'user-b';
      final connected = await auth.connect(
        serverUrlInput: baseUrl,
        token: 'token-b',
      );
      expect(connected, isTrue);

      expect(capture.draft.text, isEmpty);
      expect(capture.draft.title, isNull);
      expect(capture.draft.contextObjectIds, isEmpty);
      expect(capture.draft.contextRefs, isEmpty);
      expect(capture.draft.dependsOnIds, isEmpty);
      expect(capture.lastResult, isNull);
    });

    test('same-user network failure preserves draft', () async {
      final mock = MockClient((request) async {
        if (request.url.path.endsWith('/capture/task')) {
          throw http.ClientException('connection refused');
        }
        return http.Response('{}', 404);
      });

      final auth = AuthController(
        apiClient: SecretaryApiClient(httpClient: mock),
        tokenStore: FakeTokenStore(),
        serverUrlStore: FakeServerUrlStore(),
      );
      final capture = buildCaptureController(auth);
      auth.apiClient.configure(baseUrl: baseUrl, token: token);

      capture.mergeDraft(
        CaptureDraft(
          text: 'keep on network error',
          contextObjectIds: ['ctx-1'],
          dependsOnIds: ['dep-1'],
        ),
      );

      await capture.submit();
      expect(capture.draft.text, 'keep on network error');
      expect(capture.draft.contextObjectIds, ['ctx-1']);
      expect(capture.draft.dependsOnIds, ['dep-1']);
      expect(capture.submitState, CaptureSubmitState.networkError);
    });

    testWidgets('manual context from object detail preserves text and sends context ids',
        (tester) async {
      Map<String, dynamic>? captureBody;
      final mock = MockClient((request) async {
        if (request.url.path == '/objects/email-1') {
          return http.Response(
            jsonEncode({
              'id': 'email-1',
              'kind': 'email',
              'title': 'Course plan',
              'body': 'Full email body should not be copied',
              'provider': 'gmail',
              'external_id': null,
              'canonical_uri': null,
              'status': null,
              'start_at': null,
              'due_at': null,
              'metadata': {},
              'origin': 'source',
              'state': 'observed',
              'confidence': null,
              'created_at': '2026-08-28T08:00:00Z',
              'updated_at': '2026-08-28T08:00:00Z',
            }),
            200,
          );
        }
        if (request.url.path == '/objects/email-1/neighbors') {
          return http.Response(
            jsonEncode({'object_id': 'email-1', 'neighbors': []}),
            200,
          );
        }
        if (request.url.path == '/objects/email-1/context') {
          return http.Response(
            jsonEncode({
              'object': {
                'id': 'email-1',
                'kind': 'email',
                'title': 'Course plan',
                'body': 'Full email body should not be copied',
                'provider': 'gmail',
                'external_id': null,
                'canonical_uri': null,
                'status': null,
                'start_at': null,
                'due_at': null,
                'metadata': {},
                'origin': 'source',
                'state': 'observed',
                'confidence': null,
                'created_at': '2026-08-28T08:00:00Z',
                'updated_at': '2026-08-28T08:00:00Z',
              },
              'edges': [],
              'neighbors': [],
            }),
            200,
          );
        }
        if (request.url.path.endsWith('/capture/task')) {
          captureBody = jsonDecode(request.body) as Map<String, dynamic>;
          return http.Response(
            jsonEncode({
              'task_id': 'task-new',
              'context_edge_ids': ['edge-1'],
              'dependency_edge_ids': [],
            }),
            201,
          );
        }
        return http.Response('{}', 404);
      });

      final auth = AuthController(
        apiClient: SecretaryApiClient(httpClient: mock),
        tokenStore: FakeTokenStore(),
        serverUrlStore: FakeServerUrlStore(),
      );
      auth.apiClient.configure(baseUrl: baseUrl, token: token);
      final capture = buildCaptureController(auth);
      capture.mergeDraft(CaptureDraft(text: '  keep exact  '));

      await tester.pumpWidget(
        MaterialApp(
          home: ObjectDetailScreen(
            objectId: 'email-1',
            apiClient: auth.apiClient,
            authController: auth,
            captureController: capture,
          ),
        ),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.text('Использовать как контекст задачи'));
      await tester.pumpAndSettle();

      expect(find.text('Контекст: Course plan'), findsOneWidget);
      expect(capture.draft.contextObjectIds, ['email-1']);
      expect(capture.draft.contextRefs.length, 1);
      expect(capture.draft.text, '  keep exact  ');

      capture.attachObjectContext(
        SecretaryObject.fromJson({
          'id': 'email-1',
          'kind': 'email',
          'title': 'Course plan',
          'body': null,
          'provider': null,
          'external_id': null,
          'canonical_uri': null,
          'status': null,
          'start_at': null,
          'due_at': null,
          'metadata': {},
          'origin': 'source',
          'state': 'observed',
          'confidence': null,
          'created_at': '2026-08-28T08:00:00Z',
          'updated_at': '2026-08-28T08:00:00Z',
        }),
      );
      expect(capture.draft.contextObjectIds, ['email-1']);

      await capture.submit();
      expect(captureBody!['context_object_ids'], ['email-1']);
      expect(captureBody!['text'], '  keep exact  ');
      expect(captureBody!.containsKey('body'), isFalse);
      expect(captureBody!.containsKey('context_body'), isFalse);
    });
  });

  test('capture voice sets empty task text from transcript', () async {
    int transcribeCalls = 0;
    int captureCalls = 0;
    final controller = buildController(MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        transcribeCalls += 1;
        return http.Response.bytes(
          utf8.encode(jsonEncode({'text': 'Новая задача голосом'})),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }
      if (request.url.path.endsWith('/capture/task')) {
        captureCalls += 1;
        return http.Response('{}', 201);
      }
      return http.Response('{}', 404);
    }));

    await controller.startVoiceRecording();
    expect(controller.voiceState, VoiceState.recording);
    await controller.stopVoiceRecordingAndTranscribe();
    while (controller.voiceState == VoiceState.transcribing) {
      await Future<void>.delayed(const Duration(milliseconds: 20));
    }

    expect(transcribeCalls, 1);
    expect(controller.draft.text, 'Новая задача голосом');
    expect(captureCalls, 0);
  });

  test('capture voice appends transcript to existing text', () async {
    final controller = buildController(MockClient((request) async {
      if (request.url.path == '/assistant/transcribe') {
        return http.Response.bytes(
          utf8.encode(jsonEncode({'text': 'дополнение'})),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }
      return http.Response('{}', 404);
    }));

    controller.setText('Уже есть текст');
    await controller.startVoiceRecording();
    await controller.stopVoiceRecordingAndTranscribe();
    while (controller.voiceState == VoiceState.transcribing) {
      await Future<void>.delayed(const Duration(milliseconds: 20));
    }

    expect(controller.draft.text, 'Уже есть текст дополнение');
  });

  test('exact url in task capture posts capture task not intake link', () async {
    String? path;
    Map<String, dynamic>? body;
    final controller = buildController(MockClient((request) async {
      path = request.url.path;
      body = jsonDecode(request.body) as Map<String, dynamic>;
      return http.Response(
        jsonEncode({
          'task_id': 'task-url',
          'context_edge_ids': [],
          'dependency_edge_ids': [],
        }),
        201,
      );
    }));
    controller.setText('https://example.org/article');
    await controller.submit();
    expect(path, '/capture/task');
    expect(body!['text'], 'https://example.org/article');
  });

  test('task context with exact url submits capture task', () async {
    String? path;
    Map<String, dynamic>? body;
    final controller = buildController(MockClient((request) async {
      path = request.url.path;
      body = jsonDecode(request.body) as Map<String, dynamic>;
      return http.Response(
        jsonEncode({
          'task_id': 'task-url',
          'context_edge_ids': ['edge-1'],
          'dependency_edge_ids': [],
        }),
        201,
      );
    }));
    controller.attachContext(
      CaptureContextRef(id: 'ctx-1', title: 'Related', kind: 'email'),
    );
    controller.setText('https://example.org/article');
    await controller.submit();
    expect(path, '/capture/task');
    expect(body!['text'], 'https://example.org/article');
    expect(body!['context_object_ids'], ['ctx-1']);
  });

  test('unfinished task draft preserved after failed submit', () async {
    final controller = buildController(MockClient((request) async {
      return http.Response(jsonEncode({'detail': 'validation failed'}), 422);
    }));
    controller.setText('keep unfinished task');
    await controller.submit();
    expect(controller.draft.text, 'keep unfinished task');
    expect(controller.submitState, CaptureSubmitState.validationError);
  });
}
