import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/graph/graph_workspace_controller.dart';
import 'package:personal_secretary/graph/graph_workspace_screen.dart';
import 'package:personal_secretary/graph/people_landscape.dart';
import 'package:personal_secretary/graph/unanchored_shelf_cue.dart';

import 'graph_test_harness.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('shelf bounds follow the real unanchored markers', () {
    const overview = PeopleLandscapeOverview(
      usable: true,
      positions: {
        'bea': Offset(1000, 10),
        'cio': Offset(1000, 74),
      },
      anchoredPersonIds: ['ada'],
      unanchoredPersonIds: ['bea', 'cio'],
      unresolvedPersonIds: [],
      taskBounds: null,
    );
    expect(
      unanchoredShelfWorldBounds(overview),
      Rect.fromLTWH(1000, 10, kPeopleLandscapeOverviewCardWidth, 64 + kPeopleLandscapeOverviewCardHeight),
    );
    expect(
      unanchoredShelfWorldBounds(
        const PeopleLandscapeOverview(
          usable: true,
          positions: {},
          anchoredPersonIds: ['ada'],
          unanchoredPersonIds: [],
          unresolvedPersonIds: [],
          taskBounds: null,
        ),
      ),
      isNull,
    );
  });

  test('cue stays hidden while the shelf intersects the viewport', () {
    expect(
      placeUnanchoredShelfCue(
        shelfViewport: const Rect.fromLTWH(20, 20, 128, 56),
        viewportSize: const Size(400, 300),
        count: 2,
      ),
      isNull,
    );
  });

  test('cue uses the near horizontal edge and stays inside the viewport', () {
    final right = placeUnanchoredShelfCue(
      shelfViewport: const Rect.fromLTWH(500, 30, 128, 56),
      viewportSize: const Size(400, 300),
      count: 2,
    )!;
    expect(right.onLeft, isFalse);
    expect(right.count, 2);
    expect(right.top, closeTo(30 + 28 - kUnanchoredShelfCueHeight / 2, 0.01));

    final left = placeUnanchoredShelfCue(
      shelfViewport: const Rect.fromLTWH(-180, 40, 128, 56),
      viewportSize: const Size(400, 300),
      count: 1,
    )!;
    expect(left.onLeft, isTrue);

    final clamped = placeUnanchoredShelfCue(
      shelfViewport: const Rect.fromLTWH(500, 1000, 128, 56),
      viewportSize: const Size(200, 100),
      count: 3,
    )!;
    expect(clamped.onLeft, isFalse);
    expect(clamped.top, 100 - kUnanchoredShelfCueHeight);
  });

  test('pan keeps scale and centers the shelf', () {
    final current = Matrix4.identity()..scaleByDouble(2, 2, 1, 1);
    const world = Rect.fromLTWH(500, 40, 128, 56);
    final next = panToCenterWorldRect(
      current: current,
      world: world,
      paintOrigin: Offset.zero,
      canvasPadding: 0,
      viewportSize: const Size(200, 100),
    );
    expect(next.getMaxScaleOnAxis(), closeTo(2, 0.0001));
    expect(
      MatrixUtils.transformPoint(next, world.center),
      offsetMoreOrLessEquals(const Offset(100, 50), epsilon: 0.01),
    );
  });

  testWidgets('cue is absent while the real shelf is visible and when nobody is unanchored', (
    tester,
  ) async {
    final harness = await _pump(tester, _people(unanchored: const ['person-bea', 'person-cio']));
    expect(find.byKey(const ValueKey('unanchored-shelf-cue')), findsNothing);
    expect(_overlapsViewer(tester, 'person-bea'), isTrue);

    await tester.pumpWidget(const SizedBox.shrink());
    await _pump(tester, _people(unanchored: const []));
    _moveShelf(tester, toLeft: false, ids: const ['person-ada']);
    await tester.pump();
    expect(find.byKey(const ValueKey('unanchored-shelf-cue')), findsNothing);
    expect(harness.graph.mode, GraphWorkspaceMode.people);
  });

  testWidgets('offscreen shelf cue pans back without changing scale or selection', (tester) async {
    final harness = await _pump(tester, _people(unanchored: const ['person-bea', 'person-cio']));
    final centers = Map<String, Offset>.from(harness.graph.canonicalTaskCenters);

    _moveShelf(tester, toLeft: false, ids: const ['person-bea', 'person-cio']);
    await tester.pump();

    expect(
      find.descendant(
        of: find.byType(InteractiveViewer),
        matching: find.byKey(const ValueKey('unanchored-shelf-cue')),
      ),
      findsNothing,
    );
    final tab = tester.widget<Positioned>(
      find.ancestor(
        of: find.byKey(const ValueKey('unanchored-shelf-cue')),
        matching: find.byType(Positioned),
      ).first,
    );
    expect(tab.right, 0);
    expect(tab.left, isNull);
    expect(find.byTooltip('Люди без привязки к задачам · 2'), findsOneWidget);
    expect(tester.widget<Text>(find.byKey(const ValueKey('unanchored-shelf-cue-count'))).data, '2');

    final scale = _scale(tester);
    expect(harness.graph.selectedObjectId, isNull);
    await tester.tap(find.byKey(const ValueKey('unanchored-shelf-cue')));
    await tester.pump();

    expect(_scale(tester), closeTo(scale, 0.0001));
    expect(harness.graph.selectedObjectId, isNull);
    expect(harness.graph.canonicalTaskCenters, centers);
    expect(find.byKey(const ValueKey('unanchored-shelf-cue')), findsNothing);
    expect(_overlapsViewer(tester, 'person-bea'), isTrue);
    expect(_overlapsViewer(tester, 'person-cio'), isTrue);
  });

  testWidgets('cue moves to the left edge when the shelf is left of the viewport', (tester) async {
    await _pump(tester, _people(unanchored: const ['person-bea']));
    _moveShelf(tester, toLeft: true, ids: const ['person-bea']);
    await tester.pump();
    final tab = tester.widget<Positioned>(
      find.ancestor(
        of: find.byKey(const ValueKey('unanchored-shelf-cue')),
        matching: find.byType(Positioned),
      ).first,
    );
    expect(tab.left, 0);
    expect(tab.right, isNull);
    expect(find.byTooltip('Люди без привязки к задачам · 1'), findsOneWidget);
  });

  testWidgets('manual fit shows the real shelf and the cue is not part of the camera child', (
    tester,
  ) async {
    await _pump(tester, _people(unanchored: const ['person-bea']));
    _moveShelf(tester, toLeft: false, ids: const ['person-bea']);
    await tester.pump();
    expect(find.byKey(const ValueKey('unanchored-shelf-cue')), findsOneWidget);
    expect(
      find.descendant(
        of: find.byType(InteractiveViewer),
        matching: find.byKey(const ValueKey('unanchored-shelf-cue')),
      ),
      findsNothing,
    );

    await tester.tap(find.byTooltip('Уместить граф'));
    await tester.pump();
    expect(find.byKey(const ValueKey('unanchored-shelf-cue')), findsNothing);
    expect(_overlapsViewer(tester, 'person-bea'), isTrue);
  });

  testWidgets('cue is absent in Tasks mode, rooted People mode, and the fallback grid', (
    tester,
  ) async {
    final harness = await _pump(tester, _people(unanchored: const ['person-bea']));
    _moveShelf(tester, toLeft: false, ids: const ['person-bea']);
    await tester.pump();
    expect(find.byKey(const ValueKey('unanchored-shelf-cue')), findsOneWidget);

    await harness.graph.setMode(GraphWorkspaceMode.tasks);
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('unanchored-shelf-cue')), findsNothing);

    await harness.graph.setMode(GraphWorkspaceMode.people);
    await tester.pumpAndSettle();
    await harness.graph.reRoot('person-ada');
    await tester.pumpAndSettle();
    expect(harness.graph.rootId, 'person-ada');
    expect(find.byKey(const ValueKey('unanchored-shelf-cue')), findsNothing);

    await tester.pumpWidget(const SizedBox.shrink());
    await _pump(tester, _people(unanchored: const ['person-bea']), layoutUsable: false);
    expect(find.byKey(const ValueKey('unanchored-shelf-cue')), findsNothing);
  });
}

double _scale(WidgetTester tester) {
  return tester
      .widget<InteractiveViewer>(find.byType(InteractiveViewer))
      .transformationController!
      .value
      .getMaxScaleOnAxis();
}

bool _overlapsViewer(WidgetTester tester, String id) {
  final viewer = tester.getRect(find.byType(InteractiveViewer));
  final node = tester.getRect(find.byKey(Key('graph_node_$id')));
  return viewer.overlaps(node);
}

void _moveShelf(
  WidgetTester tester, {
  required bool toLeft,
  required List<String> ids,
}) {
  final viewer = tester.widget<InteractiveViewer>(find.byType(InteractiveViewer));
  final controller = viewer.transformationController!;
  final scale = controller.value.getMaxScaleOnAxis();
  final viewport = tester.getSize(find.byType(InteractiveViewer));
  Rect? shelf;
  for (final id in ids) {
    final positioned = tester.widget<Positioned>(
      find.ancestor(
        of: find.byKey(Key('graph_node_$id')),
        matching: find.byType(Positioned),
      ).first,
    );
    final rect = Offset(positioned.left!, positioned.top!) & tester.getSize(find.byKey(Key('graph_node_$id')));
    shelf = shelf == null ? rect : shelf.expandToInclude(rect);
  }
  final bounds = shelf!;
  final tx = toLeft ? -4 - scale * bounds.right : viewport.width + 4 - scale * bounds.left;
  final ty = viewport.height / 2 - scale * bounds.center.dy;
  controller.value = Matrix4.identity()
    ..translateByDouble(tx, ty, 0, 1)
    ..scaleByDouble(scale, scale, 1, 1);
}

Future<GraphTestHarness> _pump(
  WidgetTester tester,
  Map<String, dynamic> overview, {
  bool layoutUsable = true,
}) async {
  tester.view.physicalSize = const Size(1400, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final harness = GraphTestHarness(
    MockClient((request) async {
      if (request.method == 'GET' && request.url.path == '/graph/task-layout') {
        if (!layoutUsable) {
          return http.Response('missing', 404);
        }
        final tasks = (overview['landscape_tasks'] as List?) ?? const [];
        return jsonUtf8Response({
          'topology_revision': 1,
          'snapshot_revision': 1,
          'algorithm_version': 'task-map-v2.2',
          'usable': true,
          'centers': [
            for (var index = 0; index < tasks.length; index++)
              {
                'task_id': (tasks[index] as Map)['id'],
                'world_x': 500.0 + index * 800,
                'world_y': 240.0,
              },
          ],
        });
      }
      if (request.url.path == '/graph/workspace') {
        return jsonUtf8Response(
          graphWorkspaceJson(
            nodes: [graphObjectJson(id: 'task-a', title: 'Скрытая задача')],
          ),
        );
      }
      if (request.url.path == '/graph/people-workspace') {
        return jsonUtf8Response(overview);
      }
      if (request.url.path == '/search/facets') {
        return jsonUtf8Response({'kinds': [], 'providers': []});
      }
      return http.Response('not found', 404);
    }),
  );
  harness.configure();
  await harness.graph.setMode(GraphWorkspaceMode.people);
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: GraphWorkspaceScreen(
          controller: harness.graph,
          apiClient: harness.auth.apiClient,
          authController: harness.auth,
          captureController: harness.capture,
          assistantController: harness.assistant,
          onAskSecretary: (_) {},
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
  return harness;
}

Map<String, dynamic> _people({required List<String> unanchored}) {
  const titles = {
    'person-ada': 'Ada',
    'person-bea': 'Bea',
    'person-cio': 'Cio',
  };
  final people = [
    {
      'person_id': 'person-ada',
      'title': 'Ada',
      'landscape_task_ids': ['task-a'],
      'landscape_task_ids_complete': true,
    },
    for (final id in unanchored)
      {
        'person_id': id,
        'title': titles[id],
        'landscape_task_ids': <String>[],
        'landscape_task_ids_complete': true,
      },
  ];
  final body = graphWorkspaceJson(
    nodes: [
      for (final person in people)
        graphObjectJson(
          id: person['person_id'] as String,
          title: person['title'] as String,
          kind: 'person',
        ),
    ],
  );
  body['seed_ids'] = [for (final person in people) person['person_id']];
  body['people'] = people;
  body['landscape_tasks'] = [graphObjectJson(id: 'task-a', title: 'Скрытая задача')];
  body['landscape_task_edges'] = <Map<String, dynamic>>[];
  body['landscape_task_context_complete'] = true;
  return body;
}
