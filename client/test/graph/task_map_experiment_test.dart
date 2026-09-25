import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/graph/graph_workspace_screen.dart';
import 'package:personal_secretary/graph/task_map.dart';
import 'package:personal_secretary/graph/task_map_view.dart';
import 'package:personal_secretary/graph/task_profile_section.dart';

import 'graph_test_harness.dart';

SecretaryObject _object({
  required String id,
  required String title,
  String kind = 'task',
  String? dueAt,
  String? operationalState,
}) {
  final json = graphObjectJson(
    id: id,
    title: title,
    kind: kind,
    dueAt: dueAt,
  );
  if (operationalState != null) {
    json['metadata'] = {'operational_state': operationalState};
  }
  return SecretaryObject.fromJson(json);
}

SecretaryEdge _edge(String sourceId, String targetId) {
  return SecretaryEdge.fromJson({
    'id': '$sourceId-$targetId',
    'source_id': sourceId,
    'target_id': targetId,
    'type': 'depends_on',
    'origin': 'user',
    'state': 'confirmed',
    'metadata': {},
    'created_at': '2026-01-01T00:00:00Z',
    'updated_at': '2026-01-01T00:00:00Z',
  });
}

List<SecretaryObject> _chain(int count, {String titlePrefix = 'Задача'}) {
  return [
    for (var index = 0; index < count; index++)
      _object(id: 'n$index', title: '$titlePrefix $index с длинным названием'),
  ];
}

List<SecretaryEdge> _chainEdges(int count) {
  return [
    for (var index = 0; index < count - 1; index++) _edge('n$index', 'n${index + 1}'),
  ];
}

void main() {
  test('task skeleton hides context and context toggle is reversible', () {
    final nodes = [
      _object(id: 'task-a', title: 'Задача А'),
      _object(id: 'task-b', title: 'Задача Б'),
      _object(id: 'email-1', title: 'Письмо', kind: 'email'),
      _object(id: 'file-1', title: 'Файл', kind: 'file'),
    ];
    final edges = [
      _edge('task-a', 'task-b'),
      _edge('task-a', 'email-1'),
      _edge('task-b', 'file-1'),
    ];

    final hidden = projectTaskMap(
      nodes: nodes,
      edges: edges,
      selectedObjectId: 'task-a',
      showContext: false,
    );
    expect(hidden.nodes.map((node) => node.id), ['task-a', 'task-b']);
    expect(hidden.edges.map((edge) => edge.id), ['task-a-task-b']);

    final shown = projectTaskMap(
      nodes: nodes,
      edges: edges,
      selectedObjectId: 'task-a',
      showContext: true,
    );
    expect(shown.nodes.map((node) => node.id), ['task-a', 'task-b', 'email-1']);
    expect(shown.edges.map((edge) => edge.id), ['task-a-task-b', 'task-a-email-1']);
    expect(shown.nodes.any((node) => node.id == 'file-1'), isFalse);

    final restored = projectTaskMap(
      nodes: nodes,
      edges: edges,
      selectedObjectId: 'task-a',
      showContext: false,
    );
    expect(restored.nodes.map((node) => node.id), hidden.nodes.map((node) => node.id));
    expect(restored.edges.map((edge) => edge.id), hidden.edges.map((edge) => edge.id));
  });

  test('semantic zoom presentation', () {
    final task = _object(
      id: 'task-a',
      title: 'Подготовить длинный отчёт для команды',
      dueAt: '2026-09-01T10:00:00Z',
      operationalState: 'blocked',
    );
    final email = _object(
      id: 'email-1',
      title: 'Письмо с очень длинной темой обсуждения',
      kind: 'email',
    );

    final near = presentTaskMapNode(task, TaskMapDensity.near);
    expect(near.title, task.title);
    expect(near.cue, 'Заблокировано');
    expect(near.dueLabel, contains('Срок:'));

    final middle = presentTaskMapNode(task, TaskMapDensity.middle);
    expect(middle.title, task.title);
    expect(middle.cue, contains('Срок:'));
    expect(middle.dueLabel, isNull);

    final far = presentTaskMapNode(task, TaskMapDensity.far);
    expect(far.title.length, lessThan(task.title.length));
    expect(far.cue, isNull);
    expect(far.dueLabel, isNull);

    final contextFar = presentTaskMapNode(email, TaskMapDensity.far);
    final contextNear = presentTaskMapNode(email, TaskMapDensity.near);
    expect(contextFar.title.length, lessThan(far.title.length));
    expect(contextNear.cue, 'Письмо');
    expect(contextNear.dueLabel, isNull);
    expect(contextNear.title.length, lessThan(email.title.length));
  });

  test('layout selector algorithms stay off the workspace objects', () {
    final nodes = _chain(4);
    final edges = _chainEdges(4);
    final before = nodes.map((node) => '${node.id}:${node.title}').toList();
    for (final layout in TaskMapLayout.values) {
      final result = layoutTaskMap(layout: layout, nodes: nodes, edges: edges);
      expect(result.completed, isTrue, reason: layout.name);
      expect(result.positions.keys, nodes.map((node) => node.id));
    }
    expect(nodes.map((node) => '${node.id}:${node.title}').toList(), before);
    expect(edges.map((edge) => edge.id).toList(), ['n0-n1', 'n1-n2', 'n2-n3']);
  });

  test('mind map reports a cycle without dropping nodes from the caller', () {
    final nodes = _chain(2);
    final edges = [_edge('n0', 'n1'), _edge('n1', 'n0')];
    final result = layoutTaskMap(
      layout: TaskMapLayout.mindmap,
      nodes: nodes,
      edges: edges,
    );
    expect(result.completed, isFalse);
    expect(result.error, contains('Cyclic'));
    expect(nodes, hasLength(2));
  });

  for (final count in [20, 50, 100]) {
    for (final layout in TaskMapLayout.values) {
      test('$layout lays out $count nodes', () {
        final result = layoutTaskMap(
          layout: layout,
          nodes: _chain(count),
          edges: _chainEdges(count),
        );
        expect(result.completed, isTrue, reason: result.error);
        expect(result.positions, hasLength(count));
      });
    }
  }

  test('stability probe records movement for add, context, and root', () {
    for (final count in [20, 50, 100]) {
      final baseNodes = _chain(count);
      final baseEdges = _chainEdges(count);
      final addedNodes = _chain(count + 1);
      final addedEdges = _chainEdges(count + 1);
      final contextNodes = [
        ...baseNodes,
        _object(id: 'email', title: 'Контекст', kind: 'email'),
      ];
      final contextEdges = [...baseEdges, _edge('n0', 'email')];
      final reversed = [
        for (final edge in baseEdges) _edge(edge.targetId, edge.sourceId),
      ];

      for (final layout in TaskMapLayout.values) {
        final base = layoutTaskMap(layout: layout, nodes: baseNodes, edges: baseEdges);
        final added = layoutTaskMap(layout: layout, nodes: addedNodes, edges: addedEdges);
        final context = layoutTaskMap(
          layout: layout,
          nodes: contextNodes,
          edges: contextEdges,
        );
        final reroot = layoutTaskMap(layout: layout, nodes: baseNodes, edges: reversed);
        expect(base.completed, isTrue, reason: '${layout.name} $count');
        expect(added.completed, isTrue, reason: '${layout.name} $count');
        expect(context.completed, isTrue, reason: '${layout.name} $count');
        expect(reroot.completed, isTrue, reason: '${layout.name} $count');
        debugPrint(
          '${layout.name} n=$count '
          'add=${taskMapMovedNodeCount(base.positions, added.positions)}/$count '
          'context=${taskMapMovedNodeCount(base.positions, context.positions)}/$count '
          'root=${taskMapMovedNodeCount(base.positions, reroot.positions)}/$count',
        );
      }
    }
  });

  testWidgets('node cards follow semantic zoom', (tester) async {
    final task = _object(
      id: 'task-a',
      title: 'Подготовить длинный отчёт',
      dueAt: '2026-09-01T10:00:00Z',
    );
    Future<void> pumpDensity(TaskMapDensity density) {
      return tester.pumpWidget(
        MaterialApp(
          home: TaskMapNodeCard(
            object: task,
            density: density,
            selected: true,
            dimmed: false,
            onTap: () {},
          ),
        ),
      );
    }

    await pumpDensity(TaskMapDensity.near);
    expect(find.byKey(const ValueKey('task-map-due')), findsOneWidget);
    expect(find.byKey(const ValueKey('task-map-cue')), findsOneWidget);
    expect(find.text('Подготовить длинный отчёт'), findsOneWidget);

    await pumpDensity(TaskMapDensity.middle);
    expect(find.byKey(const ValueKey('task-map-due')), findsNothing);
    expect(find.byKey(const ValueKey('task-map-cue')), findsOneWidget);

    await pumpDensity(TaskMapDensity.far);
    expect(find.byKey(const ValueKey('task-map-due')), findsNothing);
    expect(find.byKey(const ValueKey('task-map-cue')), findsNothing);
    expect(find.text('Подготовить длинный отчёт'), findsNothing);
  });

  testWidgets('experimental map uses workspace data and keeps the current default', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = GraphTestHarness(_workspaceMock());
    harness.configure();
    await openGraph(tester, harness);

    expect(find.byType(GraphWorkspaceScreen), findsOneWidget);
    expect(find.text('Текущий'), findsOneWidget);
    expect(find.text('Экспериментальная карта'), findsNothing);
    expect(find.text('Задача А'), findsOneWidget);
    expect(find.text('Письмо контекста'), findsOneWidget);

    await tester.tap(find.text('Эксперимент'));
    await tester.pumpAndSettle();

    expect(find.text('Экспериментальная карта'), findsOneWidget);
    expect(find.text('Mind map'), findsOneWidget);
    expect(find.text('Радиальная'), findsOneWidget);
    expect(find.text('Силовая'), findsOneWidget);
    expect(find.byKey(const ValueKey('task-map-node-task-a')), findsOneWidget);
    expect(find.byKey(const ValueKey('task-map-node-email-1')), findsNothing);

    final nodeIds = harness.graph.nodes.map((node) => node.id).toList();
    final edgeIds = harness.graph.edges.map((edge) => edge.id).toList();
    await tester.tap(find.text('Радиальная'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Силовая'));
    await tester.pumpAndSettle();
    expect(harness.graph.nodes.map((node) => node.id).toList(), nodeIds);
    expect(harness.graph.edges.map((edge) => edge.id).toList(), edgeIds);

    await tester.tap(find.byKey(const ValueKey('task-map-node-task-a')));
    await tester.pump();
    expect(harness.graph.selectedObjectId, 'task-a');
    expect(find.text('Спросить секретаря'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.byType(TaskProfileSection),
      200,
      scrollable: find
          .ancestor(
            of: find.text('Спросить секретаря'),
            matching: find.byType(Scrollable),
          )
          .first,
    );
    expect(find.byType(TaskProfileSection), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('task-map-context-toggle')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('task-map-node-email-1')), findsOneWidget);
    expect(find.byKey(const ValueKey('task-map-node-file-1')), findsNothing);

    await tester.tap(find.byKey(const ValueKey('task-map-context-toggle')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('task-map-node-email-1')), findsNothing);

    await tester.tap(find.text('Текущий'));
    await tester.pumpAndSettle();
    expect(find.text('Экспериментальная карта'), findsNothing);
    expect(find.text('Письмо контекста'), findsWidgets);
    expect(harness.graph.rootId, isNull);
  });

  testWidgets('people mode keeps the current renderer', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = GraphTestHarness(_workspaceMock());
    harness.configure();
    await openGraph(tester, harness);

    await tester.tap(find.text('Эксперимент'));
    await tester.pumpAndSettle();
    expect(find.text('Экспериментальная карта'), findsOneWidget);

    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();

    expect(harness.graph.mode.name, 'people');
    expect(find.text('Эксперимент'), findsNothing);
    expect(find.text('Экспериментальная карта'), findsNothing);
    expect(find.text('Анна'), findsOneWidget);
  });

  testWidgets('cycle fallback keeps the tasks visible', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = GraphTestHarness(_cycleMock());
    harness.configure();
    await openGraph(tester, harness);
    await tester.tap(find.text('Эксперимент'));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('task-map-layout-fallback')), findsOneWidget);
    expect(find.text('Цикл А'), findsWidgets);
    expect(find.text('Цикл Б'), findsWidgets);
    expect(harness.graph.nodes, hasLength(2));
  });

  testWidgets('20 node experiment widget lays out', (tester) async {
    tester.view.physicalSize = const Size(900, 700);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TaskMapExperiment(
            nodes: _chain(20),
            edges: _chainEdges(20),
            selectedObjectId: null,
            layout: TaskMapLayout.radial,
            showContext: false,
            onSelect: (_) {},
          ),
        ),
      ),
    );
    await tester.pump();
    expect(tester.takeException(), isNull);
    expect(find.byKey(const ValueKey('task-map-node-n0')), findsOneWidget);
    expect(find.byKey(const ValueKey('task-map-node-n19')), findsOneWidget);
  });
}

MockClient _workspaceMock() {
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
    if (request.url.path == '/search/facets') {
      return jsonUtf8Response({'kinds': [], 'providers': []});
    }
    if (request.url.path == '/graph/people-workspace') {
      return jsonUtf8Response(
        graphWorkspaceJson(
          nodes: [graphObjectJson(id: 'person-1', title: 'Анна', kind: 'person')],
        ),
      );
    }
    if (request.url.path == '/graph/workspace') {
      return jsonUtf8Response(
        graphWorkspaceJson(
          nodes: [
            graphObjectJson(id: 'task-a', title: 'Задача А'),
            graphObjectJson(id: 'task-b', title: 'Задача Б'),
            graphObjectJson(id: 'email-1', title: 'Письмо контекста', kind: 'email'),
            graphObjectJson(id: 'file-1', title: 'Чужой файл', kind: 'file'),
          ],
          edges: [
            {
              'id': 'edge-tasks',
              'source_id': 'task-a',
              'target_id': 'task-b',
              'type': 'depends_on',
              'origin': 'user',
              'state': 'confirmed',
              'metadata': {},
              'created_at': '2026-01-01T00:00:00Z',
              'updated_at': '2026-01-01T00:00:00Z',
            },
            {
              'id': 'edge-email',
              'source_id': 'task-a',
              'target_id': 'email-1',
              'type': 'references',
              'origin': 'user',
              'state': 'confirmed',
              'metadata': {},
              'created_at': '2026-01-01T00:00:00Z',
              'updated_at': '2026-01-01T00:00:00Z',
            },
            {
              'id': 'edge-file',
              'source_id': 'task-b',
              'target_id': 'file-1',
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
    return http.Response('{}', 404);
  });
}

MockClient _cycleMock() {
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
    if (request.url.path == '/search/facets') {
      return jsonUtf8Response({'kinds': [], 'providers': []});
    }
    if (request.url.path == '/graph/workspace') {
      return jsonUtf8Response(
        graphWorkspaceJson(
          nodes: [
            graphObjectJson(id: 'cycle-a', title: 'Цикл А'),
            graphObjectJson(id: 'cycle-b', title: 'Цикл Б'),
          ],
          edges: [
            {
              'id': 'ab',
              'source_id': 'cycle-a',
              'target_id': 'cycle-b',
              'type': 'depends_on',
              'origin': 'user',
              'state': 'confirmed',
              'metadata': {},
              'created_at': '2026-01-01T00:00:00Z',
              'updated_at': '2026-01-01T00:00:00Z',
            },
            {
              'id': 'ba',
              'source_id': 'cycle-b',
              'target_id': 'cycle-a',
              'type': 'depends_on',
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
    return http.Response('{}', 404);
  });
}
