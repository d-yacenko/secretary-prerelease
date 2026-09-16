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
import 'package:personal_secretary/timezone/client_timezone_context.dart';
import 'package:personal_secretary/shell/app_shell.dart';

http.Response jsonUtf8Response(Object body, {int statusCode = 200}) {
  return http.Response.bytes(
    utf8.encode(jsonEncode(body)),
    statusCode,
    headers: {'content-type': 'application/json; charset=utf-8'},
  );
}

Map<String, dynamic> graphObjectJson({
  required String id,
  required String title,
  String kind = 'task',
  String status = 'open',
  String? provider,
  String? dueAt,
  String? body,
}) {
  return {
    'id': id,
    'kind': kind,
    'title': title,
    'body': body,
    'provider': provider,
    'external_id': null,
    'canonical_uri': null,
    'status': status,
    'start_at': null,
    'due_at': dueAt,
    'metadata': {},
    'origin': 'user',
    'state': 'confirmed',
    'confidence': null,
    'created_at': '2026-01-01T00:00:00Z',
    'updated_at': '2026-01-01T00:00:00Z',
  };
}

Map<String, dynamic> graphWorkspaceJson({
  String? rootId,
  required List<Map<String, dynamic>> nodes,
  List<Map<String, dynamic>> edges = const [],
  bool truncated = false,
}) {
  return {
    'root_id': rootId,
    'seed_ids': nodes.map((n) => n['id']).toList(),
    'nodes': nodes,
    'edges': edges,
    'truncated': truncated,
  };
}

class GraphTestHarness {
  GraphTestHarness(this.mock);

  final MockClient mock;
  late final AuthController auth;
  late final CaptureController capture;
  late final AssistantController assistant;
  late final GraphWorkspaceController graph;

  void configure() {
    final apiClient = SecretaryApiClient(
      httpClient: mock,
      timezoneProvider: const FixedClientTimezoneProvider(
        ClientTimezoneContext(zoneId: 'Europe/Amsterdam', utcOffsetMinutes: 120),
      ),
    );
    apiClient.configure(baseUrl: 'https://example.com', token: 'token');
    auth = AuthController(
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
    capture = CaptureController(apiClient: apiClient, authController: auth);
    assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(
        directory: Directory.systemTemp.createTempSync('graph_screen_test'),
      ),
    );
    graph = GraphWorkspaceController(
      apiClient: apiClient,
      authController: auth,
    );
  }

  Widget app({TextScaler? textScaler}) {
    return MaterialApp(
      builder: (context, child) {
        if (textScaler != null) {
          return MediaQuery(
            data: MediaQuery.of(context).copyWith(textScaler: textScaler),
            child: child!,
          );
        }
        return child!;
      },
      home: AppShell(
        authController: auth,
        captureController: capture,
        assistantController: assistant,
        graphController: graph,
      ),
    );
  }
}

MockClient overviewMock({
  bool truncated = true,
  String nodeId = 'task-1',
  String title = 'Graph task',
  String status = 'open',
  String? provider,
}) {
  return MockClient((request) async {
    if (request.url.path == '/notifications') {
      return jsonUtf8Response({'notifications': []});
    }
    if (request.url.path == '/today') {
      return jsonUtf8Response({
        'date': '2026-08-28',
        'timezone': 'Europe/Amsterdam',
        'day_start': '2026-08-28T08:00:00+02:00',
        'tasks': [],
        'calendar_events': [],
        'notifications': [],
      });
    }
    if (request.url.path == '/graph/workspace') {
      return jsonUtf8Response(
        graphWorkspaceJson(
          nodes: [
            graphObjectJson(
              id: nodeId,
              title: title,
              status: status,
              provider: provider,
            ),
          ],
          truncated: truncated,
        ),
      );
    }
    if (request.url.path == '/search') {
      return jsonUtf8Response([
        graphObjectJson(id: 'search-root', title: 'Search hit'),
      ]);
    }
    if (request.url.path == '/search/facets') {
      return jsonUtf8Response({
        'kinds': [{'value': 'task', 'count': 1}],
        'providers': [],
      });
    }
    return jsonUtf8Response({}, statusCode: 404);
  });
}

Map<String, dynamic> graphObjectJsonWithProvider({
  required String id,
  required String title,
  required String provider,
  String kind = 'email',
  String status = 'open',
}) {
  final json = graphObjectJson(id: id, title: title, kind: kind, status: status);
  json['provider'] = provider;
  return json;
}

MockClient multiNodeOverviewMock() {
  return MockClient((request) async {
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
      final root = request.url.queryParameters['root_id'];
      if (root == 'task-center') {
        return jsonUtf8Response(
          graphWorkspaceJson(
            rootId: 'task-center',
            nodes: [
              graphObjectJson(id: 'task-center', title: 'Центральная задача', kind: 'task'),
              graphObjectJsonWithProvider(
                id: 'email-gmail',
                title: 'Gmail письмо',
                provider: 'gmail',
              ),
              graphObjectJsonWithProvider(
                id: 'email-yandex',
                title: 'Яндекс письмо',
                provider: 'yandex_mail',
              ),
              graphObjectJsonWithProvider(
                id: 'file-local',
                title: 'Локальный файл',
                kind: 'file',
                provider: 'local_device',
              ),
            ],
            edges: [
              {
                'id': 'e1',
                'source_id': 'task-center',
                'target_id': 'email-gmail',
                'type': 'references',
                'origin': 'user',
                'state': 'confirmed',
                'metadata': {},
                'created_at': '2026-01-01T00:00:00Z',
                'updated_at': '2026-01-01T00:00:00Z',
              },
              {
                'id': 'e2',
                'source_id': 'task-center',
                'target_id': 'email-yandex',
                'type': 'references',
                'origin': 'user',
                'state': 'confirmed',
                'metadata': {},
                'created_at': '2026-01-01T00:00:00Z',
                'updated_at': '2026-01-01T00:00:00Z',
              },
              {
                'id': 'e3',
                'source_id': 'task-center',
                'target_id': 'file-local',
                'type': 'references',
                'origin': 'user',
                'state': 'confirmed',
                'metadata': {},
                'created_at': '2026-01-01T00:00:00Z',
                'updated_at': '2026-01-01T00:00:00Z',
              },
            ],
          ),
        );
      }
      final nodes = List.generate(
        8,
        (index) => graphObjectJson(
          id: 'overview-$index',
          title: 'Обзорная задача $index',
          kind: index == 0 ? 'task' : 'email',
          provider: index == 1 ? 'gmail' : index == 2 ? 'yandex_mail' : index == 3 ? 'local_device' : null,
        ),
      );
      return jsonUtf8Response(graphWorkspaceJson(nodes: nodes, truncated: false));
    }
    if (request.url.path == '/search') {
      return jsonUtf8Response([]);
    }
    if (request.url.path == '/search/facets') {
      return jsonUtf8Response({
        'kinds': [
          {'value': 'task', 'count': 1},
          {'value': 'email', 'count': 7},
        ],
        'providers': [
          {'value': 'gmail', 'count': 1},
          {'value': 'yandex_mail', 'count': 1},
          {'value': 'local_device', 'count': 1},
        ],
      });
    }
    return jsonUtf8Response({}, statusCode: 404);
  });
}

Future<void> openGraph(WidgetTester tester, GraphTestHarness harness) async {
  await tester.pumpWidget(harness.app());
  await tester.pumpAndSettle();
  await tester.tap(find.text('Граф'));
  await tester.pumpAndSettle();
}
