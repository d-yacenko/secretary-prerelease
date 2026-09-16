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
import 'package:personal_secretary/graph/graph_workspace_controller.dart';
import 'package:personal_secretary/screens/placeholder_screen.dart';
import 'package:personal_secretary/shell/app_shell.dart';

const _baseUrl = 'https://secretary.example';
const _token = 'shell-token';

MockClient shellMockClient() {
  return MockClient((request) async {
    if (request.url.path == '/notifications') {
      return http.Response(jsonEncode({'notifications': []}), 200);
    }
    if (request.url.path == '/today') {
      return http.Response(
        jsonEncode({
          'date': '2026-08-28',
          'timezone': 'Europe/Amsterdam',
          'day_start': '2026-08-28T00:00:00+02:00',
          'tasks': [],
          'calendar_events': [],
          'notifications': [],
        }),
        200,
      );
    }
    if (request.url.path == '/graph/workspace') {
      return http.Response(
        jsonEncode({
          'root_id': null,
          'seed_ids': [],
          'nodes': [],
          'edges': [],
          'truncated': false,
        }),
        200,
      );
    }
    return http.Response('{}', 404);
  });
}

AuthController buildAuth() {
  final apiClient = SecretaryApiClient(httpClient: shellMockClient());
  apiClient.configure(baseUrl: _baseUrl, token: _token);
  final auth = AuthController(
    apiClient: apiClient,
    tokenStore: FakeTokenStore(),
    serverUrlStore: FakeServerUrlStore(),
  );
  auth.status = AuthStatus.authenticated;
  auth.user = UserMe(
    id: 'u1',
    displayName: 'Alice',
    createdAt: '2026-01-01T00:00:00Z',
  );
  return auth;
}

GraphWorkspaceController buildGraph(AuthController auth) {
  return GraphWorkspaceController(
    apiClient: auth.apiClient,
    authController: auth,
  );
}

void main() {
  testWidgets('narrow layout exposes five destinations and Capture FAB', (tester) async {
    tester.view.physicalSize = const Size(400, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final auth = buildAuth();
    final capture = CaptureController(
      apiClient: auth.apiClient,
      authController: auth,
    );
    final assistant = AssistantController(
      apiClient: auth.apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(
        directory: Directory.systemTemp.createTempSync('shell_test_voice'),
      ),
    );

    final graph = buildGraph(auth);

    await tester.pumpWidget(
      MaterialApp(
        home: AppShell(
          authController: auth,
          captureController: capture,
          assistantController: assistant,
          graphController: graph,
        ),
      ),
    );
    await tester.pumpAndSettle();

    for (final label in ['Входящие', 'Сегодня', 'Граф', 'Поиск', 'Секретарь']) {
      expect(find.text(label), findsWidgets);
    }
    expect(
      find.descendant(
        of: find.byType(FloatingActionButton),
        matching: find.text('Задача'),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byType(FloatingActionButton),
        matching: find.byIcon(Icons.add),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byType(FloatingActionButton),
        matching: find.text('Добавить'),
      ),
      findsNothing,
    );
    expect(find.byType(NavigationBar), findsOneWidget);
    expect(find.byType(PlaceholderScreen), findsNothing);
  });

  testWidgets('wide layout exposes NavigationRail and prominent Capture action', (tester) async {
    tester.view.physicalSize = const Size(900, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final auth = buildAuth();
    final capture = CaptureController(
      apiClient: auth.apiClient,
      authController: auth,
    );
    final assistant = AssistantController(
      apiClient: auth.apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(
        directory: Directory.systemTemp.createTempSync('shell_test_voice'),
      ),
    );

    final graph = buildGraph(auth);

    await tester.pumpWidget(
      MaterialApp(
        home: AppShell(
          authController: auth,
          captureController: capture,
          assistantController: assistant,
          graphController: graph,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byType(NavigationRail), findsOneWidget);
    final addButton = find.byKey(const Key('shell_add_button'));
    expect(
      find.descendant(of: addButton, matching: find.text('Задача')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: addButton, matching: find.text('Добавить')),
      findsNothing,
    );
    expect(
      find.descendant(of: addButton, matching: find.byIcon(Icons.add)),
      findsOneWidget,
    );
    expect(find.byType(FloatingActionButton), findsNothing);
  });

  testWidgets('returning to Graph refreshes workspace from server', (tester) async {
    tester.view.physicalSize = const Size(900, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var graphCalls = 0;
    final auth = AuthController(
      apiClient: SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.url.path == '/notifications') {
            return http.Response(jsonEncode({'notifications': []}), 200);
          }
          if (request.url.path == '/today') {
            return http.Response(
              jsonEncode({
                'date': '2026-08-28',
                'timezone': 'Europe/Amsterdam',
                'day_start': '2026-08-28T00:00:00+02:00',
                'tasks': [],
                'calendar_events': [],
                'notifications': [],
              }),
              200,
            );
          }
          if (request.url.path == '/graph/workspace') {
            graphCalls += 1;
            final nodes = graphCalls == 1
                ? [
                    {
                      'id': 'task-a',
                      'kind': 'task',
                      'title': 'Task A',
                      'body': null,
                      'provider': null,
                      'external_id': null,
                      'canonical_uri': null,
                      'status': 'open',
                      'start_at': null,
                      'due_at': null,
                      'metadata': {},
                      'origin': 'user',
                      'state': 'confirmed',
                      'confidence': null,
                      'created_at': '2026-01-01T00:00:00Z',
                      'updated_at': '2026-01-01T00:00:00Z',
                    },
                  ]
                : [
                    {
                      'id': 'task-a',
                      'kind': 'task',
                      'title': 'Task A',
                      'body': null,
                      'provider': null,
                      'external_id': null,
                      'canonical_uri': null,
                      'status': 'open',
                      'start_at': null,
                      'due_at': null,
                      'metadata': {},
                      'origin': 'user',
                      'state': 'confirmed',
                      'confidence': null,
                      'created_at': '2026-01-01T00:00:00Z',
                      'updated_at': '2026-01-01T00:00:00Z',
                    },
                    {
                      'id': 'task-b',
                      'kind': 'task',
                      'title': 'Task B',
                      'body': null,
                      'provider': null,
                      'external_id': null,
                      'canonical_uri': null,
                      'status': 'open',
                      'start_at': null,
                      'due_at': null,
                      'metadata': {},
                      'origin': 'user',
                      'state': 'confirmed',
                      'confidence': null,
                      'created_at': '2026-01-01T00:00:00Z',
                      'updated_at': '2026-01-01T00:00:00Z',
                    },
                  ];
            return http.Response(
              jsonEncode({
                'root_id': null,
                'seed_ids': nodes.map((n) => n['id']).toList(),
                'nodes': nodes,
                'edges': [],
                'truncated': false,
              }),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
      ),
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.apiClient.configure(baseUrl: _baseUrl, token: _token);
    auth.status = AuthStatus.authenticated;
    auth.user = UserMe(
      id: 'u1',
      displayName: 'Alice',
      createdAt: '2026-01-01T00:00:00Z',
    );

    final graph = buildGraph(auth);
    final capture = CaptureController(
      apiClient: auth.apiClient,
      authController: auth,
    );
    final assistant = AssistantController(
      apiClient: auth.apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(
        directory: Directory.systemTemp.createTempSync('shell_refresh_test'),
      ),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: AppShell(
          authController: auth,
          captureController: capture,
          assistantController: assistant,
          graphController: graph,
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('Граф'));
    await tester.pumpAndSettle();
    expect(find.text('Task A'), findsOneWidget);
    expect(find.text('Task B'), findsNothing);
    expect(graphCalls, 1);

    await tester.tap(find.text('Секретарь'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Граф'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));

    expect(graphCalls, greaterThanOrEqualTo(2));
    expect(find.text('Task B'), findsOneWidget);
  });
}
