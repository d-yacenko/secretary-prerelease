import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_error.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/graph/graph_layout.dart';
import 'package:personal_secretary/graph/graph_workspace_controller.dart';
import 'package:personal_secretary/graph/task_map_hierarchy.dart';

class _FakeApiClient extends SecretaryApiClient {
  _FakeApiClient(this._handler);

  final Future<GraphWorkspaceOut> Function(String? rootId) _handler;
  int? requestedWindow;
  String? requestedRootId;
  int fetchCount = 0;

  @override
  Future<GraphWorkspaceOut> getGraphWorkspace({
    String? rootId,
    int? seedLimit,
    int? neighborLimit,
    int? nodeLimit,
    int? windowIndex,
  }) {
    fetchCount += 1;
    requestedRootId = rootId;
    requestedWindow = windowIndex;
    return _handler(rootId);
  }
}

class _FakeAuth extends AuthController {
  _FakeAuth()
      : super(
          apiClient: SecretaryApiClient(),
          tokenStore: FakeTokenStore(),
          serverUrlStore: FakeServerUrlStore(),
        );

  bool failed = false;

  @override
  void handleAuthenticationFailure() {
    failed = true;
  }
}

SecretaryObject _obj(
  String id,
  String title, {
  String? status,
  String state = 'confirmed',
  String kind = 'task',
}) {
  return SecretaryObject(
    id: id,
    kind: kind,
    title: title,
    metadata: {},
    origin: 'user',
    state: state,
    status: status,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  );
}

GraphWorkspaceOut _workspace({
  String? rootId,
  List<SecretaryObject> nodes = const [],
}) {
  return GraphWorkspaceOut(
    rootId: rootId,
    seedIds: [],
    nodes: nodes,
    edges: [],
    truncated: false,
  );
}

void main() {
  test('reRoot replaces unrelated nodes and selects root', () async {
    final auth = _FakeAuth();
    final controller = GraphWorkspaceController(
      apiClient: _FakeApiClient((rootId) async {
        if (rootId == 'new-root') {
          return _workspace(rootId: 'new-root', nodes: [_obj('new-root', 'New')]);
        }
        return _workspace(nodes: [_obj('old', 'Old')]);
      }),
      authController: auth,
    );

    await controller.loadOverview();
    expect(controller.nodes.length, 1);
    expect(controller.nodes.first.id, 'old');

    await controller.reRoot('new-root');
    expect(controller.rootId, 'new-root');
    expect(controller.selectedObjectId, 'new-root');
    expect(controller.selectedObject, isNotNull);
    expect(controller.nodes.length, 1);
    expect(controller.nodes.first.id, 'new-root');
    expect(controller.positions.containsKey('new-root'), isTrue);
  });

  test('expandSelected preserves graph on error', () async {
    final auth = _FakeAuth();
    var calls = 0;
    final controller = GraphWorkspaceController(
      apiClient: _FakeApiClient((rootId) async {
        calls += 1;
        if (calls > 1) {
          throw Exception('network');
        }
        return _workspace(rootId: 'root', nodes: [_obj('root', 'Root')]);
      }),
      authController: auth,
    );

    await controller.reRoot('root');
    await controller.expandSelected();
    expect(controller.nodes.length, 1);
    expect(controller.errorMessage, isNotNull);
  });

  test('expand merges neighbors without duplicate nodes', () async {
    final auth = _FakeAuth();
    final controller = GraphWorkspaceController(
      apiClient: _FakeApiClient((rootId) async {
        if (rootId == 'root') {
          return GraphWorkspaceOut(
            rootId: 'root',
            seedIds: ['root'],
            nodes: [_obj('root', 'Root'), _obj('n1', 'Neighbor')],
            edges: [
              SecretaryEdge(
                id: 'e1',
                sourceId: 'root',
                targetId: 'n1',
                type: 'references',
                origin: 'user',
                state: 'confirmed',
                metadata: {},
                createdAt: '2026-01-01T00:00:00Z',
                updatedAt: '2026-01-01T00:00:00Z',
              ),
            ],
            truncated: false,
          );
        }
        return _workspace(nodes: [_obj('root', 'Root')]);
      }),
      authController: auth,
    );

    await controller.reRoot('root');
    final rootPos = controller.positions['root'];
    await controller.expandSelected();

    expect(controller.nodes.length, 2);
    expect(controller.edges.length, 1);
    expect(controller.positions['root'], rootPos);
    expect(controller.positions.containsKey('n1'), isTrue);
  });

  test('repeated expand preserves neighbor positions without overlap', () async {
    var expandCalls = 0;
    final auth = _FakeAuth();
    final controller = GraphWorkspaceController(
      apiClient: _FakeApiClient((rootId) async {
        if (rootId == 'root') {
          expandCalls += 1;
          if (expandCalls == 1) {
            return _workspace(rootId: 'root', nodes: [_obj('root', 'Root')]);
          }
          if (expandCalls == 2) {
            return GraphWorkspaceOut(
              rootId: 'root',
              seedIds: ['root'],
              nodes: [_obj('root', 'Root'), _obj('n1', 'Neighbor 1')],
              edges: [
                SecretaryEdge(
                  id: 'e1',
                  sourceId: 'root',
                  targetId: 'n1',
                  type: 'references',
                  origin: 'user',
                  state: 'confirmed',
                  metadata: {},
                  createdAt: '2026-01-01T00:00:00Z',
                  updatedAt: '2026-01-01T00:00:00Z',
                ),
              ],
              truncated: false,
            );
          }
          return GraphWorkspaceOut(
            rootId: 'root',
            seedIds: ['root'],
            nodes: [
              _obj('root', 'Root'),
              _obj('n1', 'Neighbor 1'),
              _obj('n2', 'Neighbor 2'),
            ],
            edges: [
              SecretaryEdge(
                id: 'e1',
                sourceId: 'root',
                targetId: 'n1',
                type: 'references',
                origin: 'user',
                state: 'confirmed',
                metadata: {},
                createdAt: '2026-01-01T00:00:00Z',
                updatedAt: '2026-01-01T00:00:00Z',
              ),
              SecretaryEdge(
                id: 'e2',
                sourceId: 'root',
                targetId: 'n2',
                type: 'references',
                origin: 'user',
                state: 'confirmed',
                metadata: {},
                createdAt: '2026-01-01T00:00:00Z',
                updatedAt: '2026-01-01T00:00:00Z',
              ),
            ],
            truncated: false,
          );
        }
        return _workspace(nodes: [_obj('root', 'Root')]);
      }),
      authController: auth,
    );

    await controller.reRoot('root');
    await controller.expandSelected();

    final rootPos = controller.positions['root']!;
    final n1Pos = controller.positions['n1']!;
    expect(controller.nodes.length, 2);

    await controller.expandSelected();

    expect(controller.nodes.length, 3);
    expect(controller.positions['root'], rootPos);
    expect(controller.positions['n1'], n1Pos);
    expect(controller.positions.containsKey('n2'), isTrue);
    _expectNoOverlaps(controller.positions);
  });

  test('mergeRelationContext positions absent target', () async {
    final auth = _FakeAuth();
    final edge = SecretaryEdge(
      id: 'e1',
      sourceId: 'source',
      targetId: 'target',
      type: 'related_to',
      origin: 'user',
      state: 'confirmed',
      metadata: {},
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    );
    final controller = GraphWorkspaceController(
      apiClient: _FakeApiClient((rootId) async {
        return GraphWorkspaceOut(
          rootId: 'source',
          seedIds: ['source'],
          nodes: [_obj('source', 'Source'), _obj('target', 'Target')],
          edges: [edge],
          truncated: false,
        );
      }),
      authController: auth,
    );

    await controller.reRoot('source');
    controller.removeEdge('e1');
    expect(controller.edges, isEmpty);

    await controller.mergeRelationContext(
      'source',
      target: _obj('target', 'Target'),
      edge: edge,
    );

    expect(controller.edges.length, 1);
    expect(controller.positions.containsKey('source'), isTrue);
    expect(controller.positions.containsKey('target'), isTrue);
    expect(controller.edgeEndpointsPositioned(edge), isTrue);
  });

  test('Task-to-Task merge clears geometry when the authoritative refresh fails', () async {
    final auth = _FakeAuth();
    final edge = SecretaryEdge(
      id: 'e-new',
      sourceId: 'source',
      targetId: 'target',
      type: 'related_to',
      origin: 'user',
      state: 'confirmed',
      metadata: {},
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    );
    var calls = 0;
    final controller = GraphWorkspaceController(
      apiClient: _FakeApiClient((rootId) async {
        calls += 1;
        if (calls > 1) {
          throw Exception('network');
        }
        return _workspace(rootId: 'source', nodes: [_obj('source', 'Source')]);
      }),
      authController: auth,
    );

    await controller.reRoot('source');
    await controller.mergeRelationContext(
      'source',
      target: _obj('target', 'Target'),
      edge: edge,
    );

    expect(controller.edges.any((item) => item.id == 'e-new'), isFalse);
    expect(controller.positions, isEmpty);
    expect(controller.loadState, GraphWorkspaceLoadState.error);
    expect(controller.errorMessage, taskTopologyRefreshFailureMessage);
    expect(calls, 2);
  });

  test('selectObject updates selection', () {
    final auth = _FakeAuth();
    final controller = GraphWorkspaceController(
      apiClient: _FakeApiClient((_) async => _workspace()),
      authController: auth,
    );
    controller.upsertObject(_obj('a', 'A'));
    controller.selectObject('a');
    expect(controller.selectedObjectId, 'a');
    expect(controller.selectedObject?.title, 'A');
  });

  test('refreshCurrentWorkspace reloads overview', () async {
    var calls = 0;
    final auth = _FakeAuth();
    final controller = GraphWorkspaceController(
      apiClient: _FakeApiClient((rootId) async {
        calls += 1;
        if (calls == 1) {
          return _workspace(nodes: [_obj('a', 'A')]);
        }
        return _workspace(nodes: [_obj('a', 'A'), _obj('b', 'B')]);
      }),
      authController: auth,
    );

    await controller.loadOverview();
    expect(controller.nodes.length, 1);

    await controller.refreshCurrentWorkspace();
    expect(calls, 2);
    expect(controller.nodes.length, 2);
    expect(controller.nodeById('b'), isNotNull);
  });

  test('delete removes task immediately from overview', () async {
    final auth = _FakeAuth();
    final edge = SecretaryEdge(
      id: 'e1',
      sourceId: 'a',
      targetId: 'b',
      type: 'references',
      origin: 'user',
      state: 'confirmed',
      metadata: {},
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    );
    final controller = GraphWorkspaceController(
      apiClient: _FakeApiClient((_) async {
        return GraphWorkspaceOut(
          rootId: null,
          seedIds: ['a', 'b'],
          nodes: [_obj('a', 'A'), _obj('b', 'B')],
          edges: [edge],
          truncated: false,
        );
      }),
      authController: auth,
    );

    await controller.loadOverview();
    controller.selectObject('a');
    await controller.applyTaskMutation(_obj('a', 'A', status: 'deleted'));

    expect(controller.nodeById('a'), isNull);
    expect(controller.positions.containsKey('a'), isFalse);
    expect(controller.edges, isEmpty);
    expect(controller.selectedObjectId, isNull);
    expect(controller.nodeById('b'), isNotNull);
  });

  test('delete rooted task falls back to overview', () async {
    var calls = 0;
    final auth = _FakeAuth();
    final controller = GraphWorkspaceController(
      apiClient: _FakeApiClient((rootId) async {
        calls += 1;
        if (rootId == 'a') {
          return _workspace(rootId: 'a', nodes: [_obj('a', 'A')]);
        }
        return _workspace(nodes: [_obj('b', 'B')]);
      }),
      authController: auth,
    );

    await controller.reRoot('a');
    await controller.applyTaskMutation(_obj('a', 'A', status: 'deleted'));

    expect(controller.rootId, isNull);
    expect(controller.nodeById('a'), isNull);
    expect(controller.nodeById('b'), isNotNull);
    expect(calls, greaterThanOrEqualTo(2));
  });

  test('terminal status removes task from overview immediately', () async {
    final auth = _FakeAuth();
    final controller = GraphWorkspaceController(
      apiClient: _FakeApiClient((_) async {
        return _workspace(nodes: [_obj('a', 'A', status: 'open')]);
      }),
      authController: auth,
    );

    await controller.loadOverview();
    await controller.applyTaskMutation(_obj('a', 'A', status: 'done'));

    expect(controller.nodeById('a'), isNull);
  });

  test('in_progress status keeps task in overview', () async {
    final auth = _FakeAuth();
    final controller = GraphWorkspaceController(
      apiClient: _FakeApiClient((_) async {
        return _workspace(nodes: [_obj('a', 'A', status: 'open')]);
      }),
      authController: auth,
    );

    await controller.loadOverview();
    await controller.applyTaskMutation(_obj('a', 'A', status: 'in_progress'));

    expect(controller.nodeById('a')?.status, 'in_progress');
  });

  test('refresh after delete does not resurrect removed task', () async {
    var calls = 0;
    final auth = _FakeAuth();
    final controller = GraphWorkspaceController(
      apiClient: _FakeApiClient((_) async {
        calls += 1;
        if (calls == 1) {
          return _workspace(nodes: [_obj('a', 'A'), _obj('b', 'B')]);
        }
        return _workspace(nodes: [_obj('b', 'B')]);
      }),
      authController: auth,
    );

    await controller.loadOverview();
    await controller.applyTaskMutation(_obj('a', 'A', status: 'deleted'));
    await controller.refreshCurrentWorkspace();

    expect(controller.nodeById('a'), isNull);
    expect(controller.nodeById('b'), isNotNull);
  });

  test('refresh rooted deleted root from API falls back to overview', () async {
    var rootedCalls = 0;
    final auth = _FakeAuth();
    final controller = GraphWorkspaceController(
      apiClient: _FakeApiClient((rootId) async {
        if (rootId == 'a') {
          rootedCalls += 1;
          if (rootedCalls == 1) {
            return _workspace(rootId: 'a', nodes: [_obj('a', 'A')]);
          }
          return _workspace(
            rootId: 'a',
            nodes: [_obj('a', 'A', status: 'deleted')],
          );
        }
        return _workspace(nodes: [_obj('b', 'B')]);
      }),
      authController: auth,
    );

    await controller.reRoot('a');
    await controller.refreshCurrentWorkspace();

    expect(controller.rootId, isNull);
    expect(controller.nodeById('a'), isNull);
    expect(controller.nodeById('b'), isNotNull);
  });

  test('refresh rooted missing root falls back to overview', () async {
    var rootedCalls = 0;
    final auth = _FakeAuth();
    final controller = GraphWorkspaceController(
      apiClient: _FakeApiClient((rootId) async {
        if (rootId == 'a') {
          rootedCalls += 1;
          if (rootedCalls == 1) {
            return _workspace(rootId: 'a', nodes: [_obj('a', 'A')]);
          }
          throw NotFoundException();
        }
        return _workspace(nodes: [_obj('b', 'B')]);
      }),
      authController: auth,
    );

    await controller.reRoot('a');
    expect(controller.rootId, 'a');

    await controller.refreshCurrentWorkspace();

    expect(controller.rootId, isNull);
    expect(controller.nodeById('a'), isNull);
    expect(controller.nodeById('b'), isNotNull);
    expect(controller.loadState, GraphWorkspaceLoadState.ready);
  });

  test('refresh rooted network error preserves graph', () async {
    var rootedCalls = 0;
    final auth = _FakeAuth();
    final controller = GraphWorkspaceController(
      apiClient: _FakeApiClient((rootId) async {
        if (rootId == 'root') {
          rootedCalls += 1;
          if (rootedCalls == 1) {
            return _workspace(rootId: 'root', nodes: [_obj('root', 'Root')]);
          }
          throw NetworkException('offline');
        }
        return _workspace();
      }),
      authController: auth,
    );

    await controller.reRoot('root');
    expect(controller.nodes.length, 1);

    await controller.refreshCurrentWorkspace();

    expect(controller.rootId, 'root');
    expect(controller.nodes.length, 1);
    expect(controller.nodeById('root'), isNotNull);
    expect(controller.errorMessage, 'offline');
    expect(controller.loadState, GraphWorkspaceLoadState.ready);
  });

  test('search facets do not hide workspace nodes or edges', () async {
    final auth = _FakeAuth();
    final task = SecretaryObject(
      id: 'task-local',
      kind: 'task',
      title: 'Local task',
      metadata: {},
      origin: 'user',
      state: 'confirmed',
      provider: 'local_device',
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    );
    final gmail = SecretaryObject(
      id: 'email-gmail',
      kind: 'email',
      title: 'Gmail mail',
      metadata: {},
      origin: 'source',
      state: 'observed',
      provider: 'gmail',
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    );
    final yandex = SecretaryObject(
      id: 'email-yandex',
      kind: 'email',
      title: 'Yandex mail',
      metadata: {},
      origin: 'source',
      state: 'observed',
      provider: 'yandex_mail',
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    );
  final edgeTaskGmail = SecretaryEdge(
      id: 'e-task-gmail',
      sourceId: 'task-local',
      targetId: 'email-gmail',
      type: 'references',
      origin: 'user',
      state: 'confirmed',
      metadata: {},
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    );
    final controller = GraphWorkspaceController(
      apiClient: _FakeApiClient((_) async {
        return GraphWorkspaceOut(
          rootId: null,
          seedIds: ['task-local', 'email-gmail', 'email-yandex'],
          nodes: [task, gmail, yandex],
          edges: [edgeTaskGmail],
          truncated: false,
        );
      }),
      authController: auth,
    );

    await controller.loadOverview();
    final originalPositions = Map<String, Offset>.from(controller.positions);

    controller.searchKindFilter = 'email';
    expect(
      controller.visibleNodes.map((node) => node.id).toSet(),
      {'task-local', 'email-gmail', 'email-yandex'},
    );
    expect(controller.visibleEdges.map((edge) => edge.id), ['e-task-gmail']);
    expect(controller.selectedObjectId, isNull);

    controller.searchProviderFilter = 'gmail';
    expect(controller.visibleNodes.length, 3);
    expect(controller.visibleEdges, isNotEmpty);

    controller.searchProviderFilter = null;
    controller.searchKindFilter = null;
    expect(controller.visibleNodes.length, 3);
    expect(controller.positions['task-local'], originalPositions['task-local']);
    expect(controller.positions['email-gmail'], originalPositions['email-gmail']);
  });

  test('part_of between positioned tasks replaces the window and recomputes geometry', () async {
    final auth = _FakeAuth();
    final parent = _obj('parent', 'Parent');
    final child = _obj('child', 'Child');
    final partOf = _edge(id: 'part', sourceId: 'child', targetId: 'parent', type: 'part_of');
    var phase = 0;
    late _FakeApiClient client;
    client = _FakeApiClient((rootId) async {
      phase += 1;
      if (phase == 1) {
        return GraphWorkspaceOut(
          rootId: null,
          seedIds: ['parent', 'child'],
          nodes: [parent, child],
          edges: const [],
          truncated: false,
          windowIndex: 0,
          windowCount: 2,
          hasNextWindow: true,
          constellationRootIds: const ['parent', 'child'],
          semanticWindowComplete: true,
        );
      }
      return GraphWorkspaceOut(
        rootId: null,
        seedIds: ['parent'],
        nodes: [parent, child],
        edges: [partOf],
        truncated: false,
        windowIndex: 0,
        windowCount: 1,
        hasNextWindow: false,
        constellationRootIds: const ['parent'],
        semanticWindowComplete: true,
      );
    });
    final controller = GraphWorkspaceController(apiClient: client, authController: auth);
    await controller.loadOverview();
    final before = Map<String, Offset>.from(controller.positions);
    final stale = GraphLayout.computePositions(
      nodes: [parent, child],
      edges: [partOf],
      rootId: null,
      existing: before,
      freshRoot: false,
    );
    controller.upsertObject(_obj('phantom', 'Phantom'));
    controller.selectObject('child');
    controller.shouldFitAfterLayout = false;

    await controller.applyCreatedRelation(
      sourceId: 'child',
      sourceKind: 'task',
      target: parent,
      edge: partOf,
    );

    expect(controller.nodeById('phantom'), isNull);
    expect(controller.edges.map((edge) => edge.id), ['part']);
    expect(controller.positions['parent'], isNot(stale['parent']));
    expect(controller.positions['child'], stale['child']);
    expect(controller.shouldFitAfterLayout, isTrue);
    expect(controller.windowCount, 1);
    expect(controller.hasNextWindow, isFalse);
    expect(controller.constellationRootIds, ['parent']);
    expect(controller.semanticWindowComplete, isTrue);
    expect(controller.selectedObjectId, 'child');
    expect(controller.loadState, GraphWorkspaceLoadState.ready);
  });

  test('invalid overview window after part_of recovers to window 0 once', () async {
    final auth = _FakeAuth();
    final task = _obj('task', 'Task');
    late _FakeApiClient client;
    client = _FakeApiClient((rootId) async {
      if (client.requestedWindow == 4) {
        throw ValidationException('graph window index is out of range');
      }
      return GraphWorkspaceOut(
        rootId: null,
        seedIds: ['task'],
        nodes: [task],
        edges: const [],
        truncated: false,
        windowIndex: 0,
        windowCount: 1,
        semanticWindowComplete: true,
      );
    });
    final controller = GraphWorkspaceController(apiClient: client, authController: auth);
    await controller.loadOverview();
    controller.windowIndex = 4;
    final fetchesBefore = client.fetchCount;

    await controller.refreshAfterTaskTopologyMutation();

    expect(controller.windowIndex, 0);
    expect(controller.loadState, GraphWorkspaceLoadState.ready);
    expect(controller.errorMessage, isNull);
    expect(controller.positions.containsKey('task'), isTrue);
    expect(client.fetchCount - fetchesBefore, 2);
  });

  test('map-visible Task-to-Task relations fresh-relayout', () async {
    for (final type in ['related_to', 'references', 'depends_on']) {
      final auth = _FakeAuth();
      final left = _obj('left', 'Left');
      final right = _obj('right', 'Right');
      final edge = _edge(id: type, sourceId: 'left', targetId: 'right', type: type);
      var phase = 0;
      final controller = GraphWorkspaceController(
        apiClient: _FakeApiClient((rootId) async {
          phase += 1;
          return GraphWorkspaceOut(
            rootId: null,
            seedIds: const ['left'],
            nodes: [left, right],
            edges: phase == 1 ? const [] : [edge],
            truncated: false,
            semanticWindowComplete: true,
          );
        }),
        authController: auth,
      );
      await controller.loadOverview();
      final before = Map<String, Offset>.from(controller.positions);
      controller.shouldFitAfterLayout = false;
      await controller.applyCreatedRelation(
        sourceId: 'left',
        sourceKind: 'task',
        target: right,
        edge: edge,
      );
      expect(controller.positions['right'], isNot(before['right']), reason: type);
      expect(controller.shouldFitAfterLayout, isTrue, reason: type);
      expect(controller.edges.single.type, type);
    }
  });

  test('Task-to-Flow relation stays incremental', () async {
    final auth = _FakeAuth();
    final task = _obj('task', 'Task');
    final flow = _obj('flow', 'Flow', kind: 'note');
    final edge = _edge(id: 'ref', sourceId: 'task', targetId: 'flow', type: 'references');
    var phase = 0;
    final controller = GraphWorkspaceController(
      apiClient: _FakeApiClient((rootId) async {
        phase += 1;
        if (phase == 1) {
          return _workspace(nodes: [task]);
        }
        return GraphWorkspaceOut(
          rootId: null,
          seedIds: const ['task'],
          nodes: [task, flow],
          edges: [edge],
          truncated: false,
        );
      }),
      authController: auth,
    );
    await controller.loadOverview();
    final taskPosition = controller.positions['task'];
    controller.shouldFitAfterLayout = false;
    await controller.applyCreatedRelation(
      sourceId: 'task',
      sourceKind: 'task',
      target: flow,
      edge: edge,
    );
    expect(controller.positions['task'], taskPosition);
    expect(controller.positions.containsKey('flow'), isTrue);
    expect(controller.edges.single.id, 'ref');
    expect(controller.shouldFitAfterLayout, isFalse);
  });

  test('deleting part_of refreshes and fresh-relayouts the split', () async {
    final auth = _FakeAuth();
    final parent = _obj('parent', 'Parent');
    final child = _obj('child', 'Child');
    final partOf = _edge(id: 'part', sourceId: 'child', targetId: 'parent', type: 'part_of');
    var phase = 0;
    final controller = GraphWorkspaceController(
      apiClient: _FakeApiClient((rootId) async {
        phase += 1;
        return GraphWorkspaceOut(
          rootId: null,
          seedIds: const ['parent', 'child'],
          nodes: [parent, child],
          edges: phase == 1 ? [partOf] : const [],
          truncated: false,
          semanticWindowComplete: true,
        );
      }),
      authController: auth,
    );
    await controller.loadOverview();
    final before = Map<String, Offset>.from(controller.positions);
    await controller.applyDeletedRelation(partOf, sourceKind: 'task', targetKind: 'task');
    expect(controller.edges, isEmpty);
    expect(controller.positions['parent'], isNot(before['parent']));
    expect(controller.shouldFitAfterLayout, isTrue);
  });

  test('Task-to-Task proposal confirm and reject refresh topology', () async {
    final auth = _FakeAuth();
    final parent = _obj('parent', 'Parent');
    final child = _obj('child', 'Child');
    final proposed = _edge(
      id: 'part',
      sourceId: 'child',
      targetId: 'parent',
      type: 'part_of',
      state: 'proposed',
      origin: 'agent',
    );
    final confirmed = _edge(
      id: 'part',
      sourceId: 'child',
      targetId: 'parent',
      type: 'part_of',
      origin: 'agent',
    );
    var includeEdge = true;
    var fetches = 0;
    final controller = GraphWorkspaceController(
      apiClient: _FakeApiClient((rootId) async {
        fetches += 1;
        return GraphWorkspaceOut(
          rootId: null,
          seedIds: const ['parent'],
          nodes: [parent, child],
          edges: includeEdge ? [confirmed] : const [],
          truncated: false,
          semanticWindowComplete: true,
        );
      }),
      authController: auth,
    );
    await controller.loadOverview();
    final beforeConfirm = fetches;
    await controller.applyRelationDecision(
      previous: proposed,
      updated: confirmed,
      sourceKind: 'task',
      targetKind: 'task',
    );
    expect(fetches, beforeConfirm + 1);
    expect(controller.shouldFitAfterLayout, isTrue);
    expect(controller.edges.single.state, 'confirmed');

    includeEdge = false;
    await controller.applyRelationDecision(
      previous: confirmed,
      updated: _edge(
        id: 'part',
        sourceId: 'child',
        targetId: 'parent',
        type: 'part_of',
        state: 'rejected',
        origin: 'agent',
      ),
      sourceKind: 'task',
      targetKind: 'task',
    );
    expect(controller.edges, isEmpty);
    expect(controller.loadState, GraphWorkspaceLoadState.ready);
  });

  test('rooted topology mutation refreshes that root with fresh geometry', () async {
    final auth = _FakeAuth();
    final root = _obj('root', 'Root');
    final child = _obj('child', 'Child');
    final partOf = _edge(id: 'part', sourceId: 'child', targetId: 'root', type: 'part_of');
    var phase = 0;
    late _FakeApiClient client;
    client = _FakeApiClient((rootId) async {
      phase += 1;
      return GraphWorkspaceOut(
        rootId: 'root',
        seedIds: const ['root'],
        nodes: [root, child],
        edges: phase == 1 ? const [] : [partOf],
        truncated: false,
      );
    });
    final controller = GraphWorkspaceController(apiClient: client, authController: auth);
    await controller.reRoot('root');
    final beforeChild = controller.positions['child'];
    controller.selectObject('root');
    controller.shouldFitAfterLayout = false;
    await controller.applyCreatedRelation(
      sourceId: 'child',
      sourceKind: 'task',
      target: root,
      edge: partOf,
    );
    expect(client.requestedRootId, 'root');
    expect(controller.rootId, 'root');
    expect(controller.selectedObjectId, 'root');
    expect(controller.positions['child'], isNot(beforeChild));
    expect(controller.shouldFitAfterLayout, isTrue);
  });

  test('overview refresh failure after a successful write does not retry', () async {
    final auth = _FakeAuth();
    var fetches = 0;
    final controller = GraphWorkspaceController(
      apiClient: _FakeApiClient((rootId) async {
        fetches += 1;
        if (fetches > 1) {
          throw Exception('offline');
        }
        return _workspace(nodes: [_obj('task', 'Task')]);
      }),
      authController: auth,
    );
    await controller.loadOverview();
    expect(controller.positions.containsKey('task'), isTrue);
    await controller.refreshAfterTaskTopologyMutation();
    expect(fetches, 2);
    expect(controller.positions, isEmpty);
    expect(controller.loadState, GraphWorkspaceLoadState.error);
    expect(controller.errorMessage, taskTopologyRefreshFailureMessage);
  });

  test('fit transform leaves node coordinates unchanged', () {
    final positions = <String, Offset>{
      'a': const Offset(12, 24),
      'b': const Offset(400, 24),
    };
    final before = Map<String, Offset>.from(positions);
    GraphLayout.fitTransform(
      positions: positions,
      viewportSize: const Size(800, 600),
    );
    expect(positions, before);
  });

  test('fresh workspace projection keeps a Task daisy with its Direction', () async {
    final auth = _FakeAuth();
    final publications = _obj('publications', 'Publications');
    final academy = _obj('academy', 'Academy');
    final paper = _obj('paper', 'Paper');
    final partOf = _edge(
      id: 'part',
      sourceId: 'publications',
      targetId: 'academy',
      type: 'part_of',
    );
    final related = _edge(
      id: 'rel',
      sourceId: 'paper',
      targetId: 'publications',
      type: 'related_to',
    );
    final controller = GraphWorkspaceController(
      apiClient: _FakeApiClient((rootId) async {
        return GraphWorkspaceOut(
          rootId: null,
          seedIds: const ['academy'],
          nodes: [academy, publications, paper],
          edges: [partOf, related],
          truncated: false,
          semanticWindowComplete: true,
        );
      }),
      authController: auth,
    );
    await controller.loadOverview();
    final stale = {
      'academy': controller.positions['academy']!,
      'publications': const Offset(3000, 0),
      'paper': const Offset(6000, 800),
    };
    final shown = Map<String, Offset>.from(stale)..addAll(
      projectTaskMapHierarchy(
        nodes: controller.nodes,
        edges: controller.edges,
      ).positions,
    );
    final projection = projectTaskMapHierarchy(
      nodes: controller.nodes,
      edges: controller.edges,
    );
    expect(projection.components, hasLength(1));
    expect(projection.placements['publications']!.parentId, 'academy');
    expect(projection.placements.containsKey('paper'), isFalse);
    final paperDistance =
        (shown['paper']! - shown['publications']!).distance;
    expect(paperDistance, lessThan(1200));
    expect(shown['paper'], isNot(stale['paper']));
  });
}

SecretaryEdge _edge({
  required String id,
  required String sourceId,
  required String targetId,
  required String type,
  String state = 'confirmed',
  String origin = 'user',
}) {
  return SecretaryEdge(
    id: id,
    sourceId: sourceId,
    targetId: targetId,
    type: type,
    origin: origin,
    state: state,
    metadata: const {},
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  );
}

void _expectNoOverlaps(Map<String, Offset> positions) {
  final ids = positions.keys.toList();
  for (var i = 0; i < ids.length; i++) {
    for (var j = i + 1; j < ids.length; j++) {
      expect(
        GraphLayout.nodeRectsOverlap(positions[ids[i]]!, positions[ids[j]]!),
        isFalse,
        reason: 'overlap between ${ids[i]} and ${ids[j]}',
      );
    }
  }
}
