import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_error.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/graph/graph_workspace_controller.dart';

import 'graph_test_harness.dart';

class _Call {
  _Call({this.rootId, this.windowIndex, this.people = false});

  final String? rootId;
  final int? windowIndex;
  final bool people;
}

class _ScriptedApi extends SecretaryApiClient {
  _ScriptedApi(this.onGraph, {this.onPeople});

  final Future<GraphWorkspaceOut> Function(String? rootId, int? windowIndex) onGraph;
  final Future<GraphWorkspaceOut> Function(String? rootId)? onPeople;
  final List<_Call> calls = [];

  @override
  Future<GraphWorkspaceOut> getGraphWorkspace({
    String? rootId,
    int? seedLimit,
    int? neighborLimit,
    int? nodeLimit,
    int? windowIndex,
  }) {
    calls.add(_Call(rootId: rootId, windowIndex: windowIndex));
    return onGraph(rootId, windowIndex);
  }

  @override
  Future<GraphWorkspaceOut> getPeopleWorkspace({
    String? rootId,
    String? query,
    int? seedLimit,
    int? neighborLimit,
  }) {
    calls.add(_Call(rootId: rootId, people: true));
    final handler = onPeople;
    if (handler == null) {
      throw StateError('people workspace was not expected');
    }
    return handler(rootId);
  }
}

class _FakeAuth extends AuthController {
  _FakeAuth()
      : super(
          apiClient: SecretaryApiClient(),
          tokenStore: FakeTokenStore(),
          serverUrlStore: FakeServerUrlStore(),
        );
}

SecretaryObject _obj(
  String id,
  String title, {
  String kind = 'task',
  String? status,
}) {
  return SecretaryObject(
    id: id,
    kind: kind,
    title: title,
    metadata: {},
    origin: 'user',
    state: 'confirmed',
    status: status,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  );
}

SecretaryEdge _edge(String id, String source, String target, {String type = 'references'}) {
  return SecretaryEdge(
    id: id,
    sourceId: source,
    targetId: target,
    type: type,
    origin: 'user',
    state: 'confirmed',
    metadata: {},
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  );
}

GraphWorkspaceOut _workspace({
  String? rootId,
  required List<SecretaryObject> nodes,
  List<SecretaryEdge> edges = const [],
  int windowIndex = 0,
  int windowCount = 1,
  bool hasPreviousWindow = false,
  bool hasNextWindow = false,
  List<String> constellationRootIds = const [],
  bool semanticWindowComplete = false,
}) {
  return GraphWorkspaceOut(
    rootId: rootId,
    seedIds: nodes.map((node) => node.id).toList(),
    nodes: nodes,
    edges: edges,
    truncated: false,
    windowIndex: windowIndex,
    windowCount: windowCount,
    hasPreviousWindow: hasPreviousWindow,
    hasNextWindow: hasNextWindow,
    constellationRootIds: constellationRootIds,
    semanticWindowComplete: semanticWindowComplete,
  );
}

GraphWorkspaceController _controller(_ScriptedApi api) {
  return GraphWorkspaceController(apiClient: api, authController: _FakeAuth());
}

void main() {
  test('single overview toggle restores the base and the show label', () async {
    final direction = _obj('a', 'Direction');
    final local = _obj('x', 'Local');
    final api = _ScriptedApi((rootId, windowIndex) async {
      if (rootId == 'a') {
        return _workspace(
          rootId: 'a',
          nodes: [direction, local],
          edges: [_edge('e-ax', 'a', 'x')],
        );
      }
      return _workspace(nodes: [direction], windowIndex: windowIndex ?? 0);
    });
    final controller = _controller(api);

    await controller.loadOverview();
    controller.selectObject('a');
    await controller.expandSelected();

    expect(controller.isLocalContextExpanded('a'), isTrue);
    expect(controller.nodes.map((node) => node.id), containsAll(['a', 'x']));

    await controller.hideLocalContext('a');

    expect(controller.nodes.map((node) => node.id), ['a']);
    expect(controller.isLocalContextExpanded('a'), isFalse);
    expect(controller.selectedObjectId, 'a');
    expect(controller.shouldFitAfterLayout, isTrue);
    expect(controller.rootId, isNull);
    expect(api.calls.where((call) => call.rootId == null).length, greaterThan(1));
  });

  test('hiding a parent returns a completed task to the default overview', () async {
    final direction = _obj('direction', 'Direction');
    final completed = _obj('done', 'Done', status: 'completed');
    final api = _ScriptedApi((rootId, windowIndex) async {
      if (rootId == 'direction') {
        return _workspace(
          rootId: 'direction',
          nodes: [direction, completed],
          edges: [_edge('part', 'done', 'direction', type: 'part_of')],
        );
      }
      return _workspace(nodes: [direction]);
    });
    final controller = _controller(api);

    await controller.loadOverview();
    controller.selectObject('direction');
    await controller.expandSelected();
    expect(controller.nodeById('done')?.status, 'completed');

    final readsBeforeHide = api.calls.length;
    await controller.hideLocalContext('direction');

    expect(controller.nodeById('done'), isNull);
    expect(controller.edges, isEmpty);
    expect(controller.nodeById('direction'), isNotNull);
    expect(api.calls.length, greaterThan(readsBeforeHide));
    expect(api.calls.every((call) => !call.people), isTrue);
  });

  test('nested expansions hide the inner anchor before the outer one', () async {
    final direction = _obj('direction', 'Direction');
    final task = _obj('task', 'Task', status: 'completed');
    final flow = _obj('flow', 'Flow', kind: 'email');
    final api = _ScriptedApi((rootId, windowIndex) async {
      if (rootId == 'direction') {
        return _workspace(
          rootId: 'direction',
          nodes: [direction, task],
          edges: [_edge('part', 'task', 'direction', type: 'part_of')],
        );
      }
      if (rootId == 'task') {
        return _workspace(
          rootId: 'task',
          nodes: [task, flow],
          edges: [_edge('evidence', 'task', 'flow')],
        );
      }
      return _workspace(nodes: [direction]);
    });
    final controller = _controller(api);

    await controller.loadOverview();
    controller.selectObject('direction');
    await controller.expandSelected();
    controller.selectObject('task');
    await controller.expandSelected();
    expect(controller.localContextAnchorIds, ['direction', 'task']);
    expect(controller.nodeById('flow'), isNotNull);

    await controller.hideLocalContext('task');

    expect(controller.localContextAnchorIds, ['direction']);
    expect(controller.isLocalContextExpanded('direction'), isTrue);
    expect(controller.nodeById('task'), isNotNull);
    expect(controller.nodeById('flow'), isNull);
    expect(controller.selectedObjectId, 'task');

    await controller.hideLocalContext('direction');

    expect(controller.localContextAnchorIds, isEmpty);
    expect(controller.nodes.map((node) => node.id), ['direction']);
  });

  test('shared context stays while another expansion still returns it', () async {
    final a = _obj('a', 'A');
    final b = _obj('b', 'B');
    final shared = _obj('x', 'Shared');
    final api = _ScriptedApi((rootId, windowIndex) async {
      if (rootId == 'a') {
        return _workspace(rootId: 'a', nodes: [a, shared], edges: [_edge('ax', 'a', 'x')]);
      }
      if (rootId == 'b') {
        return _workspace(rootId: 'b', nodes: [b, shared], edges: [_edge('bx', 'b', 'x')]);
      }
      return _workspace(nodes: [a, b]);
    });
    final controller = _controller(api);

    await controller.loadOverview();
    controller.selectObject('a');
    await controller.expandSelected();
    controller.selectObject('b');
    await controller.expandSelected();
    await controller.hideLocalContext('a');

    expect(controller.nodeById('x'), isNotNull);
    expect(controller.isLocalContextExpanded('a'), isFalse);
    expect(controller.isLocalContextExpanded('b'), isTrue);
    expect(controller.localContextAnchorIds, ['b']);
    expect(controller.rootId, isNull);
  });

  test('hiding the earlier anchor replays the later one', () async {
    final a = _obj('a', 'A');
    final b = _obj('b', 'B');
    final onlyB = _obj('only-b', 'Only B');
    final replayedRoots = <String?>[];
    final api = _ScriptedApi((rootId, windowIndex) async {
      replayedRoots.add(rootId);
      if (rootId == 'a') {
        return _workspace(rootId: 'a', nodes: [a, _obj('only-a', 'Only A')]);
      }
      if (rootId == 'b') {
        return _workspace(rootId: 'b', nodes: [b, onlyB]);
      }
      return _workspace(nodes: [a, b]);
    });
    final controller = _controller(api);
    await controller.loadOverview();
    controller.selectObject('a');
    await controller.expandSelected();
    controller.selectObject('b');
    await controller.expandSelected();
    replayedRoots.clear();

    await controller.hideLocalContext('a');

    expect(replayedRoots, [null, 'b']);
    expect(controller.nodeById('only-a'), isNull);
    expect(controller.nodeById('only-b'), isNotNull);
    expect(controller.isLocalContextExpanded('b'), isTrue);
    expect(controller.isLocalContextExpanded('a'), isFalse);
  });

  test('repeated show does not duplicate the active anchor', () async {
    final api = _ScriptedApi((rootId, windowIndex) async {
      if (rootId == 'a') {
        return _workspace(rootId: 'a', nodes: [_obj('a', 'A'), _obj('x', 'X')]);
      }
      return _workspace(nodes: [_obj('a', 'A')]);
    });
    final controller = _controller(api);
    await controller.loadOverview();
    controller.selectObject('a');
    await controller.expandSelected();
    await controller.expandSelected();

    expect(controller.localContextAnchorIds, ['a']);
  });

  test('failed show leaves the graph and does not mark the anchor', () async {
    final api = _ScriptedApi((rootId, windowIndex) async {
      if (rootId == 'a') {
        throw ServerException('expand failed');
      }
      return _workspace(nodes: [_obj('a', 'A')]);
    });
    final controller = _controller(api);
    await controller.loadOverview();
    controller.selectObject('a');
    await controller.expandSelected();

    expect(controller.nodes.map((node) => node.id), ['a']);
    expect(controller.isLocalContextExpanded('a'), isFalse);
    expect(controller.errorMessage, 'expand failed');
  });

  test('failed hide keeps the graph and the expansion bookkeeping', () async {
    var failHide = false;
    final api = _ScriptedApi((rootId, windowIndex) async {
      if (rootId == null && failHide) {
        throw ServerException('hide failed');
      }
      if (rootId == 'a') {
        return _workspace(rootId: 'a', nodes: [_obj('a', 'A'), _obj('x', 'X')]);
      }
      return _workspace(nodes: [_obj('a', 'A')]);
    });
    final controller = _controller(api);
    await controller.loadOverview();
    controller.selectObject('a');
    await controller.expandSelected();
    final positions = Map<String, Offset>.from(controller.positions);
    failHide = true;

    await controller.hideLocalContext('a');

    expect(controller.nodes.map((node) => node.id), containsAll(['a', 'x']));
    expect(controller.localContextAnchorIds, ['a']);
    expect(controller.positions['x'], positions['x']);
    expect(controller.errorMessage, localContextHideFailureMessage);
    expect(controller.loadState, GraphWorkspaceLoadState.ready);
  });

  test('hide keeps authoritative overview metadata rather than replay defaults', () async {
    final base = _workspace(
      nodes: [_obj('a', 'A'), _obj('b', 'B')],
      windowIndex: 2,
      windowCount: 4,
      hasPreviousWindow: true,
      hasNextWindow: true,
      constellationRootIds: const ['a'],
      semanticWindowComplete: true,
    );
    final api = _ScriptedApi((rootId, windowIndex) async {
      if (rootId == 'a' || rootId == 'b') {
        return _workspace(
          rootId: rootId,
          nodes: [_obj(rootId!, rootId), _obj('extra-$rootId', 'Extra')],
          windowIndex: 0,
          windowCount: 1,
          constellationRootIds: const ['replay'],
          semanticWindowComplete: false,
        );
      }
      return base;
    });
    final controller = _controller(api);
    await controller.loadOverview();
    controller.selectObject('a');
    await controller.expandSelected();
    controller.selectObject('b');
    await controller.expandSelected();

    await controller.hideLocalContext('b');

    expect(controller.windowIndex, 2);
    expect(controller.windowCount, 4);
    expect(controller.hasPreviousWindow, isTrue);
    expect(controller.hasNextWindow, isTrue);
    expect(controller.constellationRootIds, ['a']);
    expect(controller.semanticWindowComplete, isTrue);
    expect(controller.nodeById('extra-a'), isNotNull);
    expect(controller.nodeById('extra-b'), isNull);
  });

  test('invalid hide window recovers once to window 0', () async {
    var hideStarted = false;
    final windows = <int?>[];
    final api = _ScriptedApi((rootId, windowIndex) async {
      if (rootId == null) {
        windows.add(windowIndex);
      }
      if (rootId == null && hideStarted && windowIndex == 3) {
        throw ServerException('window index is out of range');
      }
      if (rootId == 'a') {
        return _workspace(rootId: 'a', nodes: [_obj('a', 'A'), _obj('x', 'X')]);
      }
      return _workspace(
        nodes: [_obj('a', 'A')],
        windowIndex: hideStarted ? 0 : (windowIndex ?? 0),
        windowCount: hideStarted ? 1 : 4,
      );
    });
    final controller = _controller(api);
    await controller.loadOverviewWindow(3);
    controller.selectObject('a');
    await controller.expandSelected();
    windows.clear();
    hideStarted = true;

    await controller.hideLocalContext('a');

    expect(windows, [3, 0]);
    expect(controller.windowIndex, 0);
    expect(controller.nodeById('x'), isNull);
    expect(controller.errorMessage, isNull);
  });

  test('show and hide inside a rooted workspace restore that rooted base', () async {
    final api = _ScriptedApi((rootId, windowIndex) async {
      if (rootId == 'child') {
        return _workspace(
          rootId: 'child',
          nodes: [_obj('child', 'Child'), _obj('flow', 'Flow', kind: 'email')],
        );
      }
      if (rootId == 'root') {
        return _workspace(rootId: 'root', nodes: [_obj('root', 'Root'), _obj('child', 'Child')]);
      }
      return _workspace(nodes: [_obj('overview', 'Overview')]);
    });
    final controller = _controller(api);
    await controller.reRoot('root');
    controller.selectObject('child');
    await controller.expandSelected();
    expect(controller.nodeById('flow'), isNotNull);

    await controller.hideLocalContext('child');

    expect(controller.rootId, 'root');
    expect(controller.nodeById('flow'), isNull);
    expect(controller.nodeById('child'), isNotNull);
    expect(controller.nodes.map((node) => node.id), isNot(contains('overview')));
  });

  test('hide keeps a surviving selection and clears a disappeared one', () async {
    final api = _ScriptedApi((rootId, windowIndex) async {
      if (rootId == 'a') {
        return _workspace(rootId: 'a', nodes: [_obj('a', 'A'), _obj('x', 'X')]);
      }
      return _workspace(nodes: [_obj('a', 'A')]);
    });
    final controller = _controller(api);
    await controller.loadOverview();
    controller.selectObject('a');
    await controller.expandSelected();
    controller.selectObject('x');

    await controller.hideLocalContext('a');

    expect(controller.selectedObjectId, isNull);

    controller.selectObject('a');
    await controller.expandSelected();
    controller.selectObject('a');
    await controller.hideLocalContext('a');
    expect(controller.selectedObjectId, 'a');
  });

  test('navigation replaces the base and clears local expansion state', () async {
    final api = _ScriptedApi(
      (rootId, windowIndex) async {
        if (rootId == 'a') {
          return _workspace(rootId: 'a', nodes: [_obj('a', 'A'), _obj('x', 'X')]);
        }
        if (rootId == 'other') {
          return _workspace(rootId: 'other', nodes: [_obj('other', 'Other')]);
        }
        return _workspace(
          nodes: [_obj('a', 'A'), _obj('b', 'B')],
          windowIndex: windowIndex ?? 0,
          windowCount: 2,
          hasNextWindow: (windowIndex ?? 0) == 0,
          hasPreviousWindow: (windowIndex ?? 0) == 1,
        );
      },
      onPeople: (rootId) async {
        return _workspace(nodes: [_obj('person', 'Person', kind: 'person')]);
      },
    );
    final controller = _controller(api);
    await controller.loadOverview();
    controller.selectObject('a');
    await controller.expandSelected();

    controller.selectObject('b');
    controller.clearFitRequest();
    expect(controller.isLocalContextExpanded('a'), isTrue);

    await controller.loadOverviewWindow(1);
    expect(controller.localContextAnchorIds, isEmpty);

    controller.selectObject('a');
    await controller.expandSelected();
    await controller.reRoot('other');
    expect(controller.localContextAnchorIds, isEmpty);

    await controller.loadOverview();
    controller.selectObject('a');
    await controller.expandSelected();
    await controller.refreshCurrentWorkspace();
    expect(controller.localContextAnchorIds, isEmpty);

    controller.selectObject('a');
    await controller.expandSelected();
    await controller.setMode(GraphWorkspaceMode.people);
    expect(controller.mode, GraphWorkspaceMode.people);
    expect(controller.localContextAnchorIds, isEmpty);
    expect(api.calls.last.people, isTrue);
  });

  test('task topology refresh clears local expansion and requests a fresh fit', () async {
    final parent = _obj('parent', 'Parent');
    final child = _obj('child', 'Child');
    final partOf = _edge('part', 'child', 'parent', type: 'part_of');
    var mutated = false;
    final api = _ScriptedApi((rootId, windowIndex) async {
      if (!mutated && rootId == 'parent') {
        return _workspace(rootId: 'parent', nodes: [parent, _obj('x', 'Local')]);
      }
      return _workspace(nodes: [parent, child], edges: mutated ? [partOf] : const []);
    });
    final controller = _controller(api);
    await controller.loadOverview();
    final before = controller.positions['parent'];
    controller.selectObject('parent');
    await controller.expandSelected();
    expect(controller.nodeById('x'), isNotNull);
    mutated = true;

    await controller.applyCreatedRelation(
      sourceId: 'parent',
      sourceKind: 'task',
      target: child,
      edge: partOf,
    );

    expect(controller.localContextAnchorIds, isEmpty);
    expect(controller.nodeById('x'), isNull);
    expect(controller.edges.single.type, 'part_of');
    expect(controller.shouldFitAfterLayout, isTrue);
    expect(controller.positions['parent'], isNot(before));
  });

  test('hide refetches persisted task evidence instead of rolling it back', () async {
    var persisted = false;
    final task = _obj('task', 'Task');
    final evidence = _obj('mail', 'Mail', kind: 'email');
    final evidenceEdge = _edge('mail-edge', 'task', 'mail');
    final api = _ScriptedApi((rootId, windowIndex) async {
      if (rootId == 'task') {
        return _workspace(
          rootId: 'task',
          nodes: [task, _obj('local', 'Local', kind: 'email')],
          edges: [_edge('local-edge', 'task', 'local')],
        );
      }
      if (persisted) {
        return _workspace(nodes: [task, evidence], edges: [evidenceEdge]);
      }
      return _workspace(nodes: [task]);
    });
    final controller = _controller(api);
    await controller.loadOverview();
    controller.selectObject('task');
    await controller.expandSelected();
    persisted = true;
    await controller.applyCreatedRelation(
      sourceId: 'task',
      sourceKind: 'task',
      target: evidence,
      edge: evidenceEdge,
    );
    expect(controller.isLocalContextExpanded('task'), isTrue);
    expect(controller.nodeById('mail'), isNotNull);

    await controller.hideLocalContext('task');

    expect(controller.nodeById('local'), isNull);
    expect(controller.nodeById('mail'), isNotNull);
    expect(controller.edges.map((edge) => edge.id), ['mail-edge']);
    expect(controller.isLocalContextExpanded('task'), isFalse);
  });

  test('people show and hide restore the people base', () async {
    final person = _obj('person', 'Ada', kind: 'person');
    final evidence = _obj('note', 'Note', kind: 'note');
    final api = _ScriptedApi(
      (rootId, windowIndex) async => throw StateError('tasks workspace during people hide'),
      onPeople: (rootId) async {
        if (rootId == 'person') {
          return _workspace(rootId: 'person', nodes: [person, evidence]);
        }
        return _workspace(nodes: [person]);
      },
    );
    final controller = _controller(api);
    await controller.setMode(GraphWorkspaceMode.people);
    controller.selectObject('person');
    await controller.expandSelected();
    expect(controller.nodeById('note'), isNotNull);
    expect(controller.isLocalContextExpanded('person'), isTrue);

    await controller.hideLocalContext('person');

    expect(controller.mode, GraphWorkspaceMode.people);
    expect(controller.nodes.map((node) => node.id), ['person']);
    expect(controller.nodeById('person')?.title, 'Ada');
    expect(controller.isLocalContextExpanded('person'), isFalse);
    expect(api.calls.every((call) => call.people), isTrue);
  });

  testWidgets('show and hide swap the detail action label', (tester) async {
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
            'day_start': '2026-08-28T08:00:00+02:00',
            'tasks': [],
            'calendar_events': [],
            'notifications': [],
          });
        }
        if (request.url.path == '/graph/workspace') {
          final root = request.url.queryParameters['root_id'];
          if (root == 'task-1') {
            return jsonUtf8Response(
              graphWorkspaceJson(
                rootId: 'task-1',
                nodes: [
                  graphObjectJson(id: 'task-1', title: 'Graph task'),
                  graphObjectJson(id: 'local-1', title: 'Local context', kind: 'email'),
                ],
                edges: [
                  {
                    'id': 'e-local',
                    'source_id': 'task-1',
                    'target_id': 'local-1',
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
          return jsonUtf8Response(
            graphWorkspaceJson(
              nodes: [graphObjectJson(id: 'task-1', title: 'Graph task')],
            ),
          );
        }
        if (request.url.path == '/search') {
          return jsonUtf8Response([]);
        }
        if (request.url.path == '/search/facets') {
          return jsonUtf8Response({
            'kinds': [
              {'value': 'task', 'count': 1},
            ],
            'providers': [],
          });
        }
        return http.Response(jsonEncode({}), 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);
    harness.graph.selectObject('task-1');
    await tester.pump();

    expect(find.text('Показать связи'), findsOneWidget);
    await tester.tap(find.text('Показать связи'));
    await tester.pumpAndSettle();

    expect(harness.graph.isLocalContextExpanded('task-1'), isTrue);
    expect(find.text('Скрыть связи'), findsOneWidget);

    await tester.tap(find.text('Скрыть связи'));
    await tester.pumpAndSettle();

    expect(harness.graph.isLocalContextExpanded('task-1'), isFalse);
    expect(find.text('Показать связи'), findsOneWidget);
    expect(harness.graph.nodeById('local-1'), isNull);
  });
}
