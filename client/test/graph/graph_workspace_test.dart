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
import 'package:personal_secretary/graph/graph_workspace_screen.dart';
import 'package:personal_secretary/screens/placeholder_screen.dart';
import 'package:personal_secretary/shell/app_shell.dart';

AuthController buildAuth(MockClient mock) {
  final apiClient = SecretaryApiClient(httpClient: mock);
  apiClient.configure(baseUrl: 'https://example.com', token: 'token');
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

MockClient graphMockClient() {
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
          'seed_ids': ['task-1'],
          'nodes': [
            {
              'id': 'task-1',
              'kind': 'task',
              'title': 'Graph task',
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
          ],
          'edges': [],
          'truncated': true,
        }),
        200,
      );
    }
    return http.Response('{}', 404);
  });
}

void main() {
  testWidgets('Graph destination is not PlaceholderScreen', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final auth = buildAuth(graphMockClient());
    final capture = CaptureController(apiClient: auth.apiClient, authController: auth);
    final assistant = AssistantController(
      apiClient: auth.apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(
        directory: Directory.systemTemp.createTempSync('graph_test_voice'),
      ),
    );
    final graph = GraphWorkspaceController(
      apiClient: auth.apiClient,
      authController: auth,
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

    expect(find.byType(PlaceholderScreen), findsNothing);
    expect(find.byType(GraphWorkspaceScreen), findsOneWidget);
    expect(find.text('Graph task'), findsOneWidget);
    expect(
      find.text('Некоторые связанные объекты скрыты лимитом рабочей области.'),
      findsOneWidget,
    );
  });
}
