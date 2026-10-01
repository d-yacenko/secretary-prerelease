import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets('confirmed agent relation is rejected through the decision endpoint', (tester) async {
    tester.view.physicalSize = const Size(1280, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final calls = <String>[];
    var workspaceReads = 0;
    final harness = GraphTestHarness(
      MockClient((request) async {
        calls.add('${request.method} ${request.url.path}');
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
        if (request.url.path == '/objects/publication/neighbors') {
          return jsonUtf8Response({'object_id': 'publication', 'neighbors': []});
        }
        if (request.url.path == '/graph/workspace') {
          workspaceReads += 1;
          final includeEdge = workspaceReads == 1;
          return jsonUtf8Response(
            graphWorkspaceJson(
              nodes: [
                graphObjectJson(id: 'publication', title: 'Publication'),
                graphObjectJson(id: 'other', title: 'Other task'),
              ],
              edges: includeEdge
                  ? [
                      _edge(
                        id: 'edge-agent',
                        sourceId: 'other',
                        targetId: 'publication',
                        type: 'depends_on',
                        origin: 'agent',
                        state: 'confirmed',
                      ),
                    ]
                  : const [],
            ),
          );
        }
        if (request.method == 'POST' && request.url.path == '/relations/edge-agent/decision') {
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['decision'], 'reject');
          return jsonUtf8Response({
            'edge': _edge(
              id: 'edge-agent',
              sourceId: 'other',
              targetId: 'publication',
              type: 'depends_on',
              origin: 'agent',
              state: 'rejected',
            ),
          });
        }
        return jsonUtf8Response({}, statusCode: 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);
    await tester.tap(find.text('Publication'));
    await tester.pumpAndSettle();

    expect(find.byTooltip('Удалить связь'), findsOneWidget);
    await tester.tap(find.byTooltip('Удалить связь'));
    await tester.pumpAndSettle();
    expect(find.text('Other task —Зависит от→ Publication'), findsOneWidget);

    await tester.tap(find.text('Удалить'));
    await tester.pumpAndSettle();

    expect(calls.where((call) => call == 'DELETE /relations/edge-agent'), isEmpty);
    expect(calls.where((call) => call == 'POST /relations/edge-agent/decision'), hasLength(1));
    expect(workspaceReads, greaterThan(1));
    expect(harness.graph.edges.where((edge) => edge.id == 'edge-agent'), isEmpty);
    expect(find.byTooltip('Удалить связь'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('user relation removal still deletes the edge and keeps the objects', (tester) async {
    tester.view.physicalSize = const Size(1280, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final calls = <String>[];
    final harness = GraphTestHarness(
      MockClient((request) async {
        calls.add('${request.method} ${request.url.path}');
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
          return jsonUtf8Response({'object_id': 'task-a', 'neighbors': []});
        }
        if (request.method == 'DELETE' && request.url.path == '/relations/edge-user') {
          return http.Response('', 204);
        }
        if (request.url.path == '/graph/workspace') {
          return jsonUtf8Response(
            graphWorkspaceJson(
              nodes: [
                graphObjectJson(id: 'task-a', title: 'Task A'),
                graphObjectJson(id: 'note-b', title: 'Note B', kind: 'note'),
              ],
              edges: [
                _edge(
                  id: 'edge-user',
                  sourceId: 'task-a',
                  targetId: 'note-b',
                  type: 'references',
                  origin: 'user',
                  state: 'confirmed',
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
    await tester.tap(find.text('Task A'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Удалить связь'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Удалить'));
    await tester.pumpAndSettle();

    expect(calls.where((call) => call == 'DELETE /relations/edge-user'), hasLength(1));
    expect(calls.where((call) => call.contains('/decision')), isEmpty);
    expect(harness.graph.edges, isEmpty);
    expect(find.text('Task A'), findsWidgets);
    expect(find.text('Note B'), findsWidgets);
  });

  testWidgets('source and protected relations have no generic remove control', (tester) async {
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
        if (request.url.path == '/objects/task-a/neighbors') {
          return jsonUtf8Response({'object_id': 'task-a', 'neighbors': []});
        }
        if (request.url.path == '/graph/workspace') {
          return jsonUtf8Response(
            graphWorkspaceJson(
              nodes: [
                graphObjectJson(id: 'task-a', title: 'Task A'),
                graphObjectJson(id: 'note-b', title: 'Note B', kind: 'note'),
                graphObjectJson(id: 'folder', title: 'Folder', kind: 'note'),
              ],
              edges: [
                _edge(
                  id: 'edge-source',
                  sourceId: 'task-a',
                  targetId: 'note-b',
                  type: 'references',
                  origin: 'source',
                  state: 'observed',
                ),
                _edge(
                  id: 'edge-protected',
                  sourceId: 'task-a',
                  targetId: 'folder',
                  type: 'contains',
                  origin: 'agent',
                  state: 'confirmed',
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
    await tester.tap(find.text('Task A'));
    await tester.pumpAndSettle();
    expect(find.byTooltip('Удалить связь'), findsNothing);
  });

  testWidgets('proposed pdf endpoint is on the canvas without an off-context cue', (tester) async {
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
        if (request.url.path == '/objects/publication/neighbors') {
          return jsonUtf8Response({
            'object_id': 'publication',
            'neighbors': [
              {
                'object': graphObjectJson(
                  id: 'pdf',
                  title: 'Program_DYSC.pdf',
                  kind: 'note',
                ),
                'edge': _edge(
                  id: 'edge-pdf',
                  sourceId: 'publication',
                  targetId: 'pdf',
                  type: 'references',
                  origin: 'agent',
                  state: 'proposed',
                ),
                'direction': 'outgoing',
              },
            ],
          });
        }
        if (request.url.path == '/graph/workspace') {
          return jsonUtf8Response(
            graphWorkspaceJson(
              nodes: [
                graphObjectJson(id: 'publication', title: 'Publication'),
                graphObjectJson(id: 'pdf', title: 'Program_DYSC.pdf', kind: 'note'),
              ],
              edges: [
                _edge(
                  id: 'edge-pdf',
                  sourceId: 'publication',
                  targetId: 'pdf',
                  type: 'references',
                  origin: 'agent',
                  state: 'proposed',
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

    expect(find.text('Publication'), findsWidgets);
    expect(
      find.byKey(const ValueKey('hybrid-glyph-pdf')).evaluate().isNotEmpty ||
          find.text('Program_DYSC.pdf').evaluate().isNotEmpty,
      isTrue,
    );
    expect(
      harness.graph.edges.singleWhere((edge) => edge.id == 'edge-pdf').state,
      'proposed',
    );
    expect(_canvasShowsProposedPdf(tester), isTrue);

    await tester.tap(find.text('Publication'));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('graph-relation-proposed-edge-pdf')), findsOneWidget);
    expect(find.textContaining('Program_DYSC.pdf'), findsWidgets);
    expect(find.byTooltip('Подтвердить'), findsOneWidget);
    expect(find.byTooltip('Отклонить'), findsOneWidget);
    expect(find.textContaining('вне текущей области'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}

bool _canvasShowsProposedPdf(WidgetTester tester) {
  if (_canvasPaintsProposedEdge(tester, 'edge-pdf')) {
    return true;
  }
  for (final paint in tester.widgetList<CustomPaint>(find.byType(CustomPaint))) {
    final painter = paint.painter;
    if (painter == null || painter.runtimeType.toString() != 'HybridHairlinePainter') {
      continue;
    }
    final hairlines = (painter as dynamic).hairlines as List<dynamic>;
    if (hairlines.any((hairline) => hairline.proposed == true && hairline.markId == 'pdf')) {
      return true;
    }
  }
  return false;
}

bool _canvasPaintsProposedEdge(WidgetTester tester, String edgeId) {
  for (final paint in tester.widgetList<CustomPaint>(find.byType(CustomPaint))) {
    final painter = paint.painter;
    if (painter == null || painter.runtimeType.toString() != '_GraphEdgePainter') {
      continue;
    }
    final edges = (painter as dynamic).edges as List<dynamic>;
    if (edges.any((edge) => edge.id == edgeId && edge.state == 'proposed')) {
      return true;
    }
  }
  return false;
}

Map<String, dynamic> _edge({
  required String id,
  required String sourceId,
  required String targetId,
  required String type,
  required String origin,
  required String state,
}) {
  return {
    'id': id,
    'source_id': sourceId,
    'target_id': targetId,
    'type': type,
    'origin': origin,
    'state': state,
    'confidence': 0.9,
    'metadata': <String, dynamic>{},
    'created_at': '2026-01-01T00:00:00Z',
    'updated_at': '2026-01-01T00:00:00Z',
  };
}
