import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/graph/graph_workspace_controller.dart';
import 'package:personal_secretary/graph/task_layout_world.dart';
import 'package:personal_secretary/graph/task_map_hierarchy.dart';
import 'package:personal_secretary/timezone/client_timezone_context.dart';

import 'graph_test_harness.dart';

void main() {
  test('usable matching layout is used without topology or replace', () async {
    final calls = <String>[];
    final controller = _controller(
      _layoutMock(
        calls: calls,
        layout: _snapshot(usable: true, centers: _centers()),
      ),
    );
    await controller.loadOverview();
    expect(controller.canonicalTaskCentersActive, isTrue);
    expect(controller.canonicalTaskCenters['task-a'], const Offset(100, 80));
    expect(controller.taskLayoutWarning, isNull);
    expect(calls.where((call) => call.contains('topology')), isEmpty);
    expect(calls.where((call) => call.startsWith('PUT')), isEmpty);
  });

  test('stale layout is recomputed from the complete topology and replaced', () async {
    final calls = <String>[];
    Map<String, dynamic>? putBody;
    final topology = _topology(['task-a', 'task-b']);
    final controller = _controller(
      _layoutMock(
        calls: calls,
        layout: _snapshot(usable: false, centers: const []),
        topology: topology,
        onPut: (body) => putBody = body,
      ),
    );
    await controller.loadOverview();
    expect(calls.where((call) => call == 'GET /graph/task-layout/topology'), hasLength(1));
    expect(calls.where((call) => call == 'PUT /graph/task-layout'), hasLength(1));
    final expected = taskLayoutCentersFromTopology(TaskLayoutTopology.tryParse(topology)!);
    expect(putBody!['expected_topology_revision'], 7);
    expect(putBody!['algorithm_version'], kTaskLayoutAlgorithmVersion);
    expect(putBody!['centers'], [for (final center in expected!) center.toJson()]);
    expect(controller.canonicalTaskCentersActive, isTrue);
    expect(controller.canonicalTaskCenters.keys, containsAll(['task-a', 'task-b']));
    expect(controller.taskLayoutWarning, isNull);
  });

  test('a usable task-map-v1 snapshot is replaced by task-map-v2.1', () async {
    final calls = <String>[];
    Map<String, dynamic>? putBody;
    final topology = _topology(['task-a', 'task-b']);
    final controller = _controller(
      _layoutMock(
        calls: calls,
        layout: _snapshot(
          usable: true,
          algorithmVersion: 'task-map-v1',
          centers: _centers(),
        ),
        topology: topology,
        onPut: (body) => putBody = body,
      ),
    );
    await controller.loadOverview();
    expect(calls.where((call) => call == 'GET /graph/task-layout/topology'), hasLength(1));
    expect(calls.where((call) => call == 'PUT /graph/task-layout'), hasLength(1));
    expect(putBody!['algorithm_version'], 'task-map-v2.2');
    expect((putBody!['centers'] as List).length, 2);
    expect(controller.canonicalTaskCentersActive, isTrue);
    expect(controller.taskLayoutWarning, isNull);
  });

  test('a usable task-map-v2 snapshot is replaced by task-map-v2.1', () async {
    final calls = <String>[];
    Map<String, dynamic>? putBody;
    final topology = _topology(['task-a', 'task-b']);
    final controller = _controller(
      _layoutMock(
        calls: calls,
        layout: _snapshot(
          usable: true,
          algorithmVersion: 'task-map-v2',
          centers: _centers(),
        ),
        topology: topology,
        onPut: (body) => putBody = body,
      ),
    );
    await controller.loadOverview();
    expect(calls.where((call) => call == 'GET /graph/task-layout/topology'), hasLength(1));
    expect(calls.where((call) => call == 'PUT /graph/task-layout'), hasLength(1));
    expect(putBody!['algorithm_version'], 'task-map-v2.2');
    expect((putBody!['centers'] as List).length, 2);
    expect(controller.canonicalTaskCentersActive, isTrue);
    expect(controller.taskLayoutWarning, isNull);
  });

  test('a usable task-map-v2.1.1 snapshot is replaced by task-map-v2.2', () async {
    final calls = <String>[];
    Map<String, dynamic>? putBody;
    final topology = _topology(['task-a', 'task-b']);
    final controller = _controller(
      _layoutMock(
        calls: calls,
        layout: _snapshot(
          usable: true,
          algorithmVersion: 'task-map-v2.1.1',
          centers: _centers(),
        ),
        topology: topology,
        onPut: (body) => putBody = body,
      ),
    );
    await controller.loadOverview();
    expect(calls.where((call) => call == 'GET /graph/task-layout/topology'), hasLength(1));
    expect(calls.where((call) => call == 'PUT /graph/task-layout'), hasLength(1));
    expect(putBody!['algorithm_version'], 'task-map-v2.2');
    expect((putBody!['centers'] as List).length, 2);
    expect(controller.canonicalTaskCentersActive, isTrue);
    expect(controller.taskLayoutWarning, isNull);
  });

  test('a usable task-map-v2.1 snapshot is replaced by task-map-v2.2', () async {
    final calls = <String>[];
    Map<String, dynamic>? putBody;
    final topology = _topology(['task-a', 'task-b']);
    final controller = _controller(
      _layoutMock(
        calls: calls,
        layout: _snapshot(
          usable: true,
          algorithmVersion: 'task-map-v2.1',
          centers: _centers(),
        ),
        topology: topology,
        onPut: (body) => putBody = body,
      ),
    );
    await controller.loadOverview();
    expect(calls.where((call) => call == 'GET /graph/task-layout/topology'), hasLength(1));
    expect(calls.where((call) => call == 'PUT /graph/task-layout'), hasLength(1));
    expect(putBody!['algorithm_version'], 'task-map-v2.2');
    expect((putBody!['centers'] as List).length, 2);
    expect(controller.canonicalTaskCentersActive, isTrue);
    expect(controller.taskLayoutWarning, isNull);
  });

  test('algorithm mismatch recomputes even when the snapshot is usable', () async {
    final calls = <String>[];
    final controller = _controller(
      _layoutMock(
        calls: calls,
        layout: _snapshot(
          usable: true,
          algorithmVersion: 'task-map-v0',
          centers: _centers(),
        ),
        topology: _topology(['task-a']),
      ),
    );
    await controller.loadOverview();
    expect(calls, contains('GET /graph/task-layout/topology'));
    expect(calls.where((call) => call == 'PUT /graph/task-layout'), hasLength(1));
    expect(controller.canonicalTaskCentersActive, isTrue);
  });

  test('the first stale replace is retried once', () async {
    var puts = 0;
    final calls = <String>[];
    final controller = _controller(
      _layoutMock(
        calls: calls,
        layout: _snapshot(usable: false, centers: const []),
        topology: _topology(['task-a']),
        putStatus: () {
          puts += 1;
          return puts == 1 ? 409 : 200;
        },
      ),
    );
    await controller.loadOverview();
    expect(puts, 2);
    expect(controller.canonicalTaskCentersActive, isTrue);
    expect(controller.taskLayoutWarning, isNull);
  });

  test('a second stale replace fails closed without another loop', () async {
    var puts = 0;
    final controller = _controller(
      _layoutMock(
        layout: _snapshot(usable: false, centers: const []),
        topology: _topology(['task-a']),
        putStatus: () {
          puts += 1;
          return 409;
        },
      ),
    );
    await controller.loadOverview();
    expect(puts, 2);
    expect(controller.canonicalTaskCentersActive, isFalse);
    expect(controller.canonicalTaskCenters, isEmpty);
    expect(controller.taskLayoutWarning, taskLayoutResolutionWarning);
    expect(controller.loadState, GraphWorkspaceLoadState.ready);
  });

  test('empty topology persists an empty snapshot', () async {
    Map<String, dynamic>? putBody;
    final controller = _controller(
      _layoutMock(
        layout: _snapshot(usable: false, centers: const []),
        topology: _topology(const []),
        onPut: (body) => putBody = body,
      ),
    );
    await controller.loadOverview();
    expect(putBody!['centers'], isEmpty);
    expect(controller.canonicalTaskCentersActive, isTrue);
    expect(controller.canonicalTaskCenters, isEmpty);
    expect(controller.taskLayoutWarning, isNull);
  });

  test('a partial or malformed center set is not installed', () async {
    final calls = <String>[];
    final malformed = _controller(
      _layoutMock(
        calls: calls,
        layout: {
          'topology_revision': 1,
          'snapshot_revision': 1,
          'algorithm_version': kTaskLayoutAlgorithmVersion,
          'usable': true,
          'centers': [
            {'task_id': 'task-a', 'world_y': 1},
          ],
        },
      ),
    );
    await malformed.loadOverview();
    expect(malformed.canonicalTaskCentersActive, isFalse);
    expect(calls.where((call) => call.startsWith('PUT')), isEmpty);

    final partial = _controller(
      _layoutMock(
        layout: _snapshot(usable: false, centers: const []),
        topology: _topology(['task-a', 'task-b']),
        putResponseCenters: [
          {'task_id': 'task-a', 'world_x': 1, 'world_y': 1},
        ],
      ),
    );
    await partial.loadOverview();
    expect(partial.canonicalTaskCentersActive, isFalse);
    expect(partial.taskLayoutWarning, taskLayoutResolutionWarning);
  });

  test('filters, reload of ordinary fields, and session reset', () async {
    final controller = _controller(
      _layoutMock(layout: _snapshot(usable: true, centers: _centers())),
    );
    await controller.loadOverview();
    final kept = Map<String, Offset>.from(controller.canonicalTaskCenters);
    controller.searchKindFilter = 'task';
    expect(controller.visibleNodes.map((node) => node.id), contains('task-a'));
    expect(controller.canonicalTaskCenters, kept);

    await controller.loadOverviewWindow(0);
    expect(controller.canonicalTaskCenters, kept);

    controller.resetSession();
    expect(controller.canonicalTaskCentersActive, isFalse);
    expect(controller.canonicalTaskCenters, isEmpty);
  });

  testWidgets('the same Task keeps its world position across semantic windows', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = GraphTestHarness(
      MockClient((request) async {
        final shell = _shell(request);
        if (shell != null) {
          return shell;
        }
        if (request.url.path == '/graph/workspace') {
          final index = int.parse(request.url.queryParameters['window_index'] ?? '0');
          final nodes = [
            graphObjectJson(id: 'task-a', title: 'Task A'),
            graphObjectJson(id: 'task-b', title: 'Task B'),
            if (index == 0) graphObjectJson(id: 'task-c', title: 'Task C'),
          ];
          return jsonUtf8Response({
            ...graphWorkspaceJson(nodes: nodes),
            'window_index': index,
            'window_count': 2,
            'has_next_window': index == 0,
            'has_previous_window': index == 1,
            'semantic_window_complete': true,
          });
        }
        if (request.url.path == '/graph/task-layout' && request.method == 'GET') {
          return jsonUtf8Response(
            _snapshot(
              usable: true,
              centers: const [
                {'task_id': 'task-a', 'world_x': 100, 'world_y': 100},
                {'task_id': 'task-b', 'world_x': 537, 'world_y': 100},
                {'task_id': 'task-c', 'world_x': 100, 'world_y': 900},
              ],
            ),
          );
        }
        return jsonUtf8Response({}, statusCode: 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);

    double delta() {
      final leftA = tester.widget<Positioned>(find.byKey(const ValueKey('drawn-task-a'))).left!;
      final leftB = tester.widget<Positioned>(find.byKey(const ValueKey('drawn-task-b'))).left!;
      return leftB - leftA;
    }

    expect(delta(), closeTo(437, 0.01));
    final subset = projectTaskMapHierarchy(
      nodes: [
        SecretaryObject.fromJson(graphObjectJson(id: 'task-a', title: 'Task A')),
        SecretaryObject.fromJson(graphObjectJson(id: 'task-b', title: 'Task B')),
      ],
      edges: const [],
    );
    final packed = subset.positions['task-b']!.dx - subset.positions['task-a']!.dx;
    expect(packed, isNot(closeTo(437, 0.01)));

    await tester.tap(find.byKey(const ValueKey('graph-overview-window-next')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('drawn-task-c')), findsNothing);
    expect(delta(), closeTo(437, 0.01));
    expect(harness.graph.canonicalTaskCenters['task-a'], const Offset(100, 100));

    await tester.tap(find.byTooltip('Уместить граф'));
    await tester.pumpAndSettle();
    expect(delta(), closeTo(437, 0.01));
  });

  testWidgets('ongoing Task anchors stay on the canonical center', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = GraphTestHarness(
      MockClient((request) async {
        final shell = _shell(request);
        if (shell != null) {
          return shell;
        }
        if (request.url.path == '/graph/workspace') {
          return jsonUtf8Response(
            graphWorkspaceJson(
              nodes: [
                graphObjectJson(id: 'task-finite', title: 'Finite'),
                graphObjectJson(
                  id: 'task-ongoing',
                  title: 'Ongoing',
                  completionMode: 'ongoing',
                ),
                graphObjectJson(id: 'flow-1', title: 'Note', kind: 'note'),
              ],
            ),
          );
        }
        if (request.url.path == '/graph/task-layout') {
          return jsonUtf8Response(
            _snapshot(
              usable: true,
              centers: const [
                {'task_id': 'task-finite', 'world_x': 200, 'world_y': 200},
                {'task_id': 'task-ongoing', 'world_x': 800, 'world_y': 200},
              ],
            ),
          );
        }
        return jsonUtf8Response({}, statusCode: 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);

    final finite = tester.widget<Positioned>(find.byKey(const ValueKey('drawn-task-finite')));
    final ongoing = tester.widget<Positioned>(find.byKey(const ValueKey('drawn-task-ongoing')));
    final finiteTopLeft = taskLayoutDrawnTopLeft(
      SecretaryObject.fromJson(graphObjectJson(id: 'task-finite', title: 'Finite')),
      const Offset(200, 200),
    );
    final ongoingTopLeft = taskLayoutDrawnTopLeft(
      SecretaryObject.fromJson(
        graphObjectJson(id: 'task-ongoing', title: 'Ongoing', completionMode: 'ongoing'),
      ),
      const Offset(800, 200),
    );
    expect(ongoing.left! - finite.left!, closeTo(ongoingTopLeft.dx - finiteTopLeft.dx, 0.01));
    expect(ongoing.top! - finite.top!, closeTo(ongoingTopLeft.dy - finiteTopLeft.dy, 0.01));
  });

  testWidgets('rooted Tasks keep the hierarchy layout', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final rootedNodes = [
      graphObjectJson(id: 'task-root', title: 'Root'),
      graphObjectJson(id: 'task-child', title: 'Child'),
    ];
    final harness = GraphTestHarness(
      MockClient((request) async {
        final shell = _shell(request);
        if (shell != null) {
          return shell;
        }
        if (request.url.path == '/graph/workspace') {
          final root = request.url.queryParameters['root_id'];
          if (root == 'task-root') {
            return jsonUtf8Response(
              graphWorkspaceJson(rootId: 'task-root', nodes: rootedNodes),
            );
          }
          return jsonUtf8Response(
            graphWorkspaceJson(nodes: rootedNodes),
          );
        }
        if (request.url.path == '/graph/task-layout') {
          return jsonUtf8Response(
            _snapshot(
              usable: true,
              centers: const [
                {'task_id': 'task-root', 'world_x': 10000, 'world_y': 8000},
                {'task_id': 'task-child', 'world_x': 11000, 'world_y': 8000},
              ],
            ),
          );
        }
        return jsonUtf8Response({}, statusCode: 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);
    expect(harness.graph.canonicalTaskCentersActive, isTrue);

    await harness.graph.reRoot('task-root');
    await tester.pumpAndSettle();

    final hierarchy = projectTaskMapHierarchy(
      nodes: rootedNodes.map((json) => SecretaryObject.fromJson(json)).toList(),
      edges: const [],
    );
    final drawn = tester.widget<Positioned>(find.byKey(const ValueKey('drawn-task-child'))).left! -
        tester.widget<Positioned>(find.byKey(const ValueKey('drawn-task-root'))).left!;
    final packed = hierarchy.positions['task-child']!.dx - hierarchy.positions['task-root']!.dx;
    expect(drawn, closeTo(packed, 0.01));
    expect(drawn, isNot(closeTo(1000, 0.01)));
    expect(harness.graph.canonicalTaskCenters['task-root'], const Offset(10000, 8000));
  });

  testWidgets('People overview does not consume Task centers', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var layoutReads = 0;
    final harness = GraphTestHarness(
      MockClient((request) async {
        final shell = _shell(request);
        if (shell != null) {
          return shell;
        }
        if (request.url.path == '/graph/workspace') {
          return jsonUtf8Response(
            graphWorkspaceJson(nodes: [graphObjectJson(id: 'task-a', title: 'Task A')]),
          );
        }
        if (request.url.path == '/graph/task-layout') {
          layoutReads += 1;
          return jsonUtf8Response(_snapshot(usable: true, centers: _centers()));
        }
        if (request.url.path == '/graph/people-workspace') {
          return jsonUtf8Response({
            'root_id': null,
            'seed_ids': ['person-1'],
            'nodes': [
              graphObjectJson(id: 'person-1', title: 'Olga', kind: 'person'),
            ],
            'edges': [],
            'truncated': false,
            'people': [
              {
                'person_id': 'person-1',
                'display_name': 'Olga',
                'primary_email': 'olga@example.com',
              },
            ],
          });
        }
        return jsonUtf8Response({}, statusCode: 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);
    final readsAfterTasks = layoutReads;
    final centers = Map<String, Offset>.from(harness.graph.canonicalTaskCenters);

    await harness.graph.setMode(GraphWorkspaceMode.people);
    await tester.pumpAndSettle();

    expect(find.text('Olga'), findsWidgets);
    expect(layoutReads, readsAfterTasks);
    expect(harness.graph.canonicalTaskCenters, centers);
    expect(find.byKey(const ValueKey('drawn-person-1')), findsOneWidget);
  });
}

GraphWorkspaceController _controller(MockClient mock) {
  final api = SecretaryApiClient(
    httpClient: mock,
    timezoneProvider: const FixedClientTimezoneProvider(
      ClientTimezoneContext(zoneId: 'Europe/Amsterdam', utcOffsetMinutes: 120),
    ),
  );
  api.configure(baseUrl: 'https://example.com', token: 'token');
  final auth = AuthController(
    apiClient: api,
    tokenStore: FakeTokenStore(),
    serverUrlStore: FakeServerUrlStore(),
  );
  return GraphWorkspaceController(apiClient: api, authController: auth);
}

MockClient _layoutMock({
  List<String>? calls,
  required Map<String, dynamic> layout,
  Map<String, dynamic>? topology,
  void Function(Map<String, dynamic> body)? onPut,
  int Function()? putStatus,
  List<Map<String, dynamic>>? putResponseCenters,
}) {
  return MockClient((request) async {
    calls?.add('${request.method} ${request.url.path}');
    if (request.url.path == '/graph/workspace') {
      return jsonUtf8Response(
        graphWorkspaceJson(nodes: [graphObjectJson(id: 'task-a', title: 'Task A')]),
      );
    }
    if (request.method == 'GET' && request.url.path == '/graph/task-layout') {
      return jsonUtf8Response(layout);
    }
    if (request.url.path == '/graph/task-layout/topology') {
      return jsonUtf8Response(topology!);
    }
    if (request.method == 'PUT' && request.url.path == '/graph/task-layout') {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      onPut?.call(body);
      final status = putStatus?.call() ?? 200;
      if (status != 200) {
        return http.Response('{"detail":"stale"}', status);
      }
      final centers = putResponseCenters ?? (body['centers'] as List).cast<Map<String, dynamic>>();
      return jsonUtf8Response(
        _snapshot(
          usable: true,
          revision: body['expected_topology_revision'] as int,
          centers: centers,
        ),
      );
    }
    return jsonUtf8Response({}, statusCode: 404);
  });
}

Map<String, dynamic> _snapshot({
  required bool usable,
  List<Map<String, dynamic>> centers = const [],
  String? algorithmVersion,
  int revision = 3,
}) {
  return {
    'topology_revision': revision,
    'snapshot_revision': usable ? revision : null,
    'algorithm_version': algorithmVersion ?? (usable ? kTaskLayoutAlgorithmVersion : null),
    'usable': usable,
    'centers': centers,
  };
}

List<Map<String, dynamic>> _centers() {
  return const [
    {'task_id': 'task-a', 'world_x': 100, 'world_y': 80},
    {'task_id': 'task-b', 'world_x': 240, 'world_y': 80},
  ];
}

Map<String, dynamic> _topology(List<String> ids) {
  return {
    'topology_revision': 7,
    'tasks': [for (final id in ids) graphObjectJson(id: id, title: id)],
    'edges': <Map<String, dynamic>>[],
  };
}

http.Response? _shell(http.Request request) {
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
  return null;
}
