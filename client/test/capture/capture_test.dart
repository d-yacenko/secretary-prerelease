import 'dart:async';
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
import 'package:personal_secretary/capture/capture_screen.dart';
import 'package:personal_secretary/navigation/secretary_navigation.dart';
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
    final controller = buildController(
      MockClient((request) async {
        return http.Response('{}', 201);
      }),
    );
    controller.setText('   ');
    await controller.submit();
    expect(controller.submitState, CaptureSubmitState.validationError);
  });

  test('exact whitespace and text preserved in request', () async {
    Map<String, dynamic>? body;
    final controller = buildController(
      MockClient((request) async {
        body = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(
          jsonEncode({
            'task_id': 't1',
            'context_edge_ids': [],
            'dependency_edge_ids': [],
          }),
          201,
        );
      }),
    );
    controller.setText('  leading space');
    await controller.submit();
    expect(body!['text'], '  leading space');
  });

  test('title is optional', () async {
    Map<String, dynamic>? body;
    final controller = buildController(
      MockClient((request) async {
        body = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(
          jsonEncode({
            'task_id': 't1',
            'context_edge_ids': [],
            'dependency_edge_ids': [],
          }),
          201,
        );
      }),
    );
    controller.setText('task body');
    await controller.submit();
    expect(body!.containsKey('title'), isFalse);
  });

  test('max length validation blocks submit', () async {
    final controller = buildController(
      MockClient((request) async {
        return http.Response('{}', 201);
      }),
    );
    controller.setText('x' * (CaptureDraft.maxTextLength + 1));
    expect(controller.draft.canSubmit, isFalse);

    controller.setText('ok');
    controller.setTitle('t' * (CaptureDraft.maxTitleLength + 1));
    expect(controller.draft.canSubmit, isFalse);
  });

  test('submit disabled while request pending', () async {
    final controller = buildController(
      MockClient((request) async {
        await Future<void>.delayed(const Duration(milliseconds: 100));
        return http.Response(
          jsonEncode({
            'task_id': 't1',
            'context_edge_ids': [],
            'dependency_edge_ids': [],
          }),
          201,
        );
      }),
    );
    controller.setText('task');
    final first = controller.submit();
    expect(controller.submitState, CaptureSubmitState.submitting);
    await first;
  });

  test('success clears draft', () async {
    final controller = buildController(
      MockClient((request) async {
        return http.Response(
          jsonEncode({
            'task_id': 'task-42',
            'context_edge_ids': [],
            'dependency_edge_ids': [],
          }),
          201,
        );
      }),
    );
    controller.setText('done task');
    await controller.submit();
    expect(controller.submitState, CaptureSubmitState.success);
    expect(controller.draft.text, isEmpty);
    expect(controller.lastResult?.taskId, 'task-42');
  });

  test('failure preserves draft', () async {
    final controller = buildController(
      MockClient((request) async {
        return http.Response(jsonEncode({'detail': 'validation failed'}), 422);
      }),
    );
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
      return CaptureController(apiClient: auth.apiClient, authController: auth);
    }

    test(
      'clears draft after forget token and re-authentication as another user',
      () async {
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
      },
    );

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

    testWidgets(
      'object detail contextual capture starts fresh and sends that context',
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
        expect(capture.draft.text, isEmpty);
        expect(capture.draft.title, isNull);
        expect(capture.draft.dependsOnIds, isEmpty);
        capture.setText('  keep exact  ');

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
      },
    );
  });

  test('capture voice sets empty task text from transcript', () async {
    int transcribeCalls = 0;
    int captureCalls = 0;
    final controller = buildController(
      MockClient((request) async {
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
      }),
    );

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
    final controller = buildController(
      MockClient((request) async {
        if (request.url.path == '/assistant/transcribe') {
          return http.Response.bytes(
            utf8.encode(jsonEncode({'text': 'дополнение'})),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        return http.Response('{}', 404);
      }),
    );

    controller.setText('Уже есть текст');
    await controller.startVoiceRecording();
    await controller.stopVoiceRecordingAndTranscribe();
    while (controller.voiceState == VoiceState.transcribing) {
      await Future<void>.delayed(const Duration(milliseconds: 20));
    }

    expect(controller.draft.text, 'Уже есть текст дополнение');
  });

  test(
    'exact url in task capture posts capture task not intake link',
    () async {
      String? path;
      Map<String, dynamic>? body;
      final controller = buildController(
        MockClient((request) async {
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
        }),
      );
      controller.setText('https://example.org/article');
      await controller.submit();
      expect(path, '/capture/task');
      expect(body!['text'], 'https://example.org/article');
    },
  );

  test('task context with exact url submits capture task', () async {
    String? path;
    Map<String, dynamic>? body;
    final controller = buildController(
      MockClient((request) async {
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
      }),
    );
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
    final controller = buildController(
      MockClient((request) async {
        return http.Response(jsonEncode({'detail': 'validation failed'}), 422);
      }),
    );
    controller.setText('keep unfinished task');
    await controller.submit();
    expect(controller.draft.text, 'keep unfinished task');
    expect(controller.submitState, CaptureSubmitState.validationError);
  });

  Map<String, dynamic> createdBody() {
    return {
      'task_id': 't1',
      'context_edge_ids': <String>[],
      'dependency_edge_ids': <String>[],
    };
  }

  test('capture draft defaults to finite and sends it', () async {
    Map<String, dynamic>? body;
    final controller = buildController(
      MockClient((request) async {
        body = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(jsonEncode(createdBody()), 201);
      }),
    );
    expect(CaptureDraft.empty.completionMode, 'finite');
    expect(controller.draft.completionMode, 'finite');
    expect(controller.draft.toRequest().toJson()['completion_mode'], 'finite');
    controller.setText('task body');
    await controller.submit();
    expect(body!['completion_mode'], 'finite');
    expect(controller.draft.completionMode, 'finite');
  });

  test(
    'mode changes, attachments, voice, failure, and reset keep the contract',
    () async {
      Map<String, dynamic>? body;
      late CaptureController controller;
      controller = buildController(
        MockClient((request) async {
          body = jsonDecode(request.body) as Map<String, dynamic>;
          final text = body!['text'] as String;
          if (text.contains('fail')) {
            return http.Response(jsonEncode({'detail': 'no'}), 422);
          }
          return http.Response(jsonEncode(createdBody()), 201);
        }),
      );
      controller.setCompletionMode('ongoing');
      controller.setText('keep text');
      controller.setTitle('keep title');
      final due = DateTime.utc(2026, 10, 2, 9, 30);
      final start = DateTime.utc(2026, 10, 2, 10);
      final end = DateTime.utc(2026, 10, 2, 11);
      controller.setDueAt(due);
      controller.setPlannedInterval(start, end);
      expect(controller.draft.text, 'keep text');
      expect(controller.draft.completionMode, 'ongoing');
      controller.attachContext(
        CaptureContextRef(id: 'ctx-1', title: 'Mail', kind: 'email'),
      );
      controller.attachObjectContext(
        SecretaryObject(
          id: 'dep-1',
          kind: 'task',
          title: 'Prerequisite',
          metadata: const {},
          origin: 'user',
          state: 'confirmed',
          createdAt: '2026-01-01T00:00:00Z',
          updatedAt: '2026-01-01T00:00:00Z',
        ),
      );
      expect(controller.draft.completionMode, 'ongoing');
      expect(controller.draft.contextObjectIds, ['ctx-1', 'dep-1']);
      controller.mergeDraft(
        CaptureDraft(
          text: 'fail this submit',
          title: 'keep title',
          dependsOnIds: const ['dep-1'],
        ),
      );
      expect(controller.draft.completionMode, 'ongoing');
      expect(controller.draft.dependsOnIds, ['dep-1']);
      await controller.submit();
      expect(controller.submitState, CaptureSubmitState.validationError);
      expect(controller.draft.completionMode, 'ongoing');
      expect(controller.draft.dueAt, due);
      expect(controller.draft.plannedStartAt, start);
      expect(controller.draft.plannedEndAt, end);
      controller.appendTranscriptToText('ещё');
      expect(controller.draft.completionMode, 'ongoing');
      expect(controller.draft.text, contains('ещё'));
      controller.setText('ready now');
      controller.setCompletionMode('finite');
      await controller.submit();
      expect(body!['completion_mode'], 'finite');
      expect(body!['due_at'], due.toUtc().toIso8601String());
      expect(body!['planned_start_at'], start.toUtc().toIso8601String());
      expect(body!['planned_end_at'], end.toUtc().toIso8601String());
      expect(controller.draft.completionMode, 'finite');
      expect(controller.draft.dueAt, isNull);
      expect(controller.draft.plannedStartAt, isNull);
      expect(controller.draft.plannedEndAt, isNull);
      controller.setCompletionMode('ongoing');
      controller.setDueAt(due);
      controller.resetSession();
      expect(controller.draft.completionMode, 'finite');
      expect(controller.draft.dueAt, isNull);
      expect(controller.draft.text, isEmpty);
    },
  );

  testWidgets('capture selector sends ongoing and disables while submitting', (
    tester,
  ) async {
    Map<String, dynamic>? body;
    final gate = Completer<http.Response>();
    final controller = buildController(
      MockClient((request) async {
        body = jsonDecode(request.body) as Map<String, dynamic>;
        return gate.future;
      }),
    );
    controller.setText('direction text');
    await tester.pumpWidget(
      MaterialApp(home: CaptureScreen(controller: controller)),
    );
    expect(find.text('Создание задачи'), findsOneWidget);
    expect(find.text('Создать задачу'), findsOneWidget);
    await tester.tap(find.text('Направление'));
    await tester.pump();
    expect(controller.draft.completionMode, 'ongoing');
    expect(find.text('Создать направление'), findsOneWidget);
    expect(find.text('Название'), findsOneWidget);
    expect(find.text('Описание'), findsOneWidget);
    expect(find.text('Без срока'), findsOneWidget);
    expect(find.text('Запланированное время'), findsOneWidget);
    await tester.tap(find.byKey(const Key('capture_submit_button')));
    await tester.pump();
    final selector = tester.widget<SegmentedButton<String>>(
      find.byKey(const Key('capture_task_completion_mode')),
    );
    expect(selector.onSelectionChanged, isNull);
    gate.complete(http.Response(jsonEncode(createdBody()), 201));
    await tester.pumpAndSettle();
    expect(body!['completion_mode'], 'ongoing');
    expect(controller.draft.completionMode, 'finite');
  });

  test('fresh capture request drops abandoned context', () async {
    final controller = buildController(MockClient((request) async {
      return http.Response(jsonEncode(createdBody()), 201);
    }));
    final due = DateTime.utc(2026, 10, 2, 9);
    controller.beginTaskCaptureWithContext(_object('ctx-a', 'Рубрика'));
    controller.setText('abandoned');
    controller.setTitle('Старое');
    controller.setCompletionMode('ongoing');
    controller.setDueAt(due);
    controller.setPlannedInterval(due, due.add(const Duration(hours: 1)));
    controller.attachContext(
      CaptureContextRef(id: 'extra', title: 'Extra', kind: 'file'),
    );
    controller.beginFreshTaskCapture();
    controller.setText('Новая задача');
    controller.setTitle('TestTask');
    final request = controller.draft.toRequest().toJson();
    expect(request['context_object_ids'], isEmpty);
    expect(request['depends_on_ids'], isEmpty);
    expect(request['text'], 'Новая задача');
    expect(request['title'], 'TestTask');
    expect(request['completion_mode'], 'finite');
    expect(request['due_at'], isNull);
    expect(request['planned_start_at'], isNull);
    expect(request['planned_end_at'], isNull);
    expect(controller.submitState, CaptureSubmitState.idle);
  });

  test('new contextual session replaces the previous object', () {
    final controller = buildController(
      MockClient((request) async => http.Response('{}', 404)),
    );
    controller.beginTaskCaptureWithContext(_object('ctx-a', 'Рубрика A'));
    controller.setText('черновик A');
    controller.beginTaskCaptureWithContext(_object('ctx-b', 'Рубрика B'));
    expect(controller.draft.contextObjectIds, ['ctx-b']);
    expect(controller.draft.contextRefs.map((ref) => ref.title), ['Рубрика B']);
    expect(controller.draft.text, isEmpty);
    expect(controller.draft.toRequest().toJson()['context_object_ids'], ['ctx-b']);
  });

  test('same capture session keeps temporal fields while context stays attached', () {
    final controller = buildController(
      MockClient((request) async => http.Response('{}', 404)),
    );
    final due = DateTime.utc(2026, 10, 9, 18);
    final start = DateTime.utc(2026, 10, 6, 10);
    final end = DateTime.utc(2026, 10, 6, 12);
    controller.beginTaskCaptureWithContext(_object('ctx-a', 'Рубрика'));
    controller.setText('в этой сессии');
    controller.setCompletionMode('ongoing');
    controller.setDueAt(due);
    controller.setPlannedInterval(start, end);
    controller.attachContext(
      CaptureContextRef(id: 'file-1', title: 'Файл', kind: 'file'),
    );
    expect(controller.draft.contextObjectIds, ['ctx-a', 'file-1']);
    expect(controller.draft.completionMode, 'ongoing');
    expect(controller.draft.dueAt, due);
    expect(controller.draft.plannedStartAt, start);
    expect(controller.draft.plannedEndAt, end);
    expect(controller.draft.text, 'в этой сессии');
  });

  testWidgets(
    'abandoned object context does not enter the next global capture',
    (tester) async {
      final mock = MockClient((request) async {
        final path = request.url.path;
        for (final item in const [
          ('email-a', 'Rubric A'),
          ('email-b', 'Rubric B'),
        ]) {
          if (path == '/objects/${item.$1}') {
            return http.Response(
              jsonEncode(_objectJson(item.$1, item.$2)),
              200,
            );
          }
          if (path == '/objects/${item.$1}/neighbors') {
            return http.Response(
              jsonEncode({'object_id': item.$1, 'neighbors': []}),
              200,
            );
          }
          if (path == '/objects/${item.$1}/context') {
            return http.Response(
              jsonEncode({
                'object': _objectJson(item.$1, item.$2),
                'edges': [],
                'neighbors': [],
              }),
              200,
            );
          }
        }
        return http.Response('{}', 404);
      });
      final apiClient = SecretaryApiClient(httpClient: mock);
      apiClient.configure(baseUrl: baseUrl, token: token);
      final auth = AuthController(
        apiClient: apiClient,
        tokenStore: FakeTokenStore(),
        serverUrlStore: FakeServerUrlStore(),
      );
      final capture = CaptureController(apiClient: apiClient, authController: auth);
      capture.mergeDraft(
        CaptureDraft(
          text: 'старый текст',
          title: 'Старый заголовок',
          contextObjectIds: const ['stale'],
          contextRefs: const [
            CaptureContextRef(id: 'stale', title: 'Старое', kind: 'note'),
          ],
          dependsOnIds: const ['dep-stale'],
          completionMode: 'ongoing',
        ),
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Builder(
            builder: (context) => Scaffold(
              body: Column(
                children: [
                  TextButton(
                    onPressed: () => openCapture(
                      context,
                      captureController: capture,
                      authController: auth,
                    ),
                    child: const Text('Новая задача'),
                  ),
                  TextButton(
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (context) => ObjectDetailScreen(
                          objectId: 'email-a',
                          apiClient: apiClient,
                          authController: auth,
                          captureController: capture,
                        ),
                      ),
                    ),
                    child: const Text('Открыть A'),
                  ),
                  TextButton(
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (context) => ObjectDetailScreen(
                          objectId: 'email-b',
                          apiClient: apiClient,
                          authController: auth,
                          captureController: capture,
                        ),
                      ),
                    ),
                    child: const Text('Открыть B'),
                  ),
                ],
              ),
            ),
          ),
        ),
      );

      await tester.tap(find.text('Открыть A'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Использовать как контекст задачи'));
      await tester.pumpAndSettle();
      expect(find.text('Контекст: Rubric A'), findsOneWidget);
      expect(capture.draft.contextObjectIds, ['email-a']);
      expect(capture.draft.dependsOnIds, isEmpty);
      expect(capture.draft.text, isEmpty);
      expect(capture.draft.completionMode, 'finite');

      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(capture.draft.contextObjectIds, isEmpty);

      await tester.pageBack();
      await tester.pumpAndSettle();
      await tester.tap(find.text('Новая задача'));
      await tester.pumpAndSettle();
      expect(find.text('Создание задачи'), findsOneWidget);
      expect(find.textContaining('Контекст:'), findsNothing);
      expect(capture.draft.contextObjectIds, isEmpty);
      expect(capture.draft.dependsOnIds, isEmpty);
      expect(capture.draft.text, isEmpty);
      capture.setText('Несвязанная задача');
      expect(
        capture.draft.toRequest().toJson()['context_object_ids'],
        isEmpty,
      );

      await tester.pageBack();
      await tester.pumpAndSettle();
      await tester.tap(find.text('Открыть B'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Использовать как контекст задачи'));
      await tester.pumpAndSettle();
      expect(find.text('Контекст: Rubric B'), findsOneWidget);
      expect(find.text('Контекст: Rubric A'), findsNothing);
      expect(capture.draft.contextObjectIds, ['email-b']);
      final due = DateTime.utc(2026, 10, 9, 18);
      capture.setDueAt(due);
      capture.setCompletionMode('ongoing');
      expect(capture.draft.contextObjectIds, ['email-b']);
      expect(capture.draft.dueAt, due);
      expect(capture.draft.completionMode, 'ongoing');
    },
  );
}

SecretaryObject _object(String id, String title) {
  return SecretaryObject.fromJson(_objectJson(id, title));
}

Map<String, dynamic> _objectJson(String id, String title) {
  return {
    'id': id,
    'kind': 'email',
    'title': title,
    'body': null,
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
  };
}
