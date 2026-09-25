import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/graph/graph_workspace_screen.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets('Задачи | Люди switches workspace and keeps task mode compatible', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final paths = <String>[];
    final harness = GraphTestHarness(
      MockClient((request) async {
        paths.add('${request.method} ${request.url.path}?${request.url.query}');
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
        if (request.url.path == '/search/facets') {
          return jsonUtf8Response({'kinds': [], 'providers': []});
        }
        if (request.url.path == '/graph/workspace') {
          return jsonUtf8Response(
            graphWorkspaceJson(nodes: [graphObjectJson(id: 'task-1', title: 'Graph task')]),
          );
        }
        if (request.url.path == '/graph/people-workspace') {
          final query = request.url.queryParameters['q'];
          final root = request.url.queryParameters['root_id'];
          if (query == 'olga@example.com' || root == 'person-search') {
            return jsonUtf8Response(
              _peopleWorkspace(
                rootId: root,
                personId: 'person-search',
                title: 'Olga Search',
                email: 'olga@example.com',
              ),
            );
          }
          return jsonUtf8Response(
            _peopleWorkspace(
              personId: 'person-1',
              title: 'Olga',
              email: 'olga@example.com',
              taskId: 'task-linked',
              taskTitle: 'Reply to Olga',
            ),
          );
        }
        if (request.url.path.endsWith('/identity-correction')) {
          return jsonUtf8Response({
            'person_id': 'person-1',
            'evidence_id': 'evidence-1',
            'evidence_type': 'user_rejected',
            'state': 'active',
          });
        }
        return http.Response('{}', 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);

    expect(find.text('Задачи'), findsOneWidget);
    expect(find.text('Люди'), findsOneWidget);
    expect(find.text('Graph task'), findsOneWidget);
    expect(harness.graph.mode.name, 'tasks');

    harness.graph.selectObject('task-1');
    await tester.pump();
    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();

    expect(harness.graph.selectedObjectId, isNull);
    expect(find.text('Olga'), findsWidgets);
    expect(find.textContaining('email'), findsWidgets);
    expect(paths.any((path) => path.contains('/graph/people-workspace')), isTrue);

    await tester.tap(find.text('Olga').first);
    await tester.pumpAndSettle();
    expect(find.text('olga@example.com'), findsWidgets);
    expect(find.text('Reply to Olga'), findsOneWidget);
    expect(find.text('Открытые задачи: 1'), findsOneWidget);
    expect(find.text('Письмо Olga'), findsOneWidget);

    await tester.enterText(find.byType(TextField), 'olga@example.com');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Olga Search'));
    await tester.pumpAndSettle();
    expect(harness.graph.rootId, 'person-search');
    expect(find.text('Olga Search'), findsWidgets);
  });
}

Map<String, dynamic> _peopleWorkspace({
  String? rootId,
  required String personId,
  required String title,
  required String email,
  String? taskId,
  String? taskTitle,
}) {
  final nodes = [
    graphObjectJson(id: personId, title: title, kind: 'person'),
    if (taskId != null) graphObjectJson(id: taskId, title: taskTitle!, kind: 'task'),
  ];
  return {
    ...graphWorkspaceJson(
      rootId: rootId,
      nodes: nodes,
      edges: taskId == null
          ? []
          : [
              {
                'id': 'edge-1',
                'source_id': personId,
                'target_id': taskId,
                'type': 'related_to',
                'origin': 'user',
                'state': 'confirmed',
                'metadata': {},
                'created_at': '2026-01-01T00:00:00Z',
                'updated_at': '2026-01-01T00:00:00Z',
              },
            ],
    ),
    'people': [
      {
        'person_id': personId,
        'title': title,
        'salience_score': 1,
        'identities': [
          {
            'provider': 'email',
            'identity_type': 'email',
            'display_value': email,
            'realm': '',
            'canonical_value': email,
            'state': 'effective',
            'confirmable': false,
          },
        ],
        'routes': [
          {'provider': 'email', 'label': 'Письмо $title', 'route_key': 'email:$email'},
        ],
        'identity_conflict': false,
        'open_task_count': taskId == null ? 0 : 1,
        'recent_communication_count': 0,
      },
    ],
  };
}
