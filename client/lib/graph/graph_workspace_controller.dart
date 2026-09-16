import 'package:flutter/material.dart';

import '../api/api_error.dart';
import '../api/api_models.dart';
import '../api/secretary_api_client.dart';
import '../auth/auth_controller.dart';
import 'graph_layout.dart';

enum GraphWorkspaceLoadState { idle, loading, ready, error }

const Set<String> _terminalTaskStatusesForReads = {
  'done',
  'completed',
  'cancelled',
  'archived',
  'deleted',
};

class GraphWorkspaceController extends ChangeNotifier {
  GraphWorkspaceController({
    required SecretaryApiClient apiClient,
    required AuthController authController,
  })  : _apiClient = apiClient,
        _authController = authController;

  final SecretaryApiClient _apiClient;
  final AuthController _authController;

  GraphWorkspaceLoadState loadState = GraphWorkspaceLoadState.idle;
  String? errorMessage;
  String? rootId;
  bool truncated = false;
  String? selectedObjectId;
  String? selectedEdgeId;
  String? searchQuery;
  String? searchKindFilter;
  String? searchProviderFilter;
  bool shouldFitAfterLayout = false;

  final Map<String, SecretaryObject> _nodes = {};
  final List<SecretaryEdge> _edges = [];
  final Map<String, Offset> _positions = {};

  List<SecretaryObject> get nodes => _nodes.values.toList();
  List<SecretaryObject> get visibleNodes =>
      _nodes.values.where(_matchesDisplayFilters).toList();
  bool get hasActiveDisplayFilters =>
      searchKindFilter != null || searchProviderFilter != null;
  SecretaryObject? nodeById(String id) => _nodes[id];
  List<SecretaryEdge> get edges => List.unmodifiable(_edges);
  List<SecretaryEdge> get visibleEdges {
    final visibleIds = visibleNodes.map((node) => node.id).toSet();
    return _edges
        .where(
          (edge) =>
              visibleIds.contains(edge.sourceId) &&
              visibleIds.contains(edge.targetId),
        )
        .toList();
  }
  Map<String, Offset> get positions => Map.unmodifiable(_positions);
  Map<String, Offset> get visiblePositions {
    final visibleIds = visibleNodes.map((node) => node.id).toSet();
    return Map.fromEntries(
      _positions.entries.where((entry) => visibleIds.contains(entry.key)),
    );
  }

  SecretaryObject? get selectedObject =>
      selectedObjectId == null ? null : _nodes[selectedObjectId!];

  SecretaryEdge? get selectedEdge {
    if (selectedEdgeId == null) {
      return null;
    }
    for (final edge in _edges) {
      if (edge.id == selectedEdgeId) {
        return edge;
      }
    }
    return null;
  }

  void resetSession() {
    loadState = GraphWorkspaceLoadState.idle;
    errorMessage = null;
    rootId = null;
    truncated = false;
    selectedObjectId = null;
    selectedEdgeId = null;
    searchQuery = null;
    searchKindFilter = null;
    searchProviderFilter = null;
    shouldFitAfterLayout = false;
    _nodes.clear();
    _edges.clear();
    _positions.clear();
    notifyListeners();
  }

  Future<void> refreshCurrentWorkspace() async {
    if (loadState == GraphWorkspaceLoadState.loading) {
      return;
    }
    if (rootId == null) {
      await loadOverview();
      return;
    }
    await _refreshRooted(rootId!);
  }

  Future<void> loadOverview() async {
    if (loadState == GraphWorkspaceLoadState.loading) {
      return;
    }
    await _loadOverviewInternal(setLoading: true);
  }

  Future<void> _loadOverviewFromMissingRoot() async {
    try {
      final workspace = await _apiClient.getGraphWorkspace();
      _replaceWorkspaceState(
        workspace: workspace,
        layoutRoot: null,
        freshRoot: true,
        rootIdAfter: null,
        selectObjectId: null,
        fitAfterLayout: true,
      );
      loadState = GraphWorkspaceLoadState.ready;
      errorMessage = 'Root object is no longer available in graph workspace';
    } on AuthenticationException {
      _authController.handleAuthenticationFailure();
    } on ApiException catch (error) {
      loadState = GraphWorkspaceLoadState.error;
      errorMessage = error.message;
    } catch (_) {
      loadState = GraphWorkspaceLoadState.error;
      errorMessage = 'Failed to load graph workspace';
    }
    notifyListeners();
  }

  Future<void> _loadOverviewInternal({required bool setLoading}) async {
    if (setLoading) {
      loadState = GraphWorkspaceLoadState.loading;
      errorMessage = null;
      notifyListeners();
    }
    try {
      final workspace = await _apiClient.getGraphWorkspace();
      _replaceWorkspaceState(
        workspace: workspace,
        layoutRoot: null,
        freshRoot: true,
        rootIdAfter: null,
        selectObjectId: null,
        fitAfterLayout: true,
      );
      loadState = GraphWorkspaceLoadState.ready;
    } on AuthenticationException {
      _authController.handleAuthenticationFailure();
    } on ApiException catch (error) {
      loadState = GraphWorkspaceLoadState.error;
      errorMessage = error.message;
    } catch (_) {
      loadState = GraphWorkspaceLoadState.error;
      errorMessage = 'Failed to load graph workspace';
    }
    notifyListeners();
  }

  Future<void> reRoot(String objectId) async {
    if (loadState == GraphWorkspaceLoadState.loading) {
      return;
    }
    loadState = GraphWorkspaceLoadState.loading;
    errorMessage = null;
    notifyListeners();
    try {
      final workspace = await _apiClient.getGraphWorkspace(rootId: objectId);
      _replaceWorkspaceState(
        workspace: workspace,
        layoutRoot: objectId,
        freshRoot: true,
        rootIdAfter: objectId,
        selectObjectId: objectId,
        fitAfterLayout: true,
      );
      loadState = GraphWorkspaceLoadState.ready;
    } on AuthenticationException {
      _authController.handleAuthenticationFailure();
    } on ApiException catch (error) {
      loadState = GraphWorkspaceLoadState.ready;
      errorMessage = error.message;
    } catch (_) {
      loadState = GraphWorkspaceLoadState.ready;
      errorMessage = 'Failed to load graph workspace';
    }
    notifyListeners();
  }

  Future<void> _refreshRooted(String objectId) async {
    if (loadState == GraphWorkspaceLoadState.loading) {
      return;
    }
    loadState = GraphWorkspaceLoadState.loading;
    errorMessage = null;
    notifyListeners();
    try {
      final workspace = await _apiClient.getGraphWorkspace(rootId: objectId);
      SecretaryObject? rootNode;
      for (final node in workspace.nodes) {
        if (node.id == objectId) {
          rootNode = node;
          break;
        }
      }
      if (rootNode == null || rootNode.isDeletedTask) {
        await _loadOverviewFromMissingRoot();
        return;
      }
      final preservedSelection = selectedObjectId;
      _replaceWorkspaceState(
        workspace: workspace,
        layoutRoot: objectId,
        freshRoot: true,
        rootIdAfter: objectId,
        selectObjectId: preservedSelection != null &&
                workspace.nodes.any((node) => node.id == preservedSelection)
            ? preservedSelection
            : objectId,
        fitAfterLayout: true,
      );
      loadState = GraphWorkspaceLoadState.ready;
    } on AuthenticationException {
      _authController.handleAuthenticationFailure();
    } on NotFoundException {
      await _loadOverviewFromMissingRoot();
    } on NetworkException catch (error) {
      loadState = GraphWorkspaceLoadState.ready;
      errorMessage = error.message;
    } on ServerException catch (error) {
      loadState = GraphWorkspaceLoadState.ready;
      errorMessage = error.message;
    } on ApiException catch (error) {
      loadState = GraphWorkspaceLoadState.ready;
      errorMessage = error.message;
    } catch (_) {
      loadState = GraphWorkspaceLoadState.ready;
      errorMessage = 'Failed to load graph workspace';
    }
    notifyListeners();
  }

  Future<void> expandSelected() async {
    final selected = selectedObject;
    if (selected == null) {
      return;
    }
    try {
      final workspace = await _apiClient.getGraphWorkspace(rootId: selected.id);
      _mergeWorkspace(workspace, expandAround: selected.id);
      errorMessage = null;
    } on AuthenticationException {
      _authController.handleAuthenticationFailure();
    } on ApiException catch (error) {
      errorMessage = error.message;
      notifyListeners();
    } catch (_) {
      errorMessage = 'Failed to expand neighbors';
      notifyListeners();
    }
  }

  Future<void> mergeRelationContext(
    String sourceId, {
    SecretaryObject? target,
    SecretaryEdge? edge,
  }) async {
    if (edge != null) {
      _stageCreatedRelation(sourceId, target, edge);
    } else if (target != null) {
      _nodes[target.id] = target;
    }
    try {
      final workspace = await _apiClient.getGraphWorkspace(rootId: sourceId);
      _mergeWorkspace(workspace, expandAround: sourceId);
      errorMessage = null;
    } on AuthenticationException {
      _authController.handleAuthenticationFailure();
    } on ApiException catch (error) {
      errorMessage = error.message;
      notifyListeners();
    } catch (_) {
      errorMessage = 'Failed to refresh graph after relation change';
      notifyListeners();
    }
  }

  void _stageCreatedRelation(
    String sourceId,
    SecretaryObject? target,
    SecretaryEdge edge,
  ) {
    if (target != null) {
      _nodes[target.id] = target;
    }
    if (!_positions.containsKey(sourceId)) {
      _positions[sourceId] = const Offset(0, 0);
    }
    if (target != null) {
      final layoutNodes = <SecretaryObject>[];
      final source = _nodes[sourceId];
      if (source != null) {
        layoutNodes.add(source);
      }
      layoutNodes.add(target);
      final computed = GraphLayout.computePositions(
        nodes: layoutNodes,
        edges: _edges,
        rootId: sourceId,
        existing: _positions,
        freshRoot: false,
      );
      _positions.addAll(computed);
    }
    addEdge(edge);
  }

  bool edgeEndpointsPositioned(SecretaryEdge edge) {
    return _positions.containsKey(edge.sourceId) &&
        _positions.containsKey(edge.targetId);
  }

  Future<void> removeObjectImmediately(String objectId) async {
    _removeObjectFromWorkspace(objectId);
    if (rootId == objectId) {
      await loadOverview();
    }
    notifyListeners();
  }

  Future<void> applyTaskMutation(SecretaryObject object) async {
    if (object.kind != 'task') {
      _nodes[object.id] = object;
      notifyListeners();
      return;
    }

    if (object.isDeletedTask) {
      _removeObjectFromWorkspace(object.id);
      if (rootId == object.id) {
        await loadOverview();
      }
      return;
    }

    if (rootId == null && _isTerminalForActiveOverview(object.status)) {
      _removeObjectFromWorkspace(object.id);
      return;
    }

    _nodes[object.id] = object;
    notifyListeners();
  }

  void selectObject(String? objectId) {
    selectedObjectId = objectId;
    selectedEdgeId = null;
    notifyListeners();
  }

  void selectEdge(String? edgeId) {
    selectedEdgeId = edgeId;
    notifyListeners();
  }

  void upsertObject(SecretaryObject object) {
    _nodes[object.id] = object;
    notifyListeners();
  }

  void removeEdge(String edgeId) {
    _edges.removeWhere((edge) => edge.id == edgeId);
    if (selectedEdgeId == edgeId) {
      selectedEdgeId = null;
    }
    notifyListeners();
  }

  void addEdge(SecretaryEdge edge) {
    final exists = _edges.any((item) => item.id == edge.id);
    if (!exists) {
      _edges.add(edge);
    }
    notifyListeners();
  }

  void upsertEdge(SecretaryEdge edge) {
    _edges.removeWhere((item) => item.id == edge.id);
    _edges.add(edge);
    notifyListeners();
  }

  void clearFitRequest() {
    shouldFitAfterLayout = false;
  }

  void applyDisplayFilters() {
    final selected = selectedObject;
    if (selected != null && !_matchesDisplayFilters(selected)) {
      selectedObjectId = null;
      selectedEdgeId = null;
    }
    notifyListeners();
  }

  bool _matchesDisplayFilters(SecretaryObject node) {
    if (searchKindFilter != null && node.kind != searchKindFilter) {
      return false;
    }
    if (searchProviderFilter != null && node.provider != searchProviderFilter) {
      return false;
    }
    return true;
  }

  void _removeObjectFromWorkspace(String objectId) {
    _nodes.remove(objectId);
    _positions.remove(objectId);
    _edges.removeWhere(
      (edge) => edge.sourceId == objectId || edge.targetId == objectId,
    );
    if (selectedObjectId == objectId) {
      selectedObjectId = null;
    }
    if (selectedEdgeId != null) {
      final edge = selectedEdge;
      if (edge == null ||
          edge.sourceId == objectId ||
          edge.targetId == objectId) {
        selectedEdgeId = null;
      }
    }
    notifyListeners();
  }

  bool _isTerminalForActiveOverview(String? status) {
    return status != null && _terminalTaskStatusesForReads.contains(status);
  }

  void _replaceWorkspaceState({
    required GraphWorkspaceOut workspace,
    required String? layoutRoot,
    required bool freshRoot,
    required String? rootIdAfter,
    required String? selectObjectId,
    required bool fitAfterLayout,
  }) {
    _nodes.clear();
    _edges.clear();
    _positions.clear();
    _applyWorkspace(workspace, layoutRoot: layoutRoot, freshRoot: freshRoot);
    rootId = rootIdAfter;
    truncated = workspace.truncated;
    selectedObjectId = selectObjectId;
    selectedEdgeId = null;
    shouldFitAfterLayout = fitAfterLayout;
  }

  void _mergeWorkspace(GraphWorkspaceOut workspace, {required String expandAround}) {
    truncated = workspace.truncated;
    for (final node in workspace.nodes) {
      _nodes[node.id] = node;
    }
    for (final edge in workspace.edges) {
      final exists = _edges.any((item) => item.id == edge.id);
      if (!exists) {
        _edges.add(edge);
      }
    }
    final computed = GraphLayout.computePositions(
      nodes: workspace.nodes,
      edges: workspace.edges,
      rootId: expandAround,
      existing: _positions,
      freshRoot: false,
    );
    _positions.addAll(computed);
    loadState = GraphWorkspaceLoadState.ready;
    notifyListeners();
  }

  void _applyWorkspace(
    GraphWorkspaceOut workspace, {
    required String? layoutRoot,
    required bool freshRoot,
  }) {
    truncated = workspace.truncated;
    for (final node in workspace.nodes) {
      _nodes[node.id] = node;
    }
    for (final edge in workspace.edges) {
      final exists = _edges.any((item) => item.id == edge.id);
      if (!exists) {
        _edges.add(edge);
      }
    }
    final computed = GraphLayout.computePositions(
      nodes: workspace.nodes,
      edges: workspace.edges,
      rootId: layoutRoot,
      existing: _positions,
      freshRoot: freshRoot,
    );
    _positions.addAll(computed);
  }
}
