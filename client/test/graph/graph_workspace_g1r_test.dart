import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/graph/focus_lod.dart';
import 'package:personal_secretary/graph/graph_map_edge_presentation.dart';

import 'graph_test_harness.dart';

Map<String, dynamic> _edge({
  required String id,
  required String sourceId,
  required String targetId,
  String type = 'part_of',
}) {
  return {
    'id': id,
    'source_id': sourceId,
    'target_id': targetId,
    'type': type,
    'origin': 'user',
    'state': 'confirmed',
    'metadata': {},
    'created_at': '2026-01-01T00:00:00Z',
    'updated_at': '2026-01-01T00:00:00Z',
  };
}

void main() {
  testWidgets(
    'admitted part_of is visible before Show relations and is not duplicated',
    (tester) async {
      tester.view.physicalSize = const Size(1280, 800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final child = graphObjectJson(
        id: 'task-child',
        title: 'Child task',
        completionMode: 'finite',
      );
      final parent = graphObjectJson(
        id: 'task-parent',
        title: 'Parent direction',
        completionMode: 'ongoing',
      );
      final structural = _edge(
        id: 'part-of-1',
        sourceId: 'task-child',
        targetId: 'task-parent',
      );
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
          if (request.url.path.endsWith('/neighbors')) {
            return jsonUtf8Response({
              'object_id': request.url.path.split('/')[2],
              'neighbors': [],
            });
          }
          if (request.url.path == '/graph/workspace') {
            return jsonUtf8Response(
              graphWorkspaceJson(
                rootId: request.url.queryParameters['root_id'],
                nodes: [child, parent],
                edges: [structural],
              ),
            );
          }
          return jsonUtf8Response({}, statusCode: 404);
        }),
      );
      harness.configure();
      await openGraph(tester, harness);

      SecretaryEdge loaded() {
        return harness.graph.edges.singleWhere((edge) => edge.id == 'part-of-1');
      }

      expect(harness.graph.edges.where((edge) => edge.id == 'part-of-1'), hasLength(1));
      final presentation = presentGraphMapEdge(
        edge: loaded(),
        sourceKind: 'task',
        targetKind: 'task',
      );
      expect(presentation.visibleOnTasksMap, isTrue);
      expect(presentation.directed, isTrue);
      expect(presentation.structural, isTrue);
      expect(
        focusLodEdgeIsVisible(
          edge: loaded(),
          fullCardIds: {'task-child', 'task-parent'},
        ),
        isTrue,
      );

      await tester.tap(find.text('Child task'));
      await tester.pumpAndSettle();
      expect(harness.graph.edges.where((edge) => edge.id == 'part-of-1'), hasLength(1));

      await tester.tap(find.text('Показать связи'));
      await tester.pumpAndSettle();
      expect(harness.graph.edges.where((edge) => edge.id == 'part-of-1'), hasLength(1));

      await tester.tap(find.text('Relax'));
      await tester.pumpAndSettle();
      expect(harness.graph.edges.where((edge) => edge.id == 'part-of-1'), hasLength(1));
      expect(
        presentGraphMapEdge(
          edge: loaded(),
          sourceKind: 'task',
          targetKind: 'task',
        ).visibleOnTasksMap,
        isTrue,
      );

      await tester.tap(find.text('Preserve'));
      await tester.pumpAndSettle();
      expect(harness.graph.edges.where((edge) => edge.id == 'part-of-1'), hasLength(1));
    },
  );
}
