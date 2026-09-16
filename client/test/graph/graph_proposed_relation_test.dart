import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/ui/domain_labels.dart';
import 'package:personal_secretary/ui/object_visuals.dart';

import 'graph_test_harness.dart';

void main() {
  test('folder kind and contains relation labels', () {
    expect(objectKindLabel('folder'), 'Папка');
    expect(relationTypeLabel('contains'), 'Содержит');
    expect(iconForKind('folder'), Icons.folder_outlined);
  });

  testWidgets('proposed relation confirm keeps edge as confirmed', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var decisionCalled = false;
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
                graphObjectJson(id: 'task-a', title: 'Task A'),
                graphObjectJson(id: 'task-b', title: 'Task B', kind: 'note'),
              ],
              edges: [
                {
                  'id': 'edge-proposed',
                  'source_id': 'task-a',
                  'target_id': 'task-b',
                  'type': 'related_to',
                  'origin': 'agent',
                  'state': 'proposed',
                  'confidence': 0.9,
                  'metadata': {},
                  'created_at': '2026-01-01T00:00:00Z',
                  'updated_at': '2026-01-01T00:00:00Z',
                },
              ],
            ),
          );
        }
        if (request.method == 'POST' &&
            request.url.path == '/relations/edge-proposed/decision') {
          decisionCalled = true;
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['decision'], 'confirm');
          return jsonUtf8Response({
            'edge': {
              'id': 'edge-proposed',
              'source_id': 'task-a',
              'target_id': 'task-b',
              'type': 'related_to',
              'origin': 'agent',
              'state': 'confirmed',
              'confidence': 0.9,
              'metadata': {},
              'created_at': '2026-01-01T00:00:00Z',
              'updated_at': '2026-01-01T00:00:00Z',
            },
          });
        }
        return jsonUtf8Response({}, statusCode: 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);

    await tester.tap(find.text('Task A'));
    await tester.pumpAndSettle();

    expect(find.textContaining('Предложено'), findsOneWidget);
    expect(find.byTooltip('Подтвердить'), findsOneWidget);
    expect(find.byTooltip('Отклонить'), findsOneWidget);

    await tester.tap(find.byTooltip('Подтвердить'));
    await tester.pumpAndSettle();

    expect(decisionCalled, isTrue);
    expect(harness.graph.edges.first.state, 'confirmed');
    expect(find.textContaining('Предложено'), findsNothing);
  });

  testWidgets('proposed relation reject removes edge from graph UI', (tester) async {
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
                graphObjectJson(id: 'task-a', title: 'Task A'),
                graphObjectJson(id: 'task-b', title: 'Task B', kind: 'note'),
              ],
              edges: [
                {
                  'id': 'edge-proposed',
                  'source_id': 'task-a',
                  'target_id': 'task-b',
                  'type': 'related_to',
                  'origin': 'agent',
                  'state': 'proposed',
                  'confidence': 0.9,
                  'metadata': {},
                  'created_at': '2026-01-01T00:00:00Z',
                  'updated_at': '2026-01-01T00:00:00Z',
                },
              ],
            ),
          );
        }
        if (request.method == 'POST' &&
            request.url.path == '/relations/edge-proposed/decision') {
          return jsonUtf8Response({
            'edge': {
              'id': 'edge-proposed',
              'source_id': 'task-a',
              'target_id': 'task-b',
              'type': 'related_to',
              'origin': 'agent',
              'state': 'rejected',
              'confidence': 0.9,
              'metadata': {},
              'created_at': '2026-01-01T00:00:00Z',
              'updated_at': '2026-01-01T00:00:00Z',
            },
          });
        }
        return jsonUtf8Response({}, statusCode: 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);

    harness.graph.selectObject('task-a');
    await tester.pump();

    await tester.tap(find.byTooltip('Отклонить'));
    await tester.pumpAndSettle();

    expect(harness.graph.edges, isEmpty);
    expect(find.byTooltip('Подтвердить'), findsNothing);
  });

  testWidgets('observed relation has no proposal decision controls', (tester) async {
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
                graphObjectJson(id: 'task-a', title: 'Task A'),
                graphObjectJson(id: 'email-1', title: 'Mail', kind: 'email'),
              ],
              edges: [
                {
                  'id': 'edge-observed',
                  'source_id': 'task-a',
                  'target_id': 'email-1',
                  'type': 'references',
                  'origin': 'source',
                  'state': 'observed',
                  'confidence': null,
                  'metadata': {},
                  'created_at': '2026-01-01T00:00:00Z',
                  'updated_at': '2026-01-01T00:00:00Z',
                },
              ],
            ),
          );
        }
        return jsonUtf8Response({}, statusCode: 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);

    harness.graph.selectObject('task-a');
    await tester.pump();

    expect(find.byTooltip('Подтвердить'), findsNothing);
    expect(find.byTooltip('Отклонить'), findsNothing);
  });
}
