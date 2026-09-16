import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/assistant/assistant_controller.dart';
import 'package:personal_secretary/assistant/fake_voice_recorder.dart';
import 'package:personal_secretary/assistant/voice_temp_files.dart';
import 'package:personal_secretary/capture/capture_controller.dart';
import 'package:personal_secretary/capture/capture_screen.dart';
import 'package:personal_secretary/capture/capture_draft.dart';
import 'package:personal_secretary/objects/object_detail_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'graph/graph_test_harness.dart';

http.Response _jsonResponse(Object body, {int statusCode = 200}) {
  return http.Response.bytes(
    utf8.encode(jsonEncode(body)),
    statusCode,
    headers: {'content-type': 'application/json; charset=utf-8'},
  );
}

Map<String, dynamic> _objectJson({
  required String id,
  required String kind,
  required String title,
  String origin = 'user',
  String state = 'confirmed',
  String? provider,
  String? body,
  Map<String, dynamic>? metadata,
}) {
  return {
    'id': id,
    'kind': kind,
    'title': title,
    'body': body,
    'provider': provider,
    'external_id': null,
    'canonical_uri': null,
    'status': null,
    'start_at': null,
    'due_at': null,
    'metadata': metadata ?? {},
    'origin': origin,
    'state': state,
    'confidence': null,
    'created_at': '2026-01-01T00:00:00Z',
    'updated_at': '2026-01-01T00:00:00Z',
  };
}

Future<void> _pumpObjectDetailReady(WidgetTester tester) async {
  await tester.pump();
  for (var i = 0; i < 40; i++) {
    await tester.pump(const Duration(milliseconds: 50));
    if (find.byType(CircularProgressIndicator).evaluate().isEmpty) {
      break;
    }
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('CaptureScreen shows add file and voice controls', (tester) async {
    final mock = MockClient((request) async => http.Response('{}', 404));
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: 'https://example.com', token: 'token');
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final capture = CaptureController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(
        directory: Directory.systemTemp.createTempSync('capture_widget_test'),
      ),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: CaptureScreen(controller: capture, authController: auth),
      ),
    );

    expect(find.text('Создание задачи'), findsOneWidget);
    expect(find.text('Создать задачу'), findsOneWidget);
    expect(find.text('Заметка'), findsNothing);
    expect(find.text('Добавить файл'), findsOneWidget);
    expect(find.byKey(const Key('capture_voice_button')), findsOneWidget);
  });

  test('attachObjectContext does not submit capture task', () async {
    int postCount = 0;
    final mock = MockClient((request) async {
      if (request.method == 'POST' && request.url.path == '/capture/tasks') {
        postCount += 1;
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: 'https://example.com', token: 'token');
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    final capture = CaptureController(apiClient: apiClient, authController: auth);
    capture.attachObjectContext(
      SecretaryObject(
        id: 'obj-1',
        kind: 'document',
        title: 'notes.md',
        metadata: {},
        origin: 'user',
        state: 'confirmed',
        createdAt: '2026-01-01T00:00:00Z',
        updatedAt: '2026-01-01T00:00:00Z',
      ),
    );
    expect(capture.draft.contextRefs.length, 1);
    expect(capture.submitState, CaptureSubmitState.idle);
    expect(postCount, 0);
  });

  testWidgets('ObjectDetail shows local open and show-in-folder', (tester) async {
    SharedPreferences.setMockInitialValues({
      'secretary_device_key': 'desk-linux',
      'secretary_device_display_name': 'Linux desk',
    });
    final mock = MockClient((request) async {
      if (request.url.path == '/objects/file-1') {
        return _jsonResponse(_objectJson(
          id: 'file-1',
          kind: 'document',
          title: 'notes.md',
          provider: 'local_device',
        ));
      }
      if (request.url.path == '/objects/file-1/neighbors') {
        return _jsonResponse({'object_id': 'file-1', 'neighbors': []});
      }
      if (request.url.path == '/objects/file-1/context') {
        return _jsonResponse({
          'object': _objectJson(
            id: 'file-1',
            kind: 'document',
            title: 'notes.md',
            provider: 'local_device',
          ),
          'edges': [],
          'neighbors': [],
        });
      }
      if (request.url.path == '/objects/file-1/open-target') {
        return _jsonResponse({
          'available': true,
          'action': 'local_file',
          'label': 'Открыть файл',
          'device_key': 'desk-linux',
          'local_path': '/home/user/notes.md',
        });
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: 'https://example.com', token: 'token');
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final capture = CaptureController(apiClient: apiClient, authController: auth);

    await tester.pumpWidget(
      MaterialApp(
        home: ObjectDetailScreen(
          objectId: 'file-1',
          apiClient: apiClient,
          authController: auth,
          captureController: capture,
        ),
      ),
    );
    await _pumpObjectDetailReady(tester);

    expect(find.byKey(const Key('object_detail_open_source')), findsOneWidget);
    expect(find.byKey(const Key('object_detail_show_in_folder')), findsOneWidget);
  });

  testWidgets('ObjectDetail email attachment section only for mail attachments', (tester) async {
    final mock = MockClient((request) async {
      if (request.url.path == '/objects/email-1') {
        return _jsonResponse(_objectJson(
          id: 'email-1',
          kind: 'email',
          title: 'Mail',
          body: 'Body',
          provider: 'gmail',
          origin: 'source',
          state: 'observed',
        ));
      }
      if (request.url.path == '/objects/email-1/neighbors') {
        return _jsonResponse({
          'object_id': 'email-1',
          'neighbors': [
            {
              'object': _objectJson(
                id: 'att-1',
                kind: 'file',
                title: 'note.txt',
                provider: 'gmail',
                origin: 'source',
                state: 'observed',
                metadata: {'mime_type': 'text/plain', 'size': 12},
              ),
              'edge': {
                'id': 'edge-att',
                'source_id': 'email-1',
                'target_id': 'att-1',
                'type': 'contains',
                'origin': 'source',
                'confidence': null,
                'state': 'observed',
                'metadata': {'source_fact': 'email_attachment'},
                'created_at': '2026-01-01T00:00:00Z',
                'updated_at': '2026-01-01T00:00:00Z',
              },
              'direction': 'outgoing',
            },
          ],
        });
      }
      if (request.url.path == '/objects/email-1/context') {
        return _jsonResponse({
          'object': _objectJson(
            id: 'email-1',
            kind: 'email',
            title: 'Mail',
            body: 'Body',
            provider: 'gmail',
            origin: 'source',
            state: 'observed',
          ),
          'edges': [],
          'neighbors': [],
        });
      }
      if (request.url.path == '/objects/email-1/open-target') {
        return _jsonResponse({
          'available': true,
          'action': 'web_url',
          'label': 'Открыть в Gmail',
          'url': 'https://mail.google.com/',
        });
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: 'https://example.com', token: 'token');
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final capture = CaptureController(apiClient: apiClient, authController: auth);

    await tester.pumpWidget(
      MaterialApp(
        home: ObjectDetailScreen(
          objectId: 'email-1',
          apiClient: apiClient,
          authController: auth,
          captureController: capture,
        ),
      ),
    );
    await _pumpObjectDetailReady(tester);

    expect(find.text('Вложения'), findsOneWidget);
    expect(find.text('note.txt'), findsOneWidget);
    expect(find.textContaining('text/plain'), findsOneWidget);
  });

  testWidgets('ObjectDetail folder child is not shown as email attachment', (tester) async {
    final mock = MockClient((request) async {
      if (request.url.path == '/objects/folder-1') {
        return _jsonResponse(_objectJson(
          id: 'folder-1',
          kind: 'folder',
          title: 'Docs',
          provider: 'local_device',
        ));
      }
      if (request.url.path == '/objects/folder-1/neighbors') {
        return _jsonResponse({
          'object_id': 'folder-1',
          'neighbors': [
            {
              'object': _objectJson(
                id: 'child-file',
                kind: 'file',
                title: 'child.txt',
                provider: 'local_device',
              ),
              'edge': {
                'id': 'edge-folder',
                'source_id': 'folder-1',
                'target_id': 'child-file',
                'type': 'contains',
                'origin': 'user',
                'confidence': null,
                'state': 'confirmed',
                'metadata': {},
                'created_at': '2026-01-01T00:00:00Z',
                'updated_at': '2026-01-01T00:00:00Z',
              },
              'direction': 'outgoing',
            },
          ],
        });
      }
      if (request.url.path == '/objects/folder-1/context') {
        return _jsonResponse({
          'object': _objectJson(
            id: 'folder-1',
            kind: 'folder',
            title: 'Docs',
            provider: 'local_device',
          ),
          'edges': [],
          'neighbors': [],
        });
      }
      if (request.url.path == '/objects/folder-1/open-target') {
        return _jsonResponse({
          'available': false,
          'action': 'unavailable',
          'label': 'Открыть папку',
          'reason': 'client_source_path_missing',
        });
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: 'https://example.com', token: 'token');
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final capture = CaptureController(apiClient: apiClient, authController: auth);

    await tester.pumpWidget(
      MaterialApp(
        home: ObjectDetailScreen(
          objectId: 'folder-1',
          apiClient: apiClient,
          authController: auth,
          captureController: capture,
        ),
      ),
    );
    await _pumpObjectDetailReady(tester);

    expect(find.text('Вложения'), findsNothing);
    expect(find.text('child.txt'), findsOneWidget);
  });

  testWidgets('Graph source label updates when selected object changes', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = GraphTestHarness(
      MockClient((request) async {
        if (request.url.path == '/notifications') {
          return jsonUtf8Response({'notifications': []});
        }
        if (request.url.path == '/today') {
          return jsonUtf8Response({
            'date': '2026-08-28',
            'timezone': 'Europe/Amsterdam',
            'day_start': '2026-08-28T00:00:00+02:00',
            'tasks': [],
            'calendar_events': [],
            'notifications': [],
          });
        }
        if (request.url.path == '/graph/workspace') {
          return jsonUtf8Response(
            graphWorkspaceJson(
              nodes: [
                graphObjectJsonWithProvider(
                  id: 'email-gmail',
                  title: 'Gmail mail',
                  provider: 'gmail',
                ),
                graphObjectJsonWithProvider(
                  id: 'file-local',
                  title: 'Local file',
                  kind: 'file',
                  provider: 'local_device',
                ),
              ],
            ),
          );
        }
        if (request.url.path.endsWith('/open-target')) {
          final id = request.url.pathSegments[1];
          if (id == 'email-gmail') {
            return jsonUtf8Response({
              'available': true,
              'action': 'web_url',
              'label': 'Открыть в Gmail',
              'url': 'https://mail.google.com/',
            });
          }
          return jsonUtf8Response({
            'available': false,
            'action': 'unavailable',
            'label': 'Открыть файл',
            'reason': 'client_source_path_missing',
          });
        }
        return jsonUtf8Response({}, statusCode: 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);

    harness.graph.selectObject('email-gmail');
    await tester.pumpAndSettle();
    expect(find.text('Открыть в Gmail'), findsOneWidget);

    harness.graph.selectObject('file-local');
    await tester.pumpAndSettle();
    expect(find.text('Открыть в Gmail'), findsNothing);
    expect(find.text('Исходный файл сейчас недоступен на этом устройстве'), findsOneWidget);
  });

  test('assistant single file sets context without sending message', () async {
    int assistantPosts = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        assistantPosts += 1;
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: 'https://example.com', token: 'token');
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    final assistant = AssistantController(apiClient: apiClient, authController: auth);
    assistant.setObjectContext(
      SecretaryObject(
        id: 'doc-1',
        kind: 'document',
        title: 'notes.md',
        metadata: {},
        origin: 'user',
        state: 'confirmed',
        createdAt: '2026-01-01T00:00:00Z',
        updatedAt: '2026-01-01T00:00:00Z',
      ),
    );
    expect(assistant.objectContext?.id, 'doc-1');
    expect(assistantPosts, 0);
  });
}
