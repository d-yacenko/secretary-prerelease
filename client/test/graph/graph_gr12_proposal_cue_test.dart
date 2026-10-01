import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets('compact canvas shows one proposal cue before selection', (tester) async {
    tester.view.physicalSize = const Size(1280, 900);
    tester.view.devicePixelRatio = 1;
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
                graphObjectJson(id: 'task', title: 'Publication'),
                graphObjectJson(id: 'file', title: 'Committee decision', kind: 'file'),
              ],
              edges: [
                _edge('ref', 'task', 'file', 'references', 'user', 'confirmed'),
                _edge('rel', 'file', 'task', 'related_to', 'agent', 'proposed'),
              ],
            ),
          );
        }
        return jsonUtf8Response({}, statusCode: 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);

    expect(find.byKey(const ValueKey('hybrid-glyph-file')), findsOneWidget);
    final beforeTask = tester.getTopLeft(find.byKey(const ValueKey('drawn-task')));
    final beforeGlyph = tester.getTopLeft(find.byKey(const ValueKey('hybrid-glyph-file')));
    final before = _pairHairline(tester);
    expect(before.proposed, isFalse);
    expect(before.proposalCue, isTrue);
    expect(before.directed, isTrue);
    expect(before.dashed, isFalse);

    harness.graph.selectObject('task');
    await tester.pumpAndSettle();
    expect(before.proposalCue, isTrue);

    harness.graph.selectObject(null);
    await tester.pumpAndSettle();
    harness.graph.removeEdge('rel');
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('hybrid-glyph-file')), findsOneWidget);
    final after = _pairHairline(tester);
    expect(after.proposalCue, isFalse);
    expect(after.proposed, isFalse);
    expect(after.directed, isTrue);
    expect(after.start, before.start);
    expect(after.end, before.end);
    expect(tester.getTopLeft(find.byKey(const ValueKey('drawn-task'))), beforeTask);
    expect(tester.getTopLeft(find.byKey(const ValueKey('hybrid-glyph-file'))), beforeGlyph);
  });
}

dynamic _pairHairline(WidgetTester tester) {
  final matches = <dynamic>[];
  for (final paint in tester.widgetList<CustomPaint>(find.byType(CustomPaint))) {
    final painter = paint.painter;
    if (painter == null || painter.runtimeType.toString() != 'HybridHairlinePainter') {
      continue;
    }
    final hairlines = (painter as dynamic).hairlines as List<dynamic>;
    matches.addAll(hairlines.where((hairline) => hairline.markId == 'file'));
  }
  expect(matches, hasLength(1));
  return matches.single;
}

Map<String, dynamic> _edge(
  String id,
  String sourceId,
  String targetId,
  String type,
  String origin,
  String state,
) {
  return {
    'id': id,
    'source_id': sourceId,
    'target_id': targetId,
    'type': type,
    'origin': origin,
    'state': state,
    'metadata': {},
    'created_at': '2026-01-01T00:00:00Z',
    'updated_at': '2026-01-01T00:00:00Z',
  };
}
