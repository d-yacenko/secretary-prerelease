import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets('semantic windows replace overview state and keep local expansion', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final workspaceCalls = <String>[];
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
        if (request.url.path == '/objects/task-parent/neighbors') {
          return jsonUtf8Response({
            'object_id': 'task-parent',
            'neighbors': [
              {
                'object': graphObjectJson(id: 'task-other', title: 'Другая область'),
                'edge': {
                  'id': 'edge-off',
                  'source_id': 'task-parent',
                  'target_id': 'task-other',
                  'type': 'related_to',
                  'origin': 'user',
                  'state': 'confirmed',
                  'metadata': <String, dynamic>{},
                  'created_at': '2026-01-01T00:00:00Z',
                  'updated_at': '2026-01-01T00:00:00Z',
                },
                'direction': 'outgoing',
              },
            ],
          });
        }
        if (request.url.path == '/graph/workspace') {
          workspaceCalls.add(request.url.query);
          final root = request.url.queryParameters['root_id'];
          final window = request.url.queryParameters['window_index'] ?? '0';
          if (root == 'task-parent') {
            return jsonUtf8Response(
              graphWorkspaceJson(
                rootId: 'task-parent',
                nodes: [
                  graphObjectJson(id: 'task-parent', title: 'Направление'),
                  graphObjectJson(id: 'task-child', title: 'Часть'),
                  graphObjectJson(id: 'note-local', title: 'Локальный контекст', kind: 'note'),
                ],
                truncated: true,
              ),
            );
          }
          if (window == '1') {
            return jsonUtf8Response(
              _window(
                nodes: [graphObjectJson(id: 'task-next', title: 'Соседняя область')],
                windowIndex: 1,
                hasPrevious: true,
              ),
            );
          }
          return jsonUtf8Response(
            _window(
              nodes: [
                graphObjectJson(id: 'task-parent', title: 'Направление'),
                graphObjectJson(id: 'task-child', title: 'Часть'),
                graphObjectJson(id: 'note-flow', title: 'Подтверждение', kind: 'note'),
              ],
              windowIndex: 0,
              hasNext: true,
            ),
          );
        }
        return jsonUtf8Response({}, statusCode: 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);

    expect(find.text('Область 1 из 2'), findsOneWidget);
    expect(find.text('Направление'), findsWidgets);
    expect(find.text('Часть'), findsWidgets);
    expect(find.text('Подтверждение'), findsWidgets);
    expect(
      find.text(
        'Показана часть пространства графа: направления и соцветия в этой области показаны целиком. '
        'Перейдите в соседнюю область, чтобы увидеть остальные.',
      ),
      findsOneWidget,
    );
    expect(
      tester.widget<IconButton>(find.byKey(const ValueKey('graph-overview-window-previous'))).onPressed,
      isNull,
    );
    expect(
      tester.widget<IconButton>(find.byKey(const ValueKey('graph-overview-window-next'))).onPressed,
      isNotNull,
    );

    harness.graph.selectObject('task-parent');
    await tester.pumpAndSettle();
    expect(find.textContaining('вне текущей области'), findsOneWidget);

    final callsBeforeRefine = workspaceCalls.length;
    await tester.tap(find.text('Relax'));
    await tester.pumpAndSettle();
    expect(workspaceCalls.length, callsBeforeRefine);
    expect(harness.graph.nodes.map((node) => node.id), containsAll(['task-parent', 'task-child', 'note-flow']));

    await tester.tap(find.byKey(const ValueKey('graph-overview-window-next')));
    await tester.pumpAndSettle();
    expect(find.text('Соседняя область'), findsWidgets);
    expect(find.text('Направление'), findsNothing);
    expect(find.text('Область 2 из 2'), findsOneWidget);
    expect(harness.graph.selectedObjectId, isNull);
    expect(
      tester.widget<IconButton>(find.byKey(const ValueKey('graph-overview-window-next'))).onPressed,
      isNull,
    );

    await tester.tap(find.byKey(const ValueKey('graph-overview-window-previous')));
    await tester.pumpAndSettle();
    expect(find.text('Направление'), findsWidgets);
    expect(find.text('Соседняя область'), findsNothing);

    harness.graph.selectObject('task-parent');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Показать связи'));
    await tester.pumpAndSettle();
    expect(find.text('Локальный контекст'), findsWidgets);
    expect(find.text('Направление'), findsWidgets);

    await tester.tap(find.byTooltip('К обзору'));
    await tester.pumpAndSettle();
    expect(find.text('Область 1 из 2'), findsOneWidget);
    expect(find.text('Локальный контекст'), findsNothing);
    expect(find.text('Подтверждение'), findsWidgets);
    expect(harness.graph.rootId, isNull);
  });
}

Map<String, dynamic> _window({
  required List<Map<String, dynamic>> nodes,
  required int windowIndex,
  bool hasPrevious = false,
  bool hasNext = false,
}) {
  return {
    ...graphWorkspaceJson(nodes: nodes, truncated: true),
    'window_index': windowIndex,
    'window_count': 2,
    'has_previous_window': hasPrevious,
    'has_next_window': hasNext,
    'constellation_root_ids': [nodes.first['id']],
    'semantic_window_complete': true,
  };
}
