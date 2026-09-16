import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_error.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/graph/graph_layout.dart';
import 'package:personal_secretary/graph/graph_workspace_controller.dart';

class _FakeApiClient extends SecretaryApiClient {
  _FakeApiClient(this._handler);

  final Future<GraphWorkspaceOut> Function(String? rootId) _handler;

  @override
  Future<GraphWorkspaceOut> getGraphWorkspace({
    String? rootId,
    int? seedLimit,
    int? neighborLimit,
    int? nodeLimit,
  }) {
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
}) {
  return SecretaryObject(
    id: id,
    kind: 'task',
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

  test('mergeRelationContext keeps staged relation when refresh fails', () async {
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

    expect(controller.edges.length, 1);
    expect(controller.edges.first.id, 'e-new');
    expect(controller.positions.containsKey('source'), isTrue);
    expect(controller.positions.containsKey('target'), isTrue);
    expect(controller.edgeEndpointsPositioned(edge), isTrue);
    expect(controller.errorMessage, isNotNull);
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

  test('display filters hide nodes and edges without reloading layout', () async {
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
    controller.applyDisplayFilters();
    expect(controller.visibleNodes.map((n) => n.id).toList(),
        ['email-gmail', 'email-yandex']);
    expect(controller.visibleEdges, isEmpty);

    controller.searchProviderFilter = 'gmail';
    controller.applyDisplayFilters();
    expect(controller.visibleNodes.single.id, 'email-gmail');

    controller.searchProviderFilter = null;
    controller.applyDisplayFilters();
    expect(controller.visibleNodes.length, 2);

    controller.searchKindFilter = null;
    controller.applyDisplayFilters();
    expect(controller.visibleNodes.length, 3);
    expect(controller.positions['task-local'], originalPositions['task-local']);
    expect(controller.positions['email-gmail'], originalPositions['email-gmail']);
  });
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
