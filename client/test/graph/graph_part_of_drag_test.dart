import 'dart:async';
import 'dart:convert';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/graph/task_part_of_connect.dart';
import 'package:vector_math/vector_math_64.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets('task handles appear when selected and stay off other nodes', (
    tester,
  ) async {
    final harness = _harness();
    harness.configure();
    await _open(tester, harness);

    expect(find.byKey(const ValueKey('part-of-handle-A-right')), findsNothing);
    final hover = await tester.createGesture(kind: PointerDeviceKind.mouse);
    await hover.addPointer(location: _card(tester, 'B'));
    await tester.pump();
    expect(
      find.byKey(const ValueKey('part-of-handle-B-right')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('part-of-handle-note-right')),
      findsNothing,
    );
    await hover.moveTo(_card(tester, 'note'));
    await tester.pump();
    expect(find.byKey(const ValueKey('part-of-handle-B-right')), findsNothing);
    expect(
      find.byKey(const ValueKey('part-of-handle-note-right')),
      findsNothing,
    );
    await hover.removePointer();
    await tester.pump();

    harness.graph.selectObject('A');
    await tester.pump();

    expect(find.byKey(const ValueKey('part-of-handle-A-top')), findsOneWidget);
    expect(
      find.byKey(const ValueKey('part-of-handle-A-right')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('part-of-handle-A-bottom')),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('part-of-handle-A-left')), findsOneWidget);
    expect(find.byKey(const ValueKey('part-of-handle-B-right')), findsNothing);
    expect(
      find.byKey(const ValueKey('part-of-handle-note-right')),
      findsNothing,
    );
    expect(
      find.byKey(const ValueKey('part-of-handle-person-right')),
      findsNothing,
    );

    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    harness.graph.selectObject('person');
    await tester.pump();
    expect(
      find.byKey(const ValueKey('part-of-handle-person-right')),
      findsNothing,
    );
    expect(find.byKey(const ValueKey('part-of-handle-A-right')), findsNothing);
  });

  testWidgets('drag from A to B sends one part_of and drops the preview', (
    tester,
  ) async {
    final posts = <Map<String, dynamic>>[];
    final harness = _harness(posts: posts);
    harness.configure();
    await _open(tester, harness);
    harness.graph.selectObject('A');
    await tester.pump();

    final gesture = await tester.startGesture(_handle(tester, 'A'));
    await gesture.moveTo(_card(tester, 'B'));
    await tester.pump();

    expect(find.byKey(const ValueKey('part-of-drag-preview')), findsOneWidget);
    expect(
      find.byKey(const ValueKey('part-of-handle-B-right')),
      findsOneWidget,
    );
    expect(find.bySemanticsLabel('part_of drag preview'), findsOneWidget);
    final painter =
        tester
                .widget<CustomPaint>(
                  find.descendant(
                    of: find.byKey(const ValueKey('part-of-drag-preview')),
                    matching: find.byType(CustomPaint),
                  ),
                )
                .painter!
            as PartOfDragPreviewPainter;
    expect(painter.solidDirected, isTrue);
    expect(find.byKey(const ValueKey('part-of-target-B')), findsOneWidget);
    expect(posts, isEmpty);

    await gesture.up();
    await tester.pumpAndSettle();

    expect(posts, [
      {'source_id': 'A', 'target_id': 'B', 'type': 'part_of'},
    ]);
    expect(find.byKey(const ValueKey('part-of-drag-preview')), findsNothing);
    expect(
      harness.graph.edges.where(
        (edge) =>
            edge.type == 'part_of' &&
            edge.sourceId == 'A' &&
            edge.targetId == 'B',
      ),
      hasLength(1),
    );
  });

  testWidgets('the same drag works under a zoomed and panned camera', (
    tester,
  ) async {
    final posts = <Map<String, dynamic>>[];
    final harness = _harness(posts: posts);
    harness.configure();
    await _open(tester, harness);
    final viewer = tester.widget<InteractiveViewer>(
      find.byType(InteractiveViewer),
    );
    viewer.transformationController!.value = Matrix4.identity()
      ..scale(1.7)
      ..setTranslationRaw(36, 18, 0);
    await tester.pump();
    harness.graph.selectObject('A');
    await tester.pump();

    final gesture = await tester.startGesture(_handle(tester, 'A'));
    await gesture.moveTo(_card(tester, 'B'));
    await tester.pump();
    expect(find.byKey(const ValueKey('part-of-target-B')), findsOneWidget);
    final storage = viewer.transformationController!.value.storage;
    expect(storage[0], closeTo(1.7, 0.001));
    expect(storage[12], closeTo(36, 0.001));
    expect(storage[13], closeTo(18, 0.001));
    await gesture.up();
    await tester.pumpAndSettle();

    expect(posts, [
      {'source_id': 'A', 'target_id': 'B', 'type': 'part_of'},
    ]);
    expect(find.byKey(const ValueKey('part-of-drag-preview')), findsNothing);
  });

  testWidgets(
    'release on empty canvas, the source, or a non-task sends nothing',
    (tester) async {
      final posts = <Map<String, dynamic>>[];
      final harness = _harness(posts: posts);
      harness.configure();
      await _open(tester, harness);
      harness.graph.selectObject('A');
      await tester.pump();

      await _drag(tester, _handle(tester, 'A'), const Offset(12, 12));
      await _drag(tester, _handle(tester, 'A'), _card(tester, 'A'));
      await _drag(tester, _handle(tester, 'A'), _card(tester, 'note'));

      expect(posts, isEmpty);
      expect(harness.graph.edges, isEmpty);
      expect(find.byKey(const ValueKey('part-of-drag-preview')), findsNothing);
    },
  );

  testWidgets('a rejected part_of shows the error and adds no edge', (
    tester,
  ) async {
    final posts = <Map<String, dynamic>>[];
    final harness = _harness(posts: posts, reject: true);
    harness.configure();
    await _open(tester, harness);
    harness.graph.selectObject('A');
    await tester.pump();

    await _drag(tester, _handle(tester, 'A'), _card(tester, 'B'));

    expect(posts, hasLength(1));
    expect(find.text('Задача уже входит в другую задачу.'), findsOneWidget);
    expect(harness.graph.edges, isEmpty);
    expect(find.byKey(const ValueKey('part-of-drag-preview')), findsNothing);
  });

  testWidgets('an in-flight drop cannot submit a second part_of', (
    tester,
  ) async {
    final posts = <Map<String, dynamic>>[];
    final gate = Completer<http.Response>();
    final harness = _harness(posts: posts, gate: gate);
    harness.configure();
    await _open(tester, harness);
    harness.graph.selectObject('A');
    await tester.pump();

    final first = await tester.startGesture(_handle(tester, 'A'));
    await first.moveTo(_card(tester, 'B'));
    await first.up();
    await tester.pump();

    final second = await tester.startGesture(_handle(tester, 'A'));
    await second.moveTo(_card(tester, 'B'));
    await second.up();
    await tester.pump();

    expect(posts, hasLength(1));
    gate.complete(_edgeResponse('A', 'B'));
    await tester.pumpAndSettle();
    expect(posts, hasLength(1));
  });

  testWidgets('a rejected async part_of can be dragged again', (tester) async {
    final posts = <Map<String, dynamic>>[];
    final gate = Completer<http.Response>();
    final harness = _harness(posts: posts, holdFirst: gate);
    harness.configure();
    await _open(tester, harness);
    harness.graph.selectObject('A');
    await tester.pump();

    final first = await tester.startGesture(_handle(tester, 'A'));
    await first.moveTo(_card(tester, 'B'));
    await first.up();
    await tester.pump();
    expect(posts, hasLength(1));

    final blocked = await tester.startGesture(_handle(tester, 'A'));
    await blocked.moveTo(_card(tester, 'B'));
    await tester.pump();
    expect(find.byKey(const ValueKey('part-of-drag-preview')), findsNothing);
    await blocked.up();
    await tester.pump();
    expect(posts, hasLength(1));

    gate.complete(
      jsonUtf8Response({
        'detail': 'Задача уже входит в другую задачу.',
      }, statusCode: 422),
    );
    await tester.pumpAndSettle();
    expect(find.text('Задача уже входит в другую задачу.'), findsOneWidget);
    expect(harness.graph.edges, isEmpty);

    await _drag(tester, _handle(tester, 'A'), _card(tester, 'B'));
    expect(posts, hasLength(2));
    expect(posts[1], {'source_id': 'A', 'target_id': 'B', 'type': 'part_of'});
    expect(
      harness.graph.edges.where(
        (edge) =>
            edge.type == 'part_of' &&
            edge.sourceId == 'A' &&
            edge.targetId == 'B',
      ),
      hasLength(1),
    );
  });
}

Future<void> _open(WidgetTester tester, GraphTestHarness harness) async {
  tester.view.physicalSize = const Size(1280, 800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await openGraph(tester, harness);
}

Offset _handle(WidgetTester tester, String id) {
  return tester.getCenter(find.byKey(ValueKey('part-of-handle-$id-right')));
}

Offset _card(WidgetTester tester, String id) {
  return tester.getCenter(find.byKey(Key('graph_node_$id')));
}

Future<void> _drag(WidgetTester tester, Offset from, Offset to) async {
  final gesture = await tester.startGesture(from);
  await gesture.moveTo(to);
  await tester.pump();
  expect(find.byKey(const ValueKey('part-of-drag-preview')), findsOneWidget);
  await gesture.up();
  await tester.pumpAndSettle();
}

GraphTestHarness _harness({
  List<Map<String, dynamic>>? posts,
  bool reject = false,
  Completer<http.Response>? gate,
  Completer<http.Response>? holdFirst,
}) {
  var linked = false;
  var heldFirst = false;
  return GraphTestHarness(
    MockClient((request) async {
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
      if (request.url.path == '/graph/workspace' ||
          request.url.path == '/graph/people-workspace') {
        final personMode = request.url.path == '/graph/people-workspace';
        return jsonUtf8Response(
          graphWorkspaceJson(
            nodes: personMode
                ? [
                    graphObjectJson(
                      id: 'person',
                      title: 'Ольга',
                      kind: 'person',
                    ),
                  ]
                : [
                    graphObjectJson(id: 'A', title: 'Ребёнок'),
                    graphObjectJson(id: 'B', title: 'Родитель'),
                    graphObjectJson(id: 'note', title: 'Заметка', kind: 'note'),
                    graphObjectJson(
                      id: 'person',
                      title: 'Ольга',
                      kind: 'person',
                    ),
                  ],
            edges: linked
                ? [
                    {
                      'id': 'edge-part',
                      'source_id': 'A',
                      'target_id': 'B',
                      'type': 'part_of',
                      'origin': 'user',
                      'state': 'confirmed',
                      'confidence': null,
                      'metadata': {},
                      'created_at': '2026-01-01T00:00:00Z',
                      'updated_at': '2026-01-01T00:00:00Z',
                    },
                  ]
                : const [],
          ),
        );
      }
      if (request.method == 'POST' && request.url.path == '/relations') {
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        posts?.add(body);
        if (holdFirst != null && !heldFirst) {
          heldFirst = true;
          return holdFirst.future;
        }
        if (reject) {
          return jsonUtf8Response({
            'detail': 'Задача уже входит в другую задачу.',
          }, statusCode: 422);
        }
        final response = _edgeResponse(
          body['source_id'] as String,
          body['target_id'] as String,
        );
        if (gate != null) {
          linked = true;
          return gate.future;
        }
        linked = true;
        return response;
      }
      if (request.url.path == '/search/facets') {
        return jsonUtf8Response({
          'kinds': [
            {'value': 'task', 'count': 1},
          ],
          'providers': [],
        });
      }
      return jsonUtf8Response({}, statusCode: 404);
    }),
  );
}

http.Response _edgeResponse(String sourceId, String targetId) {
  return jsonUtf8Response({
    'created': true,
    'edge': {
      'id': 'edge-part',
      'source_id': sourceId,
      'target_id': targetId,
      'type': 'part_of',
      'origin': 'user',
      'state': 'confirmed',
      'confidence': null,
      'metadata': {},
      'created_at': '2026-01-01T00:00:00Z',
      'updated_at': '2026-01-01T00:00:00Z',
    },
  });
}
