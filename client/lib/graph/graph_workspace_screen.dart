import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../api/api_error.dart';
import '../api/api_models.dart';
import '../api/secretary_api_client.dart';
import '../assistant/assistant_controller.dart';
import '../auth/auth_controller.dart';
import '../capture/capture_controller.dart';
import '../navigation/secretary_navigation.dart';
import '../navigation/source_navigation_presenter.dart';
import '../navigation/source_navigation_service.dart';
import '../tasks/task_management_actions.dart';
import '../ui/compact_object_filters.dart';
import '../ui/domain_labels.dart';
import '../ui/object_dates.dart';
import '../ui/object_bookmark.dart';
import '../ui/object_bookmark_controller.dart';
import '../ui/object_presentation.dart';
import '../ui/object_visuals.dart' show providerBadge;
import 'fcose_graph_refiner.dart';
import 'focus_lod.dart';
import 'graph_geometry.dart';
import 'graph_map_edge_presentation.dart';
import 'hybrid_focus_lod.dart';
import 'graph_layout.dart';
import 'graph_workspace_controller.dart';
import 'task_map_hierarchy.dart';
import 'task_profile_section.dart';

class GraphWorkspaceScreen extends StatefulWidget {
  const GraphWorkspaceScreen({
    super.key,
    required this.controller,
    required this.apiClient,
    required this.authController,
    required this.captureController,
    required this.assistantController,
    required this.onAskSecretary,
    this.bookmarkController,
    this.geometryRefiner,
  });

  final GraphWorkspaceController controller;
  final SecretaryApiClient apiClient;
  final AuthController authController;
  final CaptureController captureController;
  final AssistantController assistantController;
  final void Function(SecretaryObject object) onAskSecretary;
  final ObjectBookmarkController? bookmarkController;

  /// Test hook. Production uses [FcoseGraphRefiner] for the selected submode.
  final GraphGeometryRefiner? geometryRefiner;

  @override
  State<GraphWorkspaceScreen> createState() => _GraphWorkspaceScreenState();
}

class _GraphWorkspaceScreenState extends State<GraphWorkspaceScreen> {
  final TransformationController _transform = TransformationController();
  final TextEditingController _searchController = TextEditingController();
  List<SecretaryObject> _searchResults = [];
  bool _searching = false;
  SearchFacetsOut? _searchFacets;
  Size? _canvasViewportSize;
  FcoseRefinementMode _fcoseMode = FcoseRefinementMode.preserve;
  String? _hybridWarning;
  Rect? _hybridGraphBounds;
  Set<String> _reconciledVisibleIds = {};
  Set<String>? _inFlightReconcileIds;
  var _bookmarkReconcileScheduled = false;

  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_onControllerChanged);
    widget.bookmarkController?.addListener(_onBookmarksChanged);
    _loadFacets();
    _scheduleVisibleBookmarkReconcile();
  }

  Future<void> _loadFacets() async {
    try {
      final facets = await widget.apiClient.getSearchFacets();
      if (mounted) {
        setState(() => _searchFacets = facets);
      }
    } catch (_) {}
  }

  @override
  void didUpdateWidget(covariant GraphWorkspaceScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.controller != widget.controller) {
      oldWidget.controller.removeListener(_onControllerChanged);
      widget.controller.addListener(_onControllerChanged);
      _reconciledVisibleIds = {};
      _scheduleVisibleBookmarkReconcile();
    }
    if (oldWidget.bookmarkController != widget.bookmarkController) {
      oldWidget.bookmarkController?.removeListener(_onBookmarksChanged);
      widget.bookmarkController?.addListener(_onBookmarksChanged);
      _reconciledVisibleIds = {};
      _scheduleVisibleBookmarkReconcile();
    }
  }

  @override
  void dispose() {
    widget.controller.removeListener(_onControllerChanged);
    widget.bookmarkController?.removeListener(_onBookmarksChanged);
    _searchController.dispose();
    _transform.dispose();
    super.dispose();
  }

  void _onBookmarksChanged() {
    if (mounted) {
      setState(() {});
    }
  }

  void _onControllerChanged() {
    if (mounted) {
      setState(() {});
    }
    _scheduleVisibleBookmarkReconcile();
  }

  void _scheduleVisibleBookmarkReconcile() {
    if (widget.bookmarkController == null) {
      return;
    }
    if (_bookmarkReconcileScheduled) {
      return;
    }
    _bookmarkReconcileScheduled = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _bookmarkReconcileScheduled = false;
      if (!mounted) {
        return;
      }
      _reconcileVisibleBookmarks();
    });
  }

  Future<void> _reconcileVisibleBookmarks() async {
    final bookmarks = widget.bookmarkController;
    if (bookmarks == null) {
      return;
    }
    final ids = widget.controller.visibleNodes.map((node) => node.id).toSet();
    if (setEquals(ids, _reconciledVisibleIds)) {
      return;
    }
    if (_inFlightReconcileIds != null) {
      return;
    }
    final requested = Set<String>.from(ids);
    _inFlightReconcileIds = requested;
    try {
      final ok = await bookmarks.reconcileVisible(requested);
      if (!mounted) {
        return;
      }
      final current = widget.controller.visibleNodes
          .map((node) => node.id)
          .toSet();
      if (!ok) {
        if (!setEquals(current, requested)) {
          _scheduleVisibleBookmarkReconcile();
        }
        return;
      }
      if (!setEquals(current, requested)) {
        _scheduleVisibleBookmarkReconcile();
        return;
      }
      _reconciledVisibleIds = requested;
    } finally {
      _inFlightReconcileIds = null;
    }
  }

  Future<void> _runSearch(String query) async {
    if (query.trim().isEmpty) {
      setState(() {
        _searchResults = [];
        _searching = false;
      });
      return;
    }
    setState(() => _searching = true);
    try {
      final List<SecretaryObject> results;
      if (widget.controller.mode == GraphWorkspaceMode.people) {
        final workspace = await widget.apiClient.getPeopleWorkspace(
          query: query.trim(),
        );
        results = workspace.nodes
            .where((node) => node.kind == 'person')
            .toList();
      } else {
        results = await widget.apiClient.searchObjects(
          query: query.trim(),
          kind: widget.controller.searchKindFilter,
          provider: widget.controller.searchProviderFilter,
          sort: 'relevance',
        );
      }
      setState(() {
        _searchResults = results;
        _searching = false;
      });
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } catch (_) {
      setState(() => _searching = false);
    }
  }

  void _fitView() {
    final viewportSize = _canvasViewportSize;
    if (viewportSize == null || viewportSize.isEmpty) {
      return;
    }
    final hybridBounds = _hybridGraphBounds;
    if (widget.controller.mode == GraphWorkspaceMode.tasks &&
        hybridBounds != null) {
      _transform.value = hybridFitTransform(
        graphBounds: hybridBounds,
        viewportSize: viewportSize,
      );
      return;
    }
    _transform.value = GraphLayout.fitTransform(
      positions: widget.controller.visiblePositions,
      viewportSize: viewportSize,
    );
  }

  @override
  Widget build(BuildContext context) {
    final isWide = MediaQuery.sizeOf(context).width >= 900;
    final selected = widget.controller.selectedObject;
    final showDesktopPane = isWide && selected != null;
    final canvas = KeyedSubtree(
      key: const ValueKey('graph-canvas-region'),
      child: _buildCanvas(context),
    );
    final details = selected == null
        ? null
        : _buildDetailPanel(context, compact: !isWide);

    return Column(
      children: [
        _buildToolbar(context),
        if (widget.controller.errorMessage != null &&
            widget.controller.loadState == GraphWorkspaceLoadState.ready)
          Material(
            color: Theme.of(context).colorScheme.errorContainer,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              child: Text(widget.controller.errorMessage!),
            ),
          ),
        if (widget.controller.truncated)
          Material(
            color: Theme.of(context).colorScheme.surfaceContainerHighest,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              child: Text(
                'Некоторые связанные объекты скрыты лимитом рабочей области.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
          ),
        Expanded(
          child: isWide
              ? Row(
                  children: [
                    Expanded(child: canvas),
                    if (showDesktopPane)
                      SizedBox(
                        key: const ValueKey('graph-desktop-detail-pane'),
                        width: 360,
                        child: details,
                      ),
                  ],
                )
              : Stack(
                  children: [
                    Positioned.fill(child: canvas),
                    if (selected != null)
                      Positioned(
                        left: 0,
                        right: 0,
                        bottom: 0,
                        child: Material(
                          elevation: 4,
                          child: ConstrainedBox(
                            constraints: BoxConstraints(
                              maxHeight:
                                  MediaQuery.sizeOf(context).height * 0.45,
                            ),
                            child: details,
                          ),
                        ),
                      ),
                  ],
                ),
        ),
      ],
    );
  }

  Widget _buildToolbar(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
      child: Wrap(
        spacing: 8,
        runSpacing: 8,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          SegmentedButton<GraphWorkspaceMode>(
            segments: const [
              ButtonSegment(
                value: GraphWorkspaceMode.tasks,
                label: Text('Задачи'),
              ),
              ButtonSegment(
                value: GraphWorkspaceMode.people,
                label: Text('Люди'),
              ),
            ],
            selected: {widget.controller.mode},
            onSelectionChanged: (selection) {
              widget.controller.setMode(selection.first);
              _searchController.clear();
              setState(() => _searchResults = []);
            },
          ),
          if (widget.controller.mode == GraphWorkspaceMode.tasks)
            SegmentedButton<FcoseRefinementMode>(
              segments: const [
                ButtonSegment(
                  value: FcoseRefinementMode.preserve,
                  label: Text('Preserve'),
                ),
                ButtonSegment(
                  value: FcoseRefinementMode.relax,
                  label: Text('Relax'),
                ),
              ],
              selected: {_fcoseMode},
              onSelectionChanged: (selection) {
                setState(() => _fcoseMode = selection.first);
              },
            ),
          SizedBox(
            width: widget.controller.mode == GraphWorkspaceMode.tasks
                ? 140
                : 220,
            child: TextField(
              controller: _searchController,
              decoration: InputDecoration(
                hintText: widget.controller.mode == GraphWorkspaceMode.people
                    ? 'Поиск человека'
                    : 'Поиск по графу',
                prefixIcon: const Icon(Icons.search),
                suffixIcon: _searching
                    ? const Padding(
                        padding: EdgeInsets.all(12),
                        child: SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        ),
                      )
                    : null,
                isDense: true,
              ),
              onSubmitted: (value) => _runSearch(value),
            ),
          ),
          if (widget.controller.mode == GraphWorkspaceMode.tasks)
            CompactObjectFilters(
              facets: _searchFacets,
              selectedKind: widget.controller.searchKindFilter,
              selectedProvider: widget.controller.searchProviderFilter,
              selectedSort: 'relevance',
              showSort: false,
              onKindChanged: (value) {
                widget.controller.searchKindFilter = value;
                widget.controller.applyDisplayFilters();
                _runSearch(_searchController.text);
              },
              onProviderChanged: (value) {
                widget.controller.searchProviderFilter = value;
                widget.controller.applyDisplayFilters();
                _runSearch(_searchController.text);
              },
              onSortChanged: (_) {},
            ),
          if (_searchResults.isNotEmpty)
            SizedBox(
              height: 40,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: _searchResults.length,
                separatorBuilder: (_, __) => const SizedBox(width: 8),
                itemBuilder: (context, index) {
                  final object = _searchResults[index];
                  return ActionChip(
                    label: Text(object.title, overflow: TextOverflow.ellipsis),
                    onPressed: () => widget.controller.reRoot(object.id),
                  );
                },
              ),
            ),
          Tooltip(
            message: 'К обзору',
            child: IconButton(
              onPressed: widget.controller.loadOverview,
              icon: const Icon(Icons.grid_view_outlined),
            ),
          ),
          Tooltip(
            message: 'Уместить граф',
            child: IconButton(
              onPressed: _fitView,
              icon: const Icon(Icons.fit_screen_outlined),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildCanvas(BuildContext context) {
    if (widget.controller.loadState == GraphWorkspaceLoadState.loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (widget.controller.loadState == GraphWorkspaceLoadState.error) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(widget.controller.errorMessage ?? 'Не удалось загрузить граф'),
            const SizedBox(height: 8),
            FilledButton(
              onPressed: widget.controller.loadOverview,
              child: const Text('Повторить'),
            ),
          ],
        ),
      );
    }

    final nodes = widget.controller.visibleNodes;
    final edges = widget.controller.visibleEdges;
    final positions = Map<String, Offset>.from(widget.controller.visiblePositions);
    if (widget.controller.mode == GraphWorkspaceMode.tasks) {
      positions.addAll(
        projectTaskMapHierarchy(nodes: nodes, edges: edges).positions,
      );
    }
    if (widget.controller.hasActiveDisplayFilters && nodes.isEmpty) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('Нет объектов по выбранным фильтрам'),
            const SizedBox(height: 8),
            OutlinedButton(
              onPressed: () {
                widget.controller.searchKindFilter = null;
                widget.controller.searchProviderFilter = null;
                widget.controller.applyDisplayFilters();
                _runSearch(_searchController.text);
              },
              child: const Text('Сбросить фильтры'),
            ),
          ],
        ),
      );
    }
    _hybridWarning = null;
    final hybrid = widget.controller.mode == GraphWorkspaceMode.tasks
        ? presentHybridFocus(
            nodes: nodes,
            edges: edges,
            positions: positions,
            selectedObjectId: widget.controller.selectedObjectId,
            refiner:
                widget.geometryRefiner ?? FcoseGraphRefiner(mode: _fcoseMode),
            isBookmarked: (objectId) =>
                widget.bookmarkController?.colorFor(objectId) != null,
          )
        : null;
    _hybridWarning = hybrid?.warning;
    final projection = hybrid?.lod;
    final drawnNodes = projection == null
        ? nodes
        : nodes
              .where((node) => projection.fullCardIds.contains(node.id))
              .toList();
    final byId = {for (final node in nodes) node.id: node};
    final drawnEdges = projection == null
        ? edges
        : edges
              .where(
                (edge) =>
                    focusLodEdgeIsVisible(
                      edge: edge,
                      fullCardIds: projection.fullCardIds,
                    ) &&
                    presentGraphMapEdge(
                      edge: edge,
                      sourceKind: byId[edge.sourceId]?.kind,
                      targetKind: byId[edge.targetId]?.kind,
                    ).visibleOnTasksMap,
              )
              .toList();
    final bounds = hybrid != null
        ? hybridPresentationBounds(hybrid)
        : GraphLayout.computeBounds(positions);
    _hybridGraphBounds = hybrid != null ? bounds : null;
    const canvasPad = kGraphCanvasPadding;
    final canvasWidth = bounds.width + canvasPad * 2;
    final canvasHeight = bounds.height + canvasPad * 2;
    final selectedObjectId = widget.controller.selectedObjectId;
    final focusMode = selectedObjectId != null;
    final focusNeighborIds = _focusNeighborIds(edges, selectedObjectId);

    return LayoutBuilder(
      builder: (context, constraints) {
        final viewportSize = Size(constraints.maxWidth, constraints.maxHeight);
        if (_canvasViewportSize != viewportSize) {
          _canvasViewportSize = viewportSize;
        }
        if (widget.controller.shouldFitAfterLayout) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (!mounted) {
              return;
            }
            _transform.value = hybrid != null
                ? hybridFitTransform(
                    graphBounds: bounds,
                    viewportSize: viewportSize,
                  )
                : GraphLayout.fitTransform(
                    positions: positions,
                    viewportSize: viewportSize,
                  );
            widget.controller.clearFitRequest();
          });
        }
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (_hybridWarning != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 4, 12, 4),
                child: Text(
                  _hybridWarning!,
                  key: const ValueKey('graph-hybrid-fallback'),
                ),
              ),
            Expanded(
              child: _graphViewport(
                context,
                positions,
                drawnNodes,
                drawnEdges,
                bounds,
                canvasWidth,
                canvasHeight,
                canvasPad,
                selectedObjectId,
                focusMode,
                focusNeighborIds,
                projection,
                hybrid,
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _graphViewport(
    BuildContext context,
    Map<String, Offset> positions,
    List<SecretaryObject> nodes,
    List<SecretaryEdge> edges,
    Rect bounds,
    double canvasWidth,
    double canvasHeight,
    double canvasPad,
    String? selectedObjectId,
    bool focusMode,
    Set<String> focusNeighborIds,
    FocusLodProjection? projection,
    HybridFocusPresentation? hybrid,
  ) {
    final edgePositions = Map<String, Offset>.from(positions);
    final nodeSizes = <String, Size>{};
    if (hybrid != null) {
      for (final node in hybrid.scene.nodes) {
        edgePositions[node.id] = hybrid.displayTopLeft[node.id] ?? node.topLeft;
        nodeSizes[node.id] = Size(node.width, node.height);
      }
    }
    return InteractiveViewer(
      constrained: false,
      transformationController: _transform,
      minScale: kGraphMinScale,
      maxScale: kGraphMaxScale,
      boundaryMargin: const EdgeInsets.all(200),
      child: SizedBox(
        width: canvasWidth,
        height: canvasHeight,
        child: Stack(
          clipBehavior: Clip.none,
          children: [
            CustomPaint(
              size: Size(canvasWidth, canvasHeight),
              painter: _GraphEdgePainter(
                edges: edges,
                positions: edgePositions,
                nodeSizes: nodeSizes,
                nodeKinds: {for (final node in nodes) node.id: node.kind},
                useProductRelations: hybrid != null,
                bounds: bounds,
                padding: canvasPad,
                selectedEdgeId: widget.controller.selectedEdgeId,
                selectedObjectId: selectedObjectId,
                focusMode: focusMode,
                colorScheme: Theme.of(context).colorScheme,
              ),
            ),
            if (hybrid != null)
              Positioned.fill(
                child: CustomPaint(
                  painter: HybridHairlinePainter(
                    hairlines: hybrid.hairlines,
                    bounds: bounds,
                    padding: canvasPad,
                    color: Theme.of(context).colorScheme.outline,
                    proposalColor: Theme.of(context).colorScheme.tertiary,
                    dimmed: focusMode,
                  ),
                ),
              ),
            ...nodes.map((node) {
              final focusedFlow =
                  hybrid != null &&
                  hybrid.scene.nodeById(node.id)?.width ==
                      kHybridFocusedCardWidth;
              final ongoingAnchor = hybrid != null && node.isOngoingTask;
              final position =
                  hybrid == null || (node.kind == 'task' && !ongoingAnchor)
                  ? positions[node.id] ?? const Offset(0, 0)
                  : hybrid.topLeftFor(node.id, positions);
              final selected = selectedObjectId == node.id;
              final emphasized =
                  !focusMode || selected || focusNeighborIds.contains(node.id);
              final bookmarkColor = widget.bookmarkController?.colorFor(
                node.id,
              );
              return Positioned(
                left: position.dx - bounds.left + canvasPad,
                top: position.dy - bounds.top + canvasPad,
                child: ongoingAnchor
                    ? KeyedSubtree(
                        key: Key('graph_node_${node.id}'),
                        child: HybridOngoingTaskNode(
                          object: node,
                          selected: selected,
                          focusDimmed: focusMode && !emphasized,
                          bookmarkColor: bookmarkColor,
                          onTap: () => widget.controller.selectObject(node.id),
                        ),
                      )
                    : focusedFlow
                    ? KeyedSubtree(
                        key: Key('graph_node_${node.id}'),
                        child: HybridFocusedFlowCard(
                          object: node,
                          selected: selected,
                          focusDimmed: focusMode && !emphasized,
                          bookmarkColor: bookmarkColor,
                          onTap: () => widget.controller.selectObject(node.id),
                        ),
                      )
                    : _GraphNodeCard(
                        object: node,
                        selected: selected,
                        focusDimmed: focusMode && !emphasized,
                        person: widget.controller.personFor(node.id),
                        bookmarkColor: bookmarkColor,
                        onTap: () => widget.controller.selectObject(node.id),
                      ),
              );
            }),
            if (projection != null && hybrid == null) ...[
              for (final satellite in projection.satellites)
                _focusLodMark(
                  topLeft: satellite.topLeft,
                  bounds: bounds,
                  canvasPad: canvasPad,
                  dimmed: focusMode,
                  child: FocusLodSatelliteMark(
                    key: ValueKey('focus-lod-satellite-${satellite.objectId}'),
                    objectId: satellite.objectId,
                    kind:
                        widget.controller.nodeById(satellite.objectId)?.kind ??
                        'note',
                    title:
                        widget.controller.nodeById(satellite.objectId)?.title ??
                        '',
                    provider: widget.controller
                        .nodeById(satellite.objectId)
                        ?.provider,
                    bookmarkColor: widget.bookmarkController?.colorFor(
                      satellite.objectId,
                    ),
                    onTap: () =>
                        widget.controller.selectObject(satellite.anchorTaskId),
                  ),
                ),
              for (final overflow in projection.overflows)
                _focusLodMark(
                  topLeft: overflow.topLeft,
                  bounds: bounds,
                  canvasPad: canvasPad,
                  dimmed: focusMode,
                  child: FocusLodOverflowMark(
                    key: ValueKey(
                      'focus-lod-overflow-${overflow.anchorTaskId}',
                    ),
                    remainder: overflow.remainder,
                    onTap: () =>
                        widget.controller.selectObject(overflow.anchorTaskId),
                  ),
                ),
            ],
            if (hybrid != null) ...[
              for (final satellite in hybrid.lod.satellites)
                _focusLodMark(
                  topLeft: hybrid.topLeftFor(satellite.objectId, positions),
                  bounds: bounds,
                  canvasPad: canvasPad,
                  dimmed: focusMode,
                  child: HybridFlowGlyph(
                    key: ValueKey('hybrid-glyph-${satellite.objectId}'),
                    objectId: satellite.objectId,
                    kind:
                        widget.controller.nodeById(satellite.objectId)?.kind ??
                        'note',
                    title:
                        widget.controller.nodeById(satellite.objectId)?.title ??
                        '',
                    provider: widget.controller
                        .nodeById(satellite.objectId)
                        ?.provider,
                    bookmarkColor: widget.bookmarkController?.colorFor(
                      satellite.objectId,
                    ),
                    onTap: () =>
                        widget.controller.selectObject(satellite.anchorTaskId),
                  ),
                ),
              for (final overflow in hybrid.lod.overflows)
                _focusLodMark(
                  topLeft: hybrid.topLeftFor(
                    hybridOverflowId(overflow.anchorTaskId),
                    positions,
                  ),
                  bounds: bounds,
                  canvasPad: canvasPad,
                  dimmed: focusMode,
                  child: HybridOverflowGlyph(
                    key: ValueKey('hybrid-overflow-${overflow.anchorTaskId}'),
                    remainder: overflow.remainder,
                    onTap: () =>
                        widget.controller.selectObject(overflow.anchorTaskId),
                  ),
                ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _focusLodMark({
    required Offset topLeft,
    required Rect bounds,
    required double canvasPad,
    required bool dimmed,
    required Widget child,
  }) {
    return Positioned(
      left: topLeft.dx - bounds.left + canvasPad,
      top: topLeft.dy - bounds.top + canvasPad,
      child: Opacity(opacity: dimmed ? 0.35 : 1, child: child),
    );
  }

  Widget _buildDetailPanel(BuildContext context, {required bool compact}) {
    final object = widget.controller.selectedObject;
    if (object == null) {
      return Padding(
        padding: const EdgeInsets.all(16),
        child: Text(
          'Выберите объект для просмотра.',
          style: Theme.of(context).textTheme.bodyMedium,
        ),
      );
    }

    final relatedEdges = widget.controller.edges.where(
      (edge) => edge.sourceId == object.id || edge.targetId == object.id,
    );

    final primaryDateValue = objectPrimaryDateDisplayValue(object);

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Row(
          children: [
            Icon(iconForKind(object.kind)),
            const SizedBox(width: 8),
            if (object.provider != null) ...[
              providerBadge(context, object.provider!),
              const SizedBox(width: 8),
            ],
            Expanded(
              child: Text(
                object.title,
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
            if (widget.bookmarkController != null)
              ObjectBookmarkEditor(
                color: widget.bookmarkController!.colorFor(object.id),
                onSelect: (color) =>
                    widget.bookmarkController!.setColor(object.id, color),
                onClear: () => widget.bookmarkController!.clear(object.id),
              ),
            if (object.kind == 'task' && !object.isDeletedTask)
              IconButton(
                tooltip: 'Удалить задачу',
                onPressed: () => _deleteTask(context, object),
                icon: Icon(
                  Icons.delete_outline,
                  color: Theme.of(context).colorScheme.error,
                ),
              ),
            IconButton(
              tooltip: 'Закрыть',
              onPressed: () => widget.controller.selectObject(null),
              icon: const Icon(Icons.close),
            ),
          ],
        ),
        SelectionArea(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(objectSummaryLabel(object)),
              if (object.body != null) ...[
                const SizedBox(height: 8),
                SelectableText(object.body!),
              ],
              if (primaryDateValue.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(
                    '${objectPrimaryDateFieldLabel(object)}: $primaryDateValue',
                  ),
                ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            Tooltip(
              message: 'Спросить секретаря',
              child: OutlinedButton.icon(
                onPressed: () {
                  widget.assistantController.setObjectContext(object);
                  widget.onAskSecretary(object);
                },
                icon: const Icon(Icons.support_agent_outlined, size: 18),
                label: const Text('Спросить секретаря'),
              ),
            ),
            Tooltip(
              message: 'Использовать как контекст',
              child: OutlinedButton.icon(
                onPressed: () {
                  widget.captureController.attachObjectContext(object);
                  openCapture(
                    context,
                    captureController: widget.captureController,
                    authController: widget.authController,
                  );
                },
                icon: const Icon(Icons.add_task_outlined, size: 18),
                label: Text(compact ? 'Контекст' : 'Использовать как контекст'),
              ),
            ),
            _GraphOpenSourceAction(
              key: ValueKey(object.id),
              objectId: object.id,
              apiClient: widget.apiClient,
              onOpen: () => _openSource(context, object.id),
            ),
            Tooltip(
              message: 'Открыть подробности',
              child: OutlinedButton.icon(
                onPressed: () async {
                  final controller = widget.controller;
                  final result = await openObjectDetail(
                    context,
                    objectId: object.id,
                    apiClient: widget.apiClient,
                    authController: widget.authController,
                    captureController: widget.captureController,
                    assistantController: widget.assistantController,
                    onAskSecretary: widget.onAskSecretary,
                    onShowInGraph: (id) => controller.reRoot(id),
                    onTaskUpdated: controller.applyTaskMutation,
                    bookmarkController: widget.bookmarkController,
                  );
                  if (!mounted) {
                    return;
                  }
                  if (result != null) {
                    controller.removeObjectImmediately(result.deletedObjectId);
                  }
                  WidgetsBinding.instance.addPostFrameCallback((_) {
                    if (!mounted) {
                      return;
                    }
                    controller.refreshCurrentWorkspace();
                  });
                },
                icon: const Icon(Icons.open_in_new, size: 18),
                label: const Text('Подробнее'),
              ),
            ),
            Tooltip(
              message: 'Показать связи',
              child: OutlinedButton.icon(
                onPressed: widget.controller.expandSelected,
                icon: const Icon(Icons.hub_outlined, size: 18),
                label: const Text('Показать связи'),
              ),
            ),
            Tooltip(
              message: 'В центр',
              child: OutlinedButton.icon(
                onPressed: () => widget.controller.reRoot(object.id),
                icon: const Icon(Icons.center_focus_strong_outlined, size: 18),
                label: const Text('В центр'),
              ),
            ),
            Tooltip(
              message: 'Добавить связь',
              child: OutlinedButton.icon(
                onPressed: () => _addRelation(context, object),
                icon: const Icon(Icons.link, size: 18),
                label: const Text('Добавить связь'),
              ),
            ),
          ],
        ),
        TaskManagementActions(
          task: object,
          apiClient: widget.apiClient,
          authController: widget.authController,
          compact: compact,
          onTaskUpdated: widget.controller.applyTaskMutation,
        ),
        if (widget.controller.personFor(object.id) != null) ...[
          const SizedBox(height: 12),
          _PersonDetailSection(
            person: widget.controller.personFor(object.id)!,
            apiClient: widget.apiClient,
            onChanged: widget.controller.refreshCurrentWorkspace,
          ),
        ],
        const SizedBox(height: 12),
        _DetailSectionHeader(title: 'Связи'),
        ...relatedEdges.map((edge) {
          final source = widget.controller.nodeById(edge.sourceId);
          final target = widget.controller.nodeById(edge.targetId);
          final otherId = edge.sourceId == object.id
              ? edge.targetId
              : edge.sourceId;
          final other = widget.controller.nodeById(otherId);
          return ListTile(
            key: ValueKey('graph-relation-${edge.id}'),
            dense: true,
            selected: widget.controller.selectedEdgeId == edge.id,
            onTap: () {
              widget.controller.selectEdge(edge.id);
              if (other != null) {
                widget.controller.selectObject(other.id);
              }
            },
            leading: edge.state == 'proposed'
                ? Icon(
                    Icons.diamond_outlined,
                    size: 16,
                    color: Theme.of(context).colorScheme.tertiary,
                    key: ValueKey('graph-relation-proposed-${edge.id}'),
                  )
                : null,
            title: Text(
              graphRelationAuditText(
                edge: edge,
                sourceTitle: source?.title ?? edge.sourceId,
                targetTitle: target?.title ?? edge.targetId,
                selectedObjectId: object.id,
              ),
              key: ValueKey('graph-relation-audit-${edge.id}'),
            ),
            subtitle: Text(
              '${originLabel(edge.origin)} · ${provenanceStateLabel(edge.state)}',
            ),
            trailing: _relationTrailing(context, edge),
          );
        }),
        if (widget.controller.mode == GraphWorkspaceMode.tasks &&
            object.kind == 'task' &&
            !object.isDeletedTask) ...[
          const SizedBox(height: 12),
          TaskProfileSection(
            key: ValueKey('task-profile-${object.id}'),
            taskId: object.id,
            apiClient: widget.apiClient,
            authController: widget.authController,
            onOpenPerson: (personId) async {
              await widget.controller.setMode(GraphWorkspaceMode.people);
              if (!mounted) {
                return;
              }
              await widget.controller.reRoot(personId);
            },
            onOpenTask: widget.controller.reRoot,
            onOpenEvidence: (objectId) {
              return openObjectDetail(
                context,
                objectId: objectId,
                apiClient: widget.apiClient,
                authController: widget.authController,
                captureController: widget.captureController,
                assistantController: widget.assistantController,
                onAskSecretary: widget.onAskSecretary,
                onShowInGraph: widget.controller.reRoot,
                onTaskUpdated: widget.controller.applyTaskMutation,
                bookmarkController: widget.bookmarkController,
              );
            },
          ),
        ],
      ],
    );
  }

  Future<void> _addRelation(
    BuildContext context,
    SecretaryObject source,
  ) async {
    String relationType = 'related_to';
    SecretaryObject? target;
    final queryController = TextEditingController();
    List<SecretaryObject> options = [];

    await showDialog<void>(
      context: context,
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setState) {
            return AlertDialog(
              title: const Text('Добавить связь'),
              content: SizedBox(
                width: 360,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    DropdownButtonFormField<String>(
                      value: relationType,
                      items: [
                        const DropdownMenuItem(
                          value: 'related_to',
                          child: Text('Связано с'),
                        ),
                        const DropdownMenuItem(
                          value: 'references',
                          child: Text('Ссылается на'),
                        ),
                        const DropdownMenuItem(
                          value: 'depends_on',
                          child: Text('Зависит от'),
                        ),
                        if (source.kind == 'task')
                          const DropdownMenuItem(
                            value: 'part_of',
                            child: Text('Входит в'),
                          ),
                      ],
                      onChanged: (value) {
                        if (value == null || value == relationType) {
                          return;
                        }
                        setState(() {
                          final crossesPartOf =
                              value == 'part_of' || relationType == 'part_of';
                          relationType = value;
                          if (crossesPartOf) {
                            target = null;
                            options = [];
                          }
                        });
                      },
                    ),
                    if (relationType == 'part_of')
                      const Padding(
                        padding: EdgeInsets.only(top: 8),
                        child: Text(
                          'Выбранная задача входит в выбранную родительскую задачу.',
                        ),
                      ),
                    TextField(
                      controller: queryController,
                      decoration: const InputDecoration(
                        labelText: 'Поиск объекта',
                      ),
                      onSubmitted: (value) async {
                        final partOf = relationType == 'part_of';
                        final results = await widget.apiClient.searchObjects(
                          query: value,
                          kind: partOf ? 'task' : null,
                        );
                        setState(() {
                          options = partOf
                              ? results
                                    .where(
                                      (item) =>
                                          item.kind == 'task' &&
                                          item.id != source.id,
                                    )
                                    .toList()
                              : results;
                        });
                      },
                    ),
                    ...options.map(
                      (item) => ListTile(
                        title: Text(item.title),
                        subtitle: Text(objectKindLabel(item.kind)),
                        selected: target?.id == item.id,
                        onTap: () => setState(() => target = item),
                      ),
                    ),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text('Отмена'),
                ),
                FilledButton(
                  onPressed: target == null
                      ? null
                      : () => Navigator.pop(context),
                  child: const Text('Создать'),
                ),
              ],
            );
          },
        );
      },
    );

    if (target == null || target!.id == source.id) {
      return;
    }
    if (relationType == 'part_of' &&
        (source.kind != 'task' || target!.kind != 'task')) {
      return;
    }
    try {
      final response = await widget.apiClient.createRelation(
        sourceId: source.id,
        targetId: target!.id,
        type: relationType,
      );
      await widget.controller.mergeRelationContext(
        source.id,
        target: target,
        edge: response.edge,
      );
    } on ApiException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(error.message)));
      }
    }
  }

  Set<String> _focusNeighborIds(List<SecretaryEdge> edges, String? selectedId) {
    if (selectedId == null) {
      return {};
    }
    final neighbors = <String>{};
    for (final edge in edges) {
      if (edge.sourceId == selectedId) {
        neighbors.add(edge.targetId);
      }
      if (edge.targetId == selectedId) {
        neighbors.add(edge.sourceId);
      }
    }
    return neighbors;
  }

  Future<void> _openSource(BuildContext context, String objectId) async {
    final navigation = SourceNavigationService(apiClient: widget.apiClient);
    try {
      await navigation.launchForObject(objectId);
    } on SourceLaunchException catch (e) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  Future<void> _deleteTask(BuildContext context, SecretaryObject task) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Удалить задачу?'),
        content: Text(
          '${task.title}\n\nЗадача будет скрыта из обычного поиска и активных представлений. '
          'История в графе и связи сохранятся.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Удалить'),
          ),
        ],
      ),
    );
    if (confirmed != true) {
      return;
    }
    try {
      final response = await widget.apiClient.softDeleteTask(task.id);
      await widget.controller.applyTaskMutation(response.object);
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(error.message)));
      }
    }
  }

  Future<void> _removeRelation(BuildContext context, SecretaryEdge edge) async {
    final source = widget.controller.nodeById(edge.sourceId);
    final target = widget.controller.nodeById(edge.targetId);
    final sourceTitle = source?.title ?? edge.sourceId;
    final targetTitle = target?.title ?? edge.targetId;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Удалить связь?'),
        content: Text(
          '$sourceTitle —${relationTypeLabel(edge.type)}→ $targetTitle',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Удалить'),
          ),
        ],
      ),
    );
    if (confirmed != true) {
      return;
    }
    try {
      await widget.apiClient.deleteRelation(edge.id);
      widget.controller.removeEdge(edge.id);
    } on ApiException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(error.message)));
      }
    }
  }

  Widget? _relationTrailing(BuildContext context, SecretaryEdge edge) {
    if (edge.origin == 'agent' && edge.state == 'proposed') {
      return Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          IconButton(
            tooltip: 'Подтвердить',
            icon: const Icon(Icons.check_circle_outline),
            onPressed: () => _decideRelation(context, edge, 'confirm'),
          ),
          IconButton(
            tooltip: 'Отклонить',
            icon: const Icon(Icons.cancel_outlined),
            onPressed: () => _decideRelation(context, edge, 'reject'),
          ),
        ],
      );
    }
    if (edge.origin == 'user') {
      return IconButton(
        tooltip: 'Удалить связь',
        icon: const Icon(Icons.link_off_outlined),
        onPressed: () => _removeRelation(context, edge),
      );
    }
    return null;
  }

  Future<void> _decideRelation(
    BuildContext context,
    SecretaryEdge edge,
    String decision,
  ) async {
    try {
      final response = await widget.apiClient.decideRelation(
        edgeId: edge.id,
        decision: decision,
      );
      if (response.edge.state == 'rejected') {
        widget.controller.removeEdge(edge.id);
      } else {
        widget.controller.upsertEdge(response.edge);
      }
    } on ApiException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(error.message)));
      }
    }
  }
}

String _graphNodeFooterLabel(SecretaryObject object) {
  if (object.kind == 'task') {
    final lifecycle = objectLifecycleDisplayLabel(object);
    final due = objectPrimaryDateLabel(object);
    if (due.isNotEmpty) {
      return '$lifecycle • $due';
    }
    return lifecycle;
  }
  final primaryDate = objectPrimaryDateLabel(object);
  if (primaryDate.isNotEmpty) {
    return primaryDate;
  }
  return objectLifecycleDisplayLabel(object);
}

class _DetailSectionHeader extends StatelessWidget {
  const _DetailSectionHeader({required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: theme.textTheme.labelLarge?.copyWith(
              color: theme.colorScheme.primary,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 4),
          Divider(height: 1, color: theme.colorScheme.outlineVariant),
        ],
      ),
    );
  }
}

class _PersonDetailSection extends StatelessWidget {
  const _PersonDetailSection({
    required this.person,
    required this.apiClient,
    required this.onChanged,
  });

  final PersonPresentation person;
  final SecretaryApiClient apiClient;
  final Future<void> Function() onChanged;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _DetailSectionHeader(title: 'Известные контакты'),
        if (person.identityConflict)
          Text(
            'Есть конфликт идентичности',
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
        ...person.identities.map((identity) {
          return ListTile(
            dense: true,
            title: Text(identity.displayValue),
            subtitle: Text(
              '${providerLabel(identity.provider)} · ${_identityStateLabel(identity.state)}',
            ),
            trailing: Wrap(
              spacing: 4,
              children: [
                if (identity.confirmable)
                  TextButton(
                    onPressed: () => _correct(identity, 'confirm'),
                    child: const Text('Подтвердить'),
                  ),
                if (identity.state == 'effective' ||
                    identity.state == 'conflicted')
                  TextButton(
                    onPressed: () => _correct(identity, 'reject'),
                    child: const Text('Отклонить'),
                  ),
                if (identity.state == 'rejected')
                  TextButton(
                    onPressed: () => _correct(identity, 'retract'),
                    child: const Text('Вернуть'),
                  ),
              ],
            ),
          );
        }),
        if (person.routes.isNotEmpty) ...[
          const _DetailSectionHeader(title: 'Маршруты'),
          ...person.routes.map(
            (route) => ListTile(
              dense: true,
              title: Text(route.label),
              subtitle: Text(providerLabel(route.provider)),
            ),
          ),
        ],
        Text('Открытые задачи: ${person.openTaskCount}'),
      ],
    );
  }

  Future<void> _correct(
    PersonIdentityPresentation identity,
    String action,
  ) async {
    await apiClient.correctPersonIdentity(
      personId: person.personId,
      action: action,
      identityType: identity.identityType,
      provider: identity.provider,
      realm: identity.realm,
      canonicalValue: identity.canonicalValue,
    );
    await onChanged();
  }
}

String _identityStateLabel(String state) {
  switch (state) {
    case 'effective':
      return 'подтверждено';
    case 'conflicted':
      return 'конфликт';
    case 'rejected':
      return 'отклонено';
    case 'candidate':
      return 'кандидат';
    default:
      return state;
  }
}

class _GraphNodeCard extends StatelessWidget {
  const _GraphNodeCard({
    required this.object,
    required this.selected,
    required this.focusDimmed,
    required this.onTap,
    this.person,
    this.bookmarkColor,
  });

  final SecretaryObject object;
  final bool selected;
  final bool focusDimmed;
  final VoidCallback onTap;
  final PersonPresentation? person;
  final String? bookmarkColor;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final baseColor = selected
        ? scheme.primaryContainer
        : object.kind == 'task'
        ? scheme.surfaceContainerHigh
        : scheme.surface;

    final card = Material(
      elevation: selected ? 4 : 1,
      color: baseColor,
      borderRadius: BorderRadius.circular(10),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(10),
        child: Container(
          width: kGraphNodeWidth,
          height: kGraphNodeHeight,
          padding: const EdgeInsets.all(8),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(10),
            border: Border.all(
              color: selected ? scheme.primary : scheme.outlineVariant,
              width: selected ? 2 : 1,
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(iconForKind(object.kind), size: 16),
                  const SizedBox(width: 4),
                  Expanded(
                    child: Text(
                      objectKindLabel(object.kind),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.labelSmall,
                    ),
                  ),
                  if (person?.identityConflict == true)
                    Icon(Icons.report_outlined, size: 16, color: scheme.error),
                  if (person != null && person!.identities.isNotEmpty)
                    Flexible(
                      child: Text(
                        person!.identities
                            .where((item) => item.state == 'effective')
                            .map((item) => providerLabel(item.provider))
                            .take(2)
                            .join(' · '),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context).textTheme.labelSmall,
                      ),
                    )
                  else if (object.provider != null)
                    SizedBox(
                      width: 18,
                      height: 18,
                      child: FittedBox(
                        child: providerBadge(context, object.provider!),
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 4),
              Expanded(
                child: Text(
                  object.title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodySmall
                      ?.copyWith(fontWeight: FontWeight.w600),
                ),
              ),
              Text(
                _graphNodeFooterLabel(object),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.labelSmall
                    ?.copyWith(color: scheme.onSurfaceVariant),
              ),
            ],
          ),
        ),
      ),
    );

    return Opacity(
      opacity: focusDimmed ? 0.35 : 1,
      child: MouseRegion(
        cursor: SystemMouseCursors.click,
        child: KeyedSubtree(
          key: Key('graph_node_${object.id}'),
          child: ObjectBookmarkRibbon(
            color: bookmarkColor,
            reserveTrailingSpace: false,
            child: card,
          ),
        ),
      ),
    );
  }
}

class _GraphEdgePainter extends CustomPainter {
  _GraphEdgePainter({
    required this.edges,
    required this.positions,
    required this.bounds,
    required this.padding,
    required this.selectedEdgeId,
    required this.selectedObjectId,
    required this.focusMode,
    required this.colorScheme,
    this.nodeSizes = const {},
    this.nodeKinds = const {},
    this.useProductRelations = false,
  });

  final List<SecretaryEdge> edges;
  final Map<String, Offset> positions;
  final Map<String, Size> nodeSizes;
  final Map<String, String> nodeKinds;
  final bool useProductRelations;
  final Rect bounds;
  final double padding;
  final String? selectedEdgeId;
  final String? selectedObjectId;
  final bool focusMode;
  final ColorScheme colorScheme;

  Size _nodeSize(String objectId) {
    return nodeSizes[objectId] ?? const Size(kGraphNodeWidth, kGraphNodeHeight);
  }

  Offset _borderPoint(Offset center, Offset toward, Size size) {
    final dx = toward.dx - center.dx;
    final dy = toward.dy - center.dy;
    if (dx == 0 && dy == 0) {
      return center;
    }
    if (size.width == kHybridOngoingSize && size.height == kHybridOngoingSize) {
      final length = math.sqrt(dx * dx + dy * dy);
      final radius = kHybridOngoingSize / 2;
      return Offset(
        center.dx + dx / length * radius,
        center.dy + dy / length * radius,
      );
    }
    return GraphLayout.computeEdgeEndpoints(
      sourceCenter: center,
      targetCenter: toward,
      nodeWidth: size.width,
      nodeHeight: size.height,
    ).start;
  }

  Offset _nodeCenter(String objectId) {
    final position = positions[objectId] ?? const Offset(0, 0);
    final size = _nodeSize(objectId);
    return Offset(
      position.dx - bounds.left + padding + size.width / 2,
      position.dy - bounds.top + padding + size.height / 2,
    );
  }

  bool _isFocusEdge(SecretaryEdge edge) {
    if (selectedObjectId == null) {
      return false;
    }
    return edge.sourceId == selectedObjectId ||
        edge.targetId == selectedObjectId;
  }

  @override
  void paint(Canvas canvas, Size size) {
    for (final edge in edges) {
      if (!positions.containsKey(edge.sourceId) ||
          !positions.containsKey(edge.targetId)) {
        continue;
      }

      final presentation = useProductRelations
          ? presentGraphMapEdge(
              edge: edge,
              sourceKind: nodeKinds[edge.sourceId],
              targetKind: nodeKinds[edge.targetId],
            )
          : null;
      if (presentation != null && !presentation.visibleOnTasksMap) {
        continue;
      }
      final focusEdge = focusMode && _isFocusEdge(edge);
      final dimmed = focusMode && !focusEdge;
      final emphasized = edge.id == selectedEdgeId || focusEdge;
      final productProposed = presentation?.proposed ?? false;
      final proposed = productProposed || edge.state == 'proposed';
      final secondary = presentation?.secondary ?? false;
      final light = presentation?.light ?? false;
      final structural = presentation?.structural ?? false;

      var paint = Paint()
        ..strokeWidth = productProposed
            ? kProposedFullStroke
            : emphasized
            ? 2.5
            : (structural ? 2.0 : (secondary || light ? 1.2 : 1.5))
        ..color = proposed
            ? colorScheme.tertiary
            : emphasized
            ? colorScheme.primary
            : colorScheme.outline
        ..style = PaintingStyle.stroke;

      if (!productProposed && secondary && !emphasized) {
        paint = paint..color = paint.color.withValues(alpha: 0.55);
      } else if (!productProposed && light && !emphasized) {
        paint = paint..color = paint.color.withValues(alpha: 0.7);
      }
      if (productProposed) {
        paint = paint
          ..color = colorScheme.tertiary.withValues(
            alpha: proposedRelationOpacity(dimmed: dimmed),
          );
      } else if (dimmed) {
        paint = paint..color = paint.color.withValues(alpha: 0.35);
      }

      final sourceCenter = _nodeCenter(edge.sourceId);
      final targetCenter = _nodeCenter(edge.targetId);
      final sourceSize = _nodeSize(edge.sourceId);
      final targetSize = _nodeSize(edge.targetId);
      final start = _borderPoint(sourceCenter, targetCenter, sourceSize);
      final end = _borderPoint(targetCenter, sourceCenter, targetSize);
      if (productProposed && presentation?.dashed != true) {
        canvas.drawLine(
          start,
          end,
          Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = kProposedFullStroke + kProposedUnderExtra
            ..color = colorScheme.tertiary.withValues(alpha: dimmed ? 0.28 : 0.34),
        );
      }
      if (presentation?.dashed ?? false) {
        _drawDashed(canvas, start, end, paint);
      } else {
        canvas.drawLine(start, end, paint);
      }
      if (productProposed) {
        paintRelationDiamond(
          canvas,
          relationSegmentMidpoint(start, end),
          kProposedFullDiamond,
          paint,
        );
      }
      if (presentation != null && !presentation.directed) {
        continue;
      }

      final angle = math.atan2(end.dy - start.dy, end.dx - start.dx);
      const arrow = 10.0;
      final tip = end;
      final left = Offset(
        tip.dx - arrow * math.cos(angle - 0.4),
        tip.dy - arrow * math.sin(angle - 0.4),
      );
      final right = Offset(
        tip.dx - arrow * math.cos(angle + 0.4),
        tip.dy - arrow * math.sin(angle + 0.4),
      );
      final path = Path()
        ..moveTo(tip.dx, tip.dy)
        ..lineTo(left.dx, left.dy)
        ..lineTo(right.dx, right.dy)
        ..close();
      canvas.drawPath(path, paint);
    }
  }

  void _drawDashed(Canvas canvas, Offset start, Offset end, Paint paint) {
    const dash = 6.0;
    const gap = 4.0;
    final delta = end - start;
    final length = delta.distance;
    if (length == 0) {
      return;
    }
    final direction = delta / length;
    var drawn = 0.0;
    while (drawn < length) {
      final next = math.min(drawn + dash, length);
      canvas.drawLine(
        start + direction * drawn,
        start + direction * next,
        paint,
      );
      drawn = next + gap;
    }
  }

  @override
  bool shouldRepaint(covariant _GraphEdgePainter oldDelegate) => true;
}

class _GraphOpenSourceAction extends StatefulWidget {
  const _GraphOpenSourceAction({
    super.key,
    required this.objectId,
    required this.apiClient,
    required this.onOpen,
  });

  final String objectId;
  final SecretaryApiClient apiClient;
  final VoidCallback onOpen;

  @override
  State<_GraphOpenSourceAction> createState() => _GraphOpenSourceActionState();
}

class _GraphOpenSourceActionState extends State<_GraphOpenSourceAction> {
  SourceActionPresentation? _presentation;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant _GraphOpenSourceAction oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.objectId != widget.objectId) {
      setState(() => _presentation = null);
      _load();
    }
  }

  Future<void> _load() async {
    try {
      final target = await widget.apiClient.getOpenTarget(widget.objectId);
      final presentation = await SourceNavigationPresenter().present(target);
      if (mounted) {
        setState(() => _presentation = presentation);
      }
    } catch (_) {
      // Source action unavailable for this object.
    }
  }

  @override
  Widget build(BuildContext context) {
    final presentation = _presentation;
    if (presentation == null) {
      return const SizedBox.shrink();
    }
    if (presentation.canOpen) {
      final label = presentation.openLabel ?? 'Открыть в источнике';
      return Tooltip(
        message: label,
        child: OutlinedButton.icon(
          key: const Key('graph_open_source_button'),
          onPressed: widget.onOpen,
          icon: const Icon(Icons.open_in_new, size: 18),
          label: Text(label),
        ),
      );
    }
    if (presentation.isDisabled) {
      return Tooltip(
        message: presentation.disabledReason!,
        child: OutlinedButton.icon(
          onPressed: null,
          icon: const Icon(Icons.open_in_new, size: 18),
          label: Text(presentation.disabledReason!),
        ),
      );
    }
    return const SizedBox.shrink();
  }
}
