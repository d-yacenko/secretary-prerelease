import 'package:flutter/material.dart';

import '../api/api_error.dart';
import '../api/api_models.dart';
import '../api/secretary_api_client.dart';
import '../auth/auth_controller.dart';
import 'graph_layout.dart';
import 'graph_map_edge_presentation.dart';

enum GraphWorkspaceLoadState { idle, loading, ready, error }

enum GraphWorkspaceMode { tasks, people }

const String taskTopologyRefreshFailureMessage =
    'Связь сохранена, но граф не удалось обновить. Обновите обзор.';

const String localContextHideFailureMessage =
    'Не удалось скрыть связи. Обновите обзор и повторите.';

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
  GraphWorkspaceMode mode = GraphWorkspaceMode.tasks;
  String? errorMessage;
  String? rootId;
  bool truncated = false;
  List<PersonPromotionCandidate> promotionCandidates = const [];
  bool promotionCandidatesTruncated = false;
  List<PersonPromotionSuppression> promotionSuppressions = const [];
  int windowIndex = 0;
  int windowCount = 1;
  bool hasPreviousWindow = false;
  bool hasNextWindow = false;
  bool semanticWindowComplete = false;
  List<String> constellationRootIds = const [];
  String? selectedObjectId;
  String? selectedEdgeId;
  String? searchQuery;
  String? searchKindFilter;
  String? searchProviderFilter;
  bool shouldFitAfterLayout = false;

  final Map<String, SecretaryObject> _nodes = {};
  final Map<String, PersonPresentation> _people = {};
  final List<SecretaryEdge> _edges = [];
  final Map<String, Offset> _positions = {};
  List<String> _seedIds = const [];
  final List<String> _localContextAnchorIds = [];

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

  PersonPresentation? personFor(String id) => _people[id];
  List<String> get seedIds => List.unmodifiable(_seedIds);
  List<String> get localContextAnchorIds =>
      List.unmodifiable(_localContextAnchorIds);

  bool isLocalContextExpanded(String objectId) =>
      _localContextAnchorIds.contains(objectId);

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
    windowIndex = 0;
    windowCount = 1;
    hasPreviousWindow = false;
    hasNextWindow = false;
    semanticWindowComplete = false;
    selectedObjectId = null;
    selectedEdgeId = null;
    searchQuery = null;
    searchKindFilter = null;
    searchProviderFilter = null;
    shouldFitAfterLayout = false;
    _nodes.clear();
    _edges.clear();
    _positions.clear();
    _people.clear();
    _seedIds = const [];
    _localContextAnchorIds.clear();
    mode = GraphWorkspaceMode.tasks;
    notifyListeners();
  }

  Future<void> setMode(GraphWorkspaceMode next) async {
    if (mode == next || loadState == GraphWorkspaceLoadState.loading) {
      return;
    }
    mode = next;
    selectedObjectId = null;
    selectedEdgeId = null;
    searchKindFilter = null;
    searchProviderFilter = null;
    await loadOverview();
  }

  Future<GraphWorkspaceOut> _fetchWorkspace({
    String? rootId,
    String? query,
    int? windowIndex,
  }) {
    if (mode == GraphWorkspaceMode.people) {
      return _apiClient.getPeopleWorkspace(rootId: rootId, query: query);
    }
    return _apiClient.getGraphWorkspace(
      rootId: rootId,
      windowIndex: rootId == null ? windowIndex : null,
    );
  }

  Future<void> refreshCurrentWorkspace() async {
    if (loadState == GraphWorkspaceLoadState.loading) {
      return;
    }
    if (rootId == null) {
      await loadOverviewWindow(windowIndex);
      return;
    }
    await _refreshRooted(rootId!);
  }

  Future<void> loadOverview() async {
    if (loadState == GraphWorkspaceLoadState.loading) {
      return;
    }
    await _loadOverviewInternal(setLoading: true, windowIndex: 0);
  }

  Future<void> loadOverviewWindow(int index) async {
    if (loadState == GraphWorkspaceLoadState.loading) {
      return;
    }
    await _loadOverviewInternal(
      setLoading: true,
      windowIndex: index,
      preserveSelection: true,
    );
  }

  Future<void> loadNextOverviewWindow() async {
    if (!hasNextWindow || loadState == GraphWorkspaceLoadState.loading) {
      return;
    }
    await loadOverviewWindow(windowIndex + 1);
  }

  Future<void> loadPreviousOverviewWindow() async {
    if (!hasPreviousWindow || loadState == GraphWorkspaceLoadState.loading) {
      return;
    }
    await loadOverviewWindow(windowIndex - 1);
  }

  Future<void> _loadOverviewFromMissingRoot() async {
    try {
      final workspace = await _fetchWorkspace();
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

  Future<void> _loadOverviewInternal({
    required bool setLoading,
    int windowIndex = 0,
    bool preserveSelection = false,
  }) async {
    if (setLoading) {
      loadState = GraphWorkspaceLoadState.loading;
      errorMessage = null;
      notifyListeners();
    }
    try {
      final previousSelection = selectedObjectId;
      final workspace = await _fetchWorkspace(windowIndex: windowIndex);
      final keptSelection = preserveSelection &&
              previousSelection != null &&
              workspace.nodes.any((node) => node.id == previousSelection)
          ? previousSelection
          : null;
      _replaceWorkspaceState(
        workspace: workspace,
        layoutRoot: null,
        freshRoot: true,
        rootIdAfter: null,
        selectObjectId: keptSelection,
        fitAfterLayout: true,
      );
      loadState = GraphWorkspaceLoadState.ready;
    } on AuthenticationException {
      _authController.handleAuthenticationFailure();
    } on ApiException catch (error) {
      loadState = GraphWorkspaceLoadState.error;
      errorMessage = _workspaceErrorMessage(error);
    } catch (_) {
      loadState = GraphWorkspaceLoadState.error;
      errorMessage = 'Failed to load graph workspace';
    }
    notifyListeners();
  }

  String _workspaceErrorMessage(ApiException error) {
    if (error.message.toLowerCase().contains('too large for complete overview')) {
      return 'Это соцветие слишком велико для полного обзора. Нужен отдельный сфокусированный вид.';
    }
    return error.message;
  }

  Future<void> reRoot(String objectId) async {
    if (loadState == GraphWorkspaceLoadState.loading) {
      return;
    }
    loadState = GraphWorkspaceLoadState.loading;
    errorMessage = null;
    notifyListeners();
    try {
      final workspace = await _fetchWorkspace(rootId: objectId);
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
      errorMessage = _workspaceErrorMessage(error);
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
      final workspace = await _fetchWorkspace(rootId: objectId);
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
      final workspace = await _fetchWorkspace(rootId: selected.id);
      _mergeWorkspace(workspace, expandAround: selected.id, notify: false);
      if (!_localContextAnchorIds.contains(selected.id)) {
        _localContextAnchorIds.add(selected.id);
      }
      errorMessage = null;
      notifyListeners();
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

  /// Removes one explicit local-context overlay and rebuilds the canvas from
  /// the authoritative base plus every remaining overlay, in activation order.
  Future<void> hideLocalContext(String objectId) async {
    if (!_localContextAnchorIds.contains(objectId)) {
      return;
    }
    final remaining = [
      for (final id in _localContextAnchorIds)
        if (id != objectId) id,
    ];
    final baseRootId = rootId;
    final baseWindow = windowIndex;
    final previousSelection = selectedObjectId;
    final previousEdge = selectedEdgeId;
    try {
      final base = await _readHideBase(
        baseRootId: baseRootId,
        baseWindow: baseWindow,
      );
      if (base == null) {
        return;
      }
      final replays = <({String id, GraphWorkspaceOut workspace})>[];
      for (final anchorId in remaining) {
        final workspace = await _readReplay(anchorId);
        if (workspace == null) {
          continue;
        }
        replays.add((id: anchorId, workspace: workspace));
      }
      _installHideRebuild(
        base: base,
        rooted: baseRootId != null,
        rootId: baseRootId,
        replays: replays,
        previousSelection: previousSelection,
        previousEdge: previousEdge,
      );
    } on AuthenticationException {
      _authController.handleAuthenticationFailure();
    } catch (_) {
      errorMessage = localContextHideFailureMessage;
      notifyListeners();
    }
  }

  bool relationInvalidatesTaskTopology({
    required String type,
    String? sourceKind,
    String? targetKind,
  }) {
    if (mode != GraphWorkspaceMode.tasks) {
      return false;
    }
    if (type == 'part_of') {
      return true;
    }
    return taskToTaskRelationVisibleOnTasksMap(
      type: type,
      sourceKind: sourceKind,
      targetKind: targetKind,
    );
  }

  Future<void> applyCreatedRelation({
    required String sourceId,
    required String sourceKind,
    SecretaryObject? target,
    required SecretaryEdge edge,
  }) async {
    final targetKind = target?.kind ?? nodeById(edge.targetId)?.kind;
    if (relationInvalidatesTaskTopology(
      type: edge.type,
      sourceKind: sourceKind,
      targetKind: targetKind,
    )) {
      await refreshAfterTaskTopologyMutation();
      return;
    }
    await mergeRelationContext(sourceId, target: target, edge: edge);
  }

  Future<void> applyDeletedRelation(
    SecretaryEdge edge, {
    String? sourceKind,
    String? targetKind,
  }) async {
    if (relationInvalidatesTaskTopology(
      type: edge.type,
      sourceKind: sourceKind ?? nodeById(edge.sourceId)?.kind,
      targetKind: targetKind ?? nodeById(edge.targetId)?.kind,
    )) {
      await refreshAfterTaskTopologyMutation();
      return;
    }
    removeEdge(edge.id);
  }

  Future<void> applyRelationDecision({
    required SecretaryEdge previous,
    required SecretaryEdge updated,
    String? sourceKind,
    String? targetKind,
  }) async {
    if (relationInvalidatesTaskTopology(
      type: previous.type,
      sourceKind: sourceKind ?? nodeById(previous.sourceId)?.kind,
      targetKind: targetKind ?? nodeById(previous.targetId)?.kind,
    )) {
      await refreshAfterTaskTopologyMutation();
      return;
    }
    if (updated.state == 'rejected') {
      removeEdge(previous.id);
    } else {
      upsertEdge(updated);
    }
  }

  /// Authoritative replace of the current overview window or rooted workspace.
  /// Task coordinates are recomputed; the camera fit is requested afterwards.
  Future<void> refreshAfterTaskTopologyMutation() async {
    if (mode != GraphWorkspaceMode.tasks) {
      return;
    }
    if (rootId != null) {
      await _refreshRootedAfterTopology(rootId!);
      return;
    }
    await _refreshOverviewAfterTopology();
  }

  Future<void> _refreshOverviewAfterTopology() async {
    final index = windowIndex;
    loadState = GraphWorkspaceLoadState.loading;
    errorMessage = null;
    notifyListeners();
    try {
      await _installFreshOverview(index);
      loadState = GraphWorkspaceLoadState.ready;
    } on AuthenticationException {
      _authController.handleAuthenticationFailure();
    } on ApiException catch (error) {
      if (_windowIndexOutOfRange(error) && index != 0) {
        try {
          await _installFreshOverview(0);
          loadState = GraphWorkspaceLoadState.ready;
          errorMessage = null;
        } catch (_) {
          _failTaskTopologyRefresh();
          return;
        }
      } else {
        _failTaskTopologyRefresh();
        return;
      }
    } catch (_) {
      _failTaskTopologyRefresh();
      return;
    }
    notifyListeners();
  }

  Future<void> _refreshRootedAfterTopology(String objectId) async {
    loadState = GraphWorkspaceLoadState.loading;
    errorMessage = null;
    notifyListeners();
    try {
      final workspace = await _fetchWorkspace(rootId: objectId);
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
      return;
    } catch (_) {
      _failTaskTopologyRefresh();
      return;
    }
    notifyListeners();
  }

  Future<void> _installFreshOverview(int index) async {
    final previousSelection = selectedObjectId;
    final workspace = await _fetchWorkspace(windowIndex: index);
    final keptSelection = previousSelection != null &&
            workspace.nodes.any((node) => node.id == previousSelection)
        ? previousSelection
        : null;
    _replaceWorkspaceState(
      workspace: workspace,
      layoutRoot: null,
      freshRoot: true,
      rootIdAfter: null,
      selectObjectId: keptSelection,
      fitAfterLayout: true,
    );
  }

  bool _windowIndexOutOfRange(ApiException error) {
    return error.message.toLowerCase().contains('window index is out of range');
  }

  /// Null means the rooted base was gone and the overview fallback already ran.
  Future<GraphWorkspaceOut?> _readHideBase({
    required String? baseRootId,
    required int baseWindow,
  }) async {
    if (baseRootId == null) {
      try {
        return await _fetchWorkspace(windowIndex: baseWindow);
      } on ApiException catch (error) {
        if (_windowIndexOutOfRange(error) && baseWindow != 0) {
          return await _fetchWorkspace(windowIndex: 0);
        }
        rethrow;
      }
    }
    try {
      final workspace = await _fetchWorkspace(rootId: baseRootId);
      if (!_replayAnchorPresent(workspace, baseRootId)) {
        await _loadOverviewFromMissingRoot();
        return null;
      }
      return workspace;
    } on NotFoundException {
      await _loadOverviewFromMissingRoot();
      return null;
    }
  }

  Future<GraphWorkspaceOut?> _readReplay(String anchorId) async {
    try {
      final workspace = await _fetchWorkspace(rootId: anchorId);
      if (!_replayAnchorPresent(workspace, anchorId)) {
        return null;
      }
      return workspace;
    } on NotFoundException {
      return null;
    }
  }

  bool _replayAnchorPresent(GraphWorkspaceOut workspace, String objectId) {
    for (final node in workspace.nodes) {
      if (node.id == objectId) {
        return !node.isDeletedTask;
      }
    }
    return false;
  }

  void _installHideRebuild({
    required GraphWorkspaceOut base,
    required bool rooted,
    required String? rootId,
    required List<({String id, GraphWorkspaceOut workspace})> replays,
    required String? previousSelection,
    required String? previousEdge,
  }) {
    _replaceWorkspaceState(
      workspace: base,
      layoutRoot: rooted ? rootId : null,
      freshRoot: true,
      rootIdAfter: rooted ? rootId : null,
      selectObjectId: null,
      fitAfterLayout: true,
    );
    _localContextAnchorIds.addAll(replays.map((replay) => replay.id));
    for (final replay in replays) {
      _mergeWorkspace(
        replay.workspace,
        expandAround: replay.id,
        notify: false,
      );
    }
    selectedObjectId =
        previousSelection != null && _nodes.containsKey(previousSelection)
            ? previousSelection
            : null;
    selectedEdgeId =
        previousEdge != null && _edges.any((edge) => edge.id == previousEdge)
            ? previousEdge
            : null;
    shouldFitAfterLayout = true;
    loadState = GraphWorkspaceLoadState.ready;
    errorMessage = null;
    notifyListeners();
  }

  void _failTaskTopologyRefresh() {
    _positions.clear();
    loadState = GraphWorkspaceLoadState.error;
    errorMessage = taskTopologyRefreshFailureMessage;
    notifyListeners();
  }

  Future<void> mergeRelationContext(
    String sourceId, {
    SecretaryObject? target,
    SecretaryEdge? edge,
  }) async {
    final sourceKind = nodeById(sourceId)?.kind;
    final targetKind = target?.kind ?? (edge == null ? null : nodeById(edge.targetId)?.kind);
    if (edge != null &&
        relationInvalidatesTaskTopology(
          type: edge.type,
          sourceKind: sourceKind,
          targetKind: targetKind,
        )) {
      await refreshAfterTaskTopologyMutation();
      return;
    }
    if (edge != null) {
      _stageCreatedRelation(sourceId, target, edge);
    } else if (target != null) {
      _nodes[target.id] = target;
    }
    try {
      final workspace = await _fetchWorkspace(rootId: sourceId);
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
    _people.clear();
    _applyWorkspace(workspace, layoutRoot: layoutRoot, freshRoot: freshRoot);
    rootId = rootIdAfter;
    truncated = workspace.truncated;
    promotionCandidates = List<PersonPromotionCandidate>.from(workspace.promotionCandidates);
    promotionCandidatesTruncated = workspace.promotionCandidatesTruncated;
    promotionSuppressions = List<PersonPromotionSuppression>.from(
      workspace.promotionSuppressions,
    );
    windowIndex = workspace.windowIndex;
    windowCount = workspace.windowCount;
    hasPreviousWindow = workspace.hasPreviousWindow;
    hasNextWindow = workspace.hasNextWindow;
    semanticWindowComplete = workspace.semanticWindowComplete;
    constellationRootIds = List<String>.from(workspace.constellationRootIds);
    selectedObjectId = selectObjectId;
    selectedEdgeId = null;
    shouldFitAfterLayout = fitAfterLayout;
    _localContextAnchorIds.clear();
  }

  void _mergeWorkspace(
    GraphWorkspaceOut workspace, {
    required String expandAround,
    bool notify = true,
  }) {
    truncated = workspace.truncated;
    for (final node in workspace.nodes) {
      _nodes[node.id] = node;
    }
    for (final person in workspace.people) {
      _people[person.personId] = person;
    }
    _seedIds = List<String>.from(workspace.seedIds);
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
    if (notify) {
      notifyListeners();
    }
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
    for (final person in workspace.people) {
      _people[person.personId] = person;
    }
    _seedIds = List<String>.from(workspace.seedIds);
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
