import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets('detail inventory shows a persisted relation that is off the canvas', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final rooted = <String>[];
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
        if (request.url.path == '/objects/task-a/neighbors') {
          return jsonUtf8Response({
            'object_id': 'task-a',
            'neighbors': [
              {
                'object': graphObjectJson(id: 'task-b', title: 'On canvas'),
                'edge': _edge(
                  id: 'edge-on-canvas',
                  sourceId: 'task-a',
                  targetId: 'task-b',
                  type: 'related_to',
                ),
                'direction': 'outgoing',
              },
              {
                'object': graphObjectJson(id: 'task-c', title: 'Hidden task'),
                'edge': _edge(
                  id: 'edge-hidden',
                  sourceId: 'task-a',
                  targetId: 'task-c',
                  type: 'part_of',
                ),
                'direction': 'outgoing',
              },
            ],
          });
        }
        if (request.url.path == '/graph/workspace') {
          final rootId = request.url.queryParameters['root_id'];
          if (rootId != null) {
            rooted.add(rootId);
          }
          if (rootId == 'task-c') {
            return jsonUtf8Response(
              graphWorkspaceJson(
                rootId: 'task-c',
                nodes: [
                  graphObjectJson(id: 'task-c', title: 'Hidden task'),
                ],
              ),
            );
          }
          return jsonUtf8Response(
            graphWorkspaceJson(
              nodes: [
                graphObjectJson(id: 'task-a', title: 'Selected'),
                graphObjectJson(id: 'task-b', title: 'On canvas'),
              ],
              edges: [
                _edge(
                  id: 'edge-on-canvas',
                  sourceId: 'task-a',
                  targetId: 'task-b',
                  type: 'related_to',
                ),
              ],
            ),
          );
        }
        return jsonUtf8Response({}, statusCode: 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);
    await tester.tap(find.text('Selected'));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('graph-relation-edge-on-canvas')), findsOneWidget);
    expect(find.byKey(const ValueKey('graph-relation-edge-hidden')), findsOneWidget);
    expect(find.byKey(const ValueKey('graph-off-canvas-edge-hidden')), findsOneWidget);
    expect(find.textContaining('не на карте'), findsOneWidget);

    await _tapVisibleTop(tester, find.byKey(const ValueKey('graph-relation-edge-hidden')));
    await tester.pumpAndSettle();

    expect(rooted, contains('task-c'));
    expect(find.text('Hidden task'), findsWidgets);
  });

  testWidgets('failed relation inventory keeps the graph usable', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var neighborAttempts = 0;
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
        if (request.url.path == '/objects/task-a/neighbors') {
          neighborAttempts += 1;
          return jsonUtf8Response({'detail': 'unavailable'}, statusCode: 500);
        }
        if (request.url.path == '/graph/workspace') {
          return jsonUtf8Response(
            graphWorkspaceJson(
              nodes: [
                graphObjectJson(id: 'task-a', title: 'Selected'),
                graphObjectJson(id: 'task-b', title: 'On canvas'),
              ],
              edges: [
                _edge(
                  id: 'edge-on-canvas',
                  sourceId: 'task-a',
                  targetId: 'task-b',
                  type: 'related_to',
                ),
              ],
            ),
          );
        }
        return jsonUtf8Response({}, statusCode: 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);
    await tester.tap(find.text('Selected'));
    await tester.pumpAndSettle();

    expect(find.text('Selected'), findsWidgets);
    expect(find.byKey(const ValueKey('graph-relation-edge-on-canvas')), findsOneWidget);
    expect(find.byKey(const ValueKey('graph-relation-inventory-error')), findsOneWidget);
    expect(find.text('Не удалось загрузить полный список связей.'), findsOneWidget);

    await _tapVisibleTop(
      tester,
      find.byKey(const ValueKey('graph-relation-inventory-retry')),
    );
    await tester.pumpAndSettle();
    expect(neighborAttempts, greaterThan(1));
    expect(find.text('Selected'), findsWidgets);
    expect(find.byKey(const ValueKey('graph-canvas-region')), findsOneWidget);
  });
}

Future<void> _tapVisibleTop(WidgetTester tester, Finder finder) async {
  final topLeft = tester.getTopLeft(finder);
  await tester.tapAt(topLeft + const Offset(20, 8));
}

Map<String, dynamic> _edge({
  required String id,
  required String sourceId,
  required String targetId,
  required String type,
}) {
  return {
    'id': id,
    'source_id': sourceId,
    'target_id': targetId,
    'type': type,
    'origin': 'user',
    'state': 'confirmed',
    'metadata': <String, dynamic>{},
    'created_at': '2026-01-01T00:00:00Z',
    'updated_at': '2026-01-01T00:00:00Z',
  };
}
