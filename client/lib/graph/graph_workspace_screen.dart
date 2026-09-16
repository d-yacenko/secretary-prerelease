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
import 'graph_layout.dart';
import 'graph_workspace_controller.dart';

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
  });

  final GraphWorkspaceController controller;
  final SecretaryApiClient apiClient;
  final AuthController authController;
  final CaptureController captureController;
  final AssistantController assistantController;
  final void Function(SecretaryObject object) onAskSecretary;
  final ObjectBookmarkController? bookmarkController;

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
      final current =
          widget.controller.visibleNodes.map((node) => node.id).toSet();
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
      final results = await widget.apiClient.searchObjects(
        query: query.trim(),
        kind: widget.controller.searchKindFilter,
        provider: widget.controller.searchProviderFilter,
        sort: 'relevance',
      );
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
    _transform.value = GraphLayout.fitTransform(
      positions: widget.controller.visiblePositions,
      viewportSize: viewportSize,
    );
  }

  @override
  Widget build(BuildContext context) {
    final isWide = MediaQuery.sizeOf(context).width >= 900;
    final canvas = _buildCanvas(context);
    final details = _buildDetailPanel(context, compact: !isWide);

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
                    SizedBox(width: 360, child: details),
                  ],
                )
              : Stack(
                  children: [
                    Positioned.fill(child: canvas),
                    if (widget.controller.selectedObject != null)
                      Positioned(
                        left: 0,
                        right: 0,
                        bottom: 0,
                        child: Material(
                          elevation: 4,
                          child: ConstrainedBox(
                            constraints: BoxConstraints(
                              maxHeight: MediaQuery.sizeOf(context).height * 0.45,
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
          SizedBox(
            width: 220,
            child: TextField(
              controller: _searchController,
              decoration: InputDecoration(
                hintText: 'Поиск по графу',
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
    final positions = widget.controller.visiblePositions;
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
    final bounds = GraphLayout.computeBounds(positions);
    final canvasWidth = bounds.width + kGraphCanvasPadding * 2;
    final canvasHeight = bounds.height + kGraphCanvasPadding * 2;
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
            _transform.value = GraphLayout.fitTransform(
              positions: positions,
              viewportSize: viewportSize,
            );
            widget.controller.clearFitRequest();
          });
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
                    positions: positions,
                    bounds: bounds,
                    padding: kGraphCanvasPadding,
                    selectedEdgeId: widget.controller.selectedEdgeId,
                    selectedObjectId: selectedObjectId,
                    focusMode: focusMode,
                    colorScheme: Theme.of(context).colorScheme,
                  ),
                ),
                ...nodes.map((node) {
                  final position = positions[node.id] ?? const Offset(0, 0);
                  final selected = selectedObjectId == node.id;
                  final emphasized = !focusMode ||
                      selected ||
                      focusNeighborIds.contains(node.id);
                  return Positioned(
                    left: position.dx - bounds.left + kGraphCanvasPadding,
                    top: position.dy - bounds.top + kGraphCanvasPadding,
                    child: _GraphNodeCard(
                      object: node,
                      selected: selected,
                      focusDimmed: focusMode && !emphasized,
                      bookmarkColor:
                          widget.bookmarkController?.colorFor(node.id),
                      onTap: () => widget.controller.selectObject(node.id),
                    ),
                  );
                }),
              ],
            ),
          ),
        );
      },
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
              child: Text(object.title, style: Theme.of(context).textTheme.titleMedium),
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
        const SizedBox(height: 12),
        _DetailSectionHeader(title: 'Связи'),
        ...relatedEdges.map((edge) {
          final otherId = edge.sourceId == object.id ? edge.targetId : edge.sourceId;
          final other = widget.controller.nodeById(otherId);
          return ListTile(
            dense: true,
            selected: widget.controller.selectedEdgeId == edge.id,
            onTap: () {
              widget.controller.selectEdge(edge.id);
              if (other != null) {
                widget.controller.selectObject(other.id);
              }
            },
            title: Text(relationTypeLabel(edge.type)),
            subtitle: Text(
              edge.origin == 'agent' && edge.state == 'proposed'
                  ? '${provenanceStateLabel(edge.state)} • ${other?.title ?? otherId}'
                  : other?.title ?? otherId,
            ),
            trailing: _relationTrailing(context, edge),
          );
        }),
      ],
    );
  }

  Future<void> _addRelation(BuildContext context, SecretaryObject source) async {
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
                      items: const [
                        DropdownMenuItem(value: 'related_to', child: Text('Связано с')),
                        DropdownMenuItem(value: 'references', child: Text('Ссылается на')),
                        DropdownMenuItem(value: 'depends_on', child: Text('Зависит от')),
                      ],
                      onChanged: (value) {
                        if (value != null) {
                          setState(() => relationType = value);
                        }
                      },
                    ),
                    TextField(
                      controller: queryController,
                      decoration: const InputDecoration(labelText: 'Поиск объекта'),
                      onSubmitted: (value) async {
                        final results = await widget.apiClient.searchObjects(query: value);
                        setState(() => options = results);
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
                  onPressed: target == null ? null : () => Navigator.pop(context),
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
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(error.message)),
        );
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
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
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
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(error.message)),
        );
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
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(error.message)),
        );
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
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(error.message)),
        );
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

class _GraphNodeCard extends StatelessWidget {
  const _GraphNodeCard({
    required this.object,
    required this.selected,
    required this.focusDimmed,
    required this.onTap,
    this.bookmarkColor,
  });

  final SecretaryObject object;
  final bool selected;
  final bool focusDimmed;
  final VoidCallback onTap;
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
                  if (object.provider != null)
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
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                ),
              ),
              Text(
                _graphNodeFooterLabel(object),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      color: scheme.onSurfaceVariant,
                    ),
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
  });

  final List<SecretaryEdge> edges;
  final Map<String, Offset> positions;
  final Rect bounds;
  final double padding;
  final String? selectedEdgeId;
  final String? selectedObjectId;
  final bool focusMode;
  final ColorScheme colorScheme;

  Offset _nodeCenter(String objectId) {
    final position = positions[objectId] ?? const Offset(0, 0);
    return Offset(
      position.dx - bounds.left + padding + kGraphNodeWidth / 2,
      position.dy - bounds.top + padding + kGraphNodeHeight / 2,
    );
  }

  bool _isFocusEdge(SecretaryEdge edge) {
    if (selectedObjectId == null) {
      return false;
    }
    return edge.sourceId == selectedObjectId || edge.targetId == selectedObjectId;
  }

  @override
  void paint(Canvas canvas, Size size) {
    for (final edge in edges) {
      if (!positions.containsKey(edge.sourceId) ||
          !positions.containsKey(edge.targetId)) {
        continue;
      }

      final focusEdge = focusMode && _isFocusEdge(edge);
      final dimmed = focusMode && !focusEdge;
      final emphasized = edge.id == selectedEdgeId || focusEdge;

      var paint = Paint()
        ..strokeWidth = emphasized ? 2.5 : 1.5
        ..color = edge.state == 'proposed'
            ? colorScheme.tertiary
            : emphasized
                ? colorScheme.primary
                : colorScheme.outline
        ..style = PaintingStyle.stroke;

      if (dimmed) {
        paint = paint..color = paint.color.withValues(alpha: 0.35);
      }

      final sourceCenter = _nodeCenter(edge.sourceId);
      final targetCenter = _nodeCenter(edge.targetId);
      final endpoints = GraphLayout.computeEdgeEndpoints(
        sourceCenter: sourceCenter,
        targetCenter: targetCenter,
      );
      final start = endpoints.start;
      final end = endpoints.end;
      canvas.drawLine(start, end, paint);

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
