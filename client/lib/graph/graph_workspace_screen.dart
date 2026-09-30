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
import 'people_landscape.dart';
import 'people_overview.dart';
import 'graph_workspace_controller.dart';
import 'task_layout_world.dart';
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
  bool _peopleInspectorOpen = false;
  bool _peopleInspectorCandidates = true;
  PersonPresentation? _rootedPerson;
  String? _rootedPersonId;
  bool _rootedLoading = false;
  String? _rootedError;
  int _rootedToken = 0;
  String? _trackedPersonId;
  final ScrollController _promotionScroll = ScrollController();

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
    _promotionScroll.dispose();
    _transform.dispose();
    super.dispose();
  }

  void _onBookmarksChanged() {
    if (mounted) {
      setState(() {});
    }
  }

  void _onControllerChanged() {
    _trackPersonSelection();
    _adoptCenteredPerson();
    if (mounted) {
      setState(() {});
    }
    _scheduleVisibleBookmarkReconcile();
  }

  void _trackPersonSelection() {
    if (widget.controller.mode != GraphWorkspaceMode.people) {
      return;
    }
    final selected = widget.controller.selectedObject;
    final id = selected != null && selected.kind == 'person' ? selected.id : null;
    if (id == _trackedPersonId) {
      return;
    }
    _trackedPersonId = id;
    if (id == null) {
      _rootedPerson = null;
      _rootedPersonId = null;
      _rootedLoading = false;
      _rootedError = null;
      return;
    }
    _peopleInspectorOpen = true;
    _peopleInspectorCandidates = false;
    _loadRootedPerson(id);
  }

  void _adoptCenteredPerson() {
    final id = _trackedPersonId;
    if (id == null || widget.controller.rootId != id) {
      return;
    }
    final person = widget.controller.personFor(id);
    if (person == null) {
      return;
    }
    _rootedPerson = person;
    _rootedPersonId = id;
    _rootedLoading = false;
    _rootedError = null;
  }

  Future<void> _loadRootedPerson(String personId) async {
    final token = ++_rootedToken;
    if (mounted) {
      setState(() {
        _rootedLoading = true;
        _rootedError = null;
        _rootedPerson = null;
        _rootedPersonId = personId;
      });
    }
    try {
      final workspace = await widget.apiClient.getPeopleWorkspace(rootId: personId);
      if (!mounted || token != _rootedToken) {
        return;
      }
      PersonPresentation? match;
      for (final person in workspace.people) {
        if (person.personId == personId) {
          match = person;
          break;
        }
      }
      setState(() {
        _rootedLoading = false;
        _rootedPerson = match;
        _rootedError = match == null ? 'Не удалось загрузить карточку человека' : null;
      });
    } catch (_) {
      if (!mounted || token != _rootedToken) {
        return;
      }
      setState(() {
        _rootedLoading = false;
        _rootedPerson = null;
        _rootedError = 'Не удалось загрузить карточку человека';
      });
    }
  }

  void _togglePeopleInspector() {
    setState(() {
      _peopleInspectorOpen = !_peopleInspectorOpen;
      if (_peopleInspectorOpen && _trackedPersonId == null) {
        _peopleInspectorCandidates = true;
      }
    });
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
    final nodes = widget.controller.visibleNodes;
    _transform.value = GraphLayout.fitTransform(
      positions: _drawnPositions(
        nodes: nodes,
        edges: widget.controller.visibleEdges,
      ),
      viewportSize: viewportSize,
      nodeSizes: _peopleOverviewCardSizes(nodes),
    );
  }

  Map<String, Offset> _drawnPositions({
    required List<SecretaryObject> nodes,
    required List<SecretaryEdge> edges,
  }) {
    final positions = Map<String, Offset>.from(widget.controller.visiblePositions);
    if (widget.controller.mode == GraphWorkspaceMode.tasks) {
      final canonical = _canonicalTaskTopLefts(nodes);
      if (canonical != null) {
        positions.addAll(canonical);
      } else {
        positions.addAll(
          projectTaskMapHierarchy(nodes: nodes, edges: edges).positions,
        );
      }
    } else if (widget.controller.rootId == null) {
      positions.addAll(_peopleOverviewPositions(nodes));
    }
    return positions;
  }

  /// Top-lefts for the unrooted Tasks overview when a complete canonical
  /// snapshot is installed. Null asks the caller to keep the temporary
  /// window layout, including when any visible Task has no center.
  Map<String, Offset>? _canonicalTaskTopLefts(List<SecretaryObject> nodes) {
    if (widget.controller.rootId != null ||
        !widget.controller.canonicalTaskCentersActive) {
      return null;
    }
    final centers = widget.controller.canonicalTaskCenters;
    final placed = <String, Offset>{};
    for (final node in nodes) {
      if (node.kind != 'task') {
        continue;
      }
      final center = centers[node.id];
      if (center == null) {
        return null;
      }
      placed[node.id] = taskLayoutCardTopLeft(center);
    }
    return placed;
  }

  Map<String, Offset> _peopleOverviewPositions(List<SecretaryObject> nodes) {
    final personIds = [
      for (final node in nodes)
        if (node.kind == 'person') node.id,
    ];
    final people = <PersonPresentation>[
      for (final id in personIds)
        if (widget.controller.personFor(id) case final person?) person,
    ];
    final projection = projectPeopleLandscapeOverview(
      personIds: personIds,
      people: people,
      landscapeTasks: widget.controller.landscapeTasks,
      landscapeTaskEdges: widget.controller.landscapeTaskEdges,
      landscapeTaskContextComplete: widget.controller.landscapeTaskContextComplete,
    );
    if (projection.usable) {
      return projection.positions;
    }
    return projectPeopleOverview(
      nodes: nodes,
      seedIds: widget.controller.seedIds,
      rootId: widget.controller.rootId,
    );
  }

  /// Compact card sizes for the unrooted People overview. Other modes keep
  /// the ordinary 186×100 node rectangle.
  Map<String, Size>? _peopleOverviewCardSizes(List<SecretaryObject> nodes) {
    if (!_compactPeopleOverview) {
      return null;
    }
    return {
      for (final node in nodes)
        node.id: node.kind == 'person'
            ? const Size(
                kPeopleLandscapeOverviewCardWidth,
                kPeopleLandscapeOverviewCardHeight,
              )
            : const Size(kGraphNodeWidth, kGraphNodeHeight),
    };
  }

  bool get _compactPeopleOverview =>
      widget.controller.mode == GraphWorkspaceMode.people &&
      widget.controller.rootId == null;

  @override
  Widget build(BuildContext context) {
    final isWide = MediaQuery.sizeOf(context).width >= 900;
    final selected = widget.controller.selectedObject;
    final peopleMode = widget.controller.mode == GraphWorkspaceMode.people;
    final showPeopleInspector = peopleMode && _peopleInspectorOpen;
    final showDesktopPane = isWide && (showPeopleInspector || (!peopleMode && selected != null));
    final canvas = KeyedSubtree(
      key: const ValueKey('graph-canvas-region'),
      child: _buildCanvas(context),
    );
    final details = peopleMode
        ? (showPeopleInspector ? _peopleInspector(context, compact: !isWide) : null)
        : selected == null
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
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      _truncationBanner(),
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ),
                  if (_showOverviewWindowControls) _overviewWindowControls(),
                ],
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
                    if (showPeopleInspector || (!peopleMode && selected != null))
                      Positioned(
                        left: 0,
                        right: 0,
                        bottom: 0,
                        child: Material(
                          elevation: 4,
                          child: peopleMode
                              ? SizedBox(
                                  height: MediaQuery.sizeOf(context).height * 0.45,
                                  child: details,
                                )
                              : ConstrainedBox(
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

  bool get _showOverviewWindowControls =>
      widget.controller.mode == GraphWorkspaceMode.tasks &&
      widget.controller.rootId == null &&
      widget.controller.windowCount > 1;

  Widget _overviewWindowControls() {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Tooltip(
          message: 'Предыдущая область графа',
          child: IconButton(
            key: const ValueKey('graph-overview-window-previous'),
            visualDensity: VisualDensity.compact,
            onPressed: widget.controller.hasPreviousWindow
                ? widget.controller.loadPreviousOverviewWindow
                : null,
            icon: const Icon(Icons.chevron_left),
          ),
        ),
        Text(
          key: const ValueKey('graph-overview-window-status'),
          'Область ${widget.controller.windowIndex + 1} из ${widget.controller.windowCount}',
        ),
        Tooltip(
          message: 'Следующая область графа',
          child: IconButton(
            key: const ValueKey('graph-overview-window-next'),
            visualDensity: VisualDensity.compact,
            onPressed: widget.controller.hasNextWindow
                ? widget.controller.loadNextOverviewWindow
                : null,
            icon: const Icon(Icons.chevron_right),
          ),
        ),
      ],
    );
  }

  String _truncationBanner() {
    final controller = widget.controller;
    if (controller.rootId == null &&
        controller.mode == GraphWorkspaceMode.tasks &&
        controller.semanticWindowComplete) {
      return 'Показана часть пространства графа: направления и соцветия в этой области показаны целиком. '
          'Перейдите в соседнюю область, чтобы увидеть остальные.';
    }
    return 'Карта показывает только часть графа. Скрытые связи и объекты могут существовать. '
        'Полный список прямых связей выбранного объекта — в панели сведений.';
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
          if (_showOverviewWindowControls && !widget.controller.truncated)
            _overviewWindowControls(),
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
          if (widget.controller.mode == GraphWorkspaceMode.people) ...[
            OutlinedButton.icon(
              onPressed: _openAddPerson,
              icon: const Icon(Icons.person_add_alt_1_outlined),
              label: const Text('Добавить человека'),
            ),
            OutlinedButton.icon(
              key: const ValueKey('people-inspector-toggle'),
              onPressed: _togglePeopleInspector,
              icon: Icon(
                _peopleInspectorOpen ? Icons.view_sidebar_outlined : Icons.view_sidebar,
              ),
              label: Text(_peopleInspectorCue()),
            ),
          ],
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

  Future<void> _openAddPerson() async {
    final created = await showDialog<SecretaryObject>(
      context: context,
      builder: (context) => _AddPersonDialog(
        onSubmit: (title) => widget.apiClient.createPerson(title: title),
      ),
    );
    if (created == null || !mounted) {
      return;
    }
    await widget.controller.reRoot(created.id);
  }

  String _peopleInspectorCue() {
    final count = widget.controller.promotionCandidates.length;
    if (count > 0) {
      return 'Кандидаты · $count';
    }
    return 'Кандидаты';
  }

  Widget _peopleInspector(BuildContext context, {required bool compact}) {
    final selected = widget.controller.selectedObject;
    final personSelected = selected != null && selected.kind == 'person';
    final showCandidates = !personSelected || _peopleInspectorCandidates;
    return Material(
      key: const ValueKey('people-inspector'),
      color: Theme.of(context).colorScheme.surface,
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(8, 4, 4, 4),
            child: Row(
              children: [
                if (personSelected)
                  Expanded(
                    child: SegmentedButton<bool>(
                      key: const ValueKey('people-inspector-switch'),
                      segments: const [
                        ButtonSegment(value: true, label: Text('Кандидаты')),
                        ButtonSegment(value: false, label: Text('Детали')),
                      ],
                      selected: {_peopleInspectorCandidates},
                      onSelectionChanged: (value) {
                        setState(() => _peopleInspectorCandidates = value.first);
                      },
                    ),
                  )
                else
                  Expanded(
                    child: Text(
                      'Кандидаты',
                      style: Theme.of(context).textTheme.titleSmall,
                    ),
                  ),
                IconButton(
                  key: const ValueKey('people-inspector-close'),
                  tooltip: 'Закрыть',
                  onPressed: () => setState(() => _peopleInspectorOpen = false),
                  icon: const Icon(Icons.close),
                ),
              ],
            ),
          ),
          Expanded(
            child: showCandidates
                ? _promotionQueue(context)
                : _buildDetailPanel(context, compact: compact),
          ),
        ],
      ),
    );
  }

  Widget _rootedPersonDetail(BuildContext context, String personId) {
    if (_rootedLoading || _rootedPersonId != personId) {
      return const Padding(
        key: ValueKey('person-detail-loading'),
        padding: EdgeInsets.symmetric(vertical: 24),
        child: Center(child: CircularProgressIndicator()),
      );
    }
    final person = _rootedPerson;
    if (_rootedError != null || person == null) {
      return Column(
        key: const ValueKey('person-detail-error'),
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(_rootedError ?? 'Не удалось загрузить карточку человека'),
          TextButton(
            key: const ValueKey('person-detail-retry'),
            onPressed: () => _loadRootedPerson(personId),
            child: const Text('Повторить'),
          ),
        ],
      );
    }
    return _PersonDetailSection(
      person: person,
      apiClient: widget.apiClient,
      onChanged: () async {
        await widget.controller.refreshCurrentWorkspace();
        await _loadRootedPerson(personId);
      },
      onRename: () => _renamePerson(person),
      onMerged: (survivorId) async {
        widget.controller.selectObject(survivorId);
        await widget.controller.refreshCurrentWorkspace();
        if (!mounted) {
          return;
        }
        await _loadRootedPerson(survivorId);
      },
      onOpenTask: (taskId) async {
        await widget.controller.setMode(GraphWorkspaceMode.tasks);
        if (!mounted) {
          return;
        }
        await widget.controller.reRoot(taskId);
      },
      onOpenFlow: (objectId) {
        return openObjectDetail(
          context,
          objectId: objectId,
          apiClient: widget.apiClient,
          authController: widget.authController,
          captureController: widget.captureController,
          assistantController: widget.assistantController,
          onAskSecretary: widget.onAskSecretary,
          onShowInGraph: widget.controller.reRoot,
          bookmarkController: widget.bookmarkController,
        );
      },
    );
  }

  Future<void> _renamePerson(PersonPresentation person) async {
    final title = await showDialog<String>(
      context: context,
      builder: (context) => _RenamePersonDialog(initialTitle: person.title),
    );
    final cleaned = title?.trim() ?? '';
    if (cleaned.isEmpty || !mounted) {
      return;
    }
    final updated = await widget.apiClient.patchObject(person.personId, {'title': cleaned});
    if (!mounted) {
      return;
    }
    widget.controller.upsertObject(updated);
    await widget.controller.refreshCurrentWorkspace();
    await _loadRootedPerson(person.personId);
  }

  Widget _promotionQueue(BuildContext context) {
    final controller = widget.controller;
    final count = controller.promotionCandidates.length;
    return Scrollbar(
      key: const ValueKey('promotion-review'),
      controller: _promotionScroll,
      thumbVisibility: true,
      child: ListView(
        key: const ValueKey('promotion-review-scroll'),
        controller: _promotionScroll,
        padding: const EdgeInsets.fromLTRB(12, 0, 16, 12),
        children: [
          if (count > 0 || controller.promotionCandidatesTruncated)
            Text(
              'Предлагаемые · $count',
              key: const ValueKey('promotion-review-title'),
              style: Theme.of(context).textTheme.titleSmall,
            ),
          const SizedBox(height: 8),
                        if (controller.promotionSuppressions.isNotEmpty) ...[
                          ExpansionTile(
                            key: const ValueKey('promotion-hidden-suggestions'),
                            tilePadding: EdgeInsets.zero,
                            initiallyExpanded: false,
                            title: Text(
                              'Скрытые предложения · ${controller.promotionSuppressions.length}',
                              style: Theme.of(context).textTheme.labelLarge,
                            ),
                            children: [
                              for (final item in controller.promotionSuppressions)
                                ListTile(
                                  dense: true,
                                  contentPadding: EdgeInsets.zero,
                                  title: Text(
                                    item.displayValue,
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                  subtitle: Text(
                                    '${providerLabel(item.provider)} · ${item.canonicalValue}',
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                  trailing: TextButton(
                                    onPressed: () => _applyPromotion(item, 'retract'),
                                    child: const Text('Вернуть'),
                                  ),
                                ),
                            ],
                          ),
                          const SizedBox(height: 8),
                        ],
                        if (controller.promotionCandidatesTruncated)
                          Padding(
                            padding: const EdgeInsets.only(bottom: 8),
                            child: Text(
                              'Показана часть предложений: просмотрены не все недавние сообщения.',
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                          ),
                        LayoutBuilder(
                          builder: (context, constraints) {
                            final cardWidth = constraints.maxWidth < 680
                                ? constraints.maxWidth
                                : 320.0;
                            return Wrap(
                              spacing: 8,
                              runSpacing: 8,
                              children: [
                                for (final candidate in controller.promotionCandidates)
                                  SizedBox(
                                    width: cardWidth,
                                    child: _promotionCandidate(context, candidate),
                                  ),
                              ],
                            );
                          },
                        ),
        ],
      ),
    );
  }

  Widget _promotionCandidate(BuildContext context, PersonPromotionCandidate candidate) {
    final scheme = Theme.of(context).colorScheme;
    final secondary = candidate.displayValue == candidate.canonicalValue
        ? null
        : candidate.canonicalValue;
    return Material(
      key: ValueKey('promotion-candidate-${candidate.canonicalValue}'),
      color: scheme.surface,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(10),
        side: BorderSide(color: scheme.outlineVariant),
      ),
      child: Padding(
        padding: const EdgeInsets.all(8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                CircleAvatar(
                  radius: 14,
                  backgroundColor: scheme.surfaceContainerHighest,
                  child: Icon(iconForKind('person'), size: 16, color: scheme.onSurfaceVariant),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    candidate.displayValue,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ),
            if (secondary != null)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  secondary,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: scheme.onSurfaceVariant,
                  ),
                ),
              ),
            const SizedBox(height: 4),
            Text(
              '${providerLabel(candidate.provider)} · ${_promotionExplanation(candidate)}',
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.labelSmall?.copyWith(
                color: scheme.onSurfaceVariant,
              ),
            ),
            const SizedBox(height: 6),
            Wrap(
              spacing: 4,
              children: [
                TextButton(
                  key: ValueKey('promotion-approve-${candidate.canonicalValue}'),
                  onPressed: () => _applyPromotion(candidate, 'approve'),
                  child: const Text('Добавить'),
                ),
                TextButton(
                  key: ValueKey('promotion-suppress-${candidate.canonicalValue}'),
                  onPressed: () => _applyPromotion(candidate, 'suppress'),
                  child: const Text('Не предлагать'),
                ),
              ],
            ),
            if (candidate.sources.isNotEmpty)
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  for (final source in candidate.sources.take(3))
                    _flowEvidenceTile(
                      context,
                      key: ValueKey(
                        'promotion-source-${candidate.canonicalValue}-${source.objectId}',
                      ),
                      kind: source.kind,
                      title: source.title ?? source.kind,
                      provider: source.provider,
                      occurredAt: source.occurredAt,
                      onTap: () => openObjectDetail(
                        context,
                        objectId: source.objectId,
                        apiClient: widget.apiClient,
                        authController: widget.authController,
                        captureController: widget.captureController,
                        assistantController: widget.assistantController,
                        onAskSecretary: widget.onAskSecretary,
                        onShowInGraph: widget.controller.reRoot,
                        bookmarkController: widget.bookmarkController,
                      ),
                    ),
                ],
              ),
          ],
        ),
      ),
    );
  }

  Widget _flowEvidenceTile(
    BuildContext context, {
    required Key key,
    required String kind,
    required String title,
    required String? provider,
    required String? occurredAt,
    required VoidCallback onTap,
  }) {
    final scheme = Theme.of(context).colorScheme;
    final when = _promotionWhen(occurredAt);
    return SizedBox(
      key: key,
      width: 148,
      child: Material(
        color: scheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(8),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(8),
          child: Padding(
            padding: const EdgeInsets.all(6),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(iconForKind(kind), size: 14, color: scheme.onSurfaceVariant),
                    const SizedBox(width: 4),
                    Expanded(
                      child: Text(
                        provider == null || provider.isEmpty ? kind : providerLabel(provider),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context).textTheme.labelSmall?.copyWith(
                          color: scheme.onSurfaceVariant,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                if (when != 'без даты')
                  Text(
                    when,
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
      ),
    );
  }

  Future<void> _applyPromotion(Object item, String action) async {
    final String identityType;
    final String provider;
    final String realm;
    final String canonicalValue;
    if (item is PersonPromotionCandidate) {
      identityType = item.identityType;
      provider = item.provider;
      realm = item.realm;
      canonicalValue = item.canonicalValue;
    } else if (item is PersonPromotionSuppression) {
      identityType = item.identityType;
      provider = item.provider;
      realm = item.realm;
      canonicalValue = item.canonicalValue;
    } else {
      return;
    }
    await widget.apiClient.applyPersonPromotion(
      action: action,
      identityType: identityType,
      provider: provider,
      realm: realm,
      canonicalValue: canonicalValue,
    );
    if (!mounted) {
      return;
    }
    await widget.controller.loadOverview();
  }

  String _promotionExplanation(PersonPromotionCandidate candidate) {
    final count = candidate.directHitCount;
    final hits = count == 1
        ? '1 прямой контакт'
        : count >= 2 && count <= 4
            ? '$count прямых контакта'
            : '$count прямых контактов';
    return '$hits · последнее ${_promotionWhen(candidate.latestOccurredAt)}';
  }

  String _promotionWhen(String? iso) {
    final parsed = iso == null ? null : DateTime.tryParse(iso);
    if (parsed == null) {
      return 'без даты';
    }
    final local = parsed.toLocal();
    final now = DateTime.now();
    final sameDay = local.year == now.year && local.month == now.month && local.day == now.day;
    if (sameDay) {
      return 'сегодня';
    }
    final day = local.day.toString().padLeft(2, '0');
    final month = local.month.toString().padLeft(2, '0');
    return '$day.$month.${local.year}';
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
    final positions = _drawnPositions(nodes: nodes, edges: edges);
    if (widget.controller.mode == GraphWorkspaceMode.people && nodes.isEmpty) {
      return const Center(child: Text('Добавьте человека, чтобы начать.'));
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
    if (hybrid != null &&
        widget.controller.rootId == null &&
        widget.controller.canonicalTaskCentersActive) {
      for (final node in nodes) {
        final topLeft = positions[node.id];
        if (node.kind == 'task' && topLeft != null) {
          hybrid.displayTopLeft[node.id] = node.isOngoingTask
              ? hybridOngoingRect(topLeft).topLeft
              : topLeft;
        }
      }
    }
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
    final overviewSizes = _peopleOverviewCardSizes(nodes);
    final bounds = hybrid != null
        ? hybridPresentationBounds(hybrid)
        : GraphLayout.computeBounds(positions, nodeSizes: overviewSizes);
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
                    nodeSizes: overviewSizes,
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
              child: Stack(
                children: [
                  _graphViewport(
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
                  if (widget.controller.taskLayoutWarning != null &&
                      widget.controller.mode == GraphWorkspaceMode.tasks &&
                      widget.controller.rootId == null)
                    Positioned(
                      left: 12,
                      right: 12,
                      top: 12,
                      child: IgnorePointer(
                        child: Material(
                        color: Theme.of(context).colorScheme.surfaceContainerHighest,
                        child: Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                          child: Text(
                            widget.controller.taskLayoutWarning!,
                            key: const ValueKey('task-layout-warning'),
                          ),
                        ),
                      ),
                      ),
                    ),
                ],
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
    final nodeSizes = <String, Size>{
      ...?_peopleOverviewCardSizes(nodes),
    };
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
              final ongoingAnchor = node.isOngoingTask;
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
                key: ValueKey('drawn-${node.id}'),
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
                        compact: _compactPeopleOverview && node.kind == 'person',
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

    final primaryDateValue = objectPrimaryDateDisplayValue(object);

    return ListView(
      key: const ValueKey('graph-detail-panel'),
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
              onPressed: () {
                if (widget.controller.mode == GraphWorkspaceMode.people) {
                  setState(() => _peopleInspectorOpen = false);
                } else {
                  widget.controller.selectObject(null);
                }
              },
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
              message: widget.controller.isLocalContextExpanded(object.id)
                  ? 'Скрыть связи'
                  : 'Показать связи',
              child: OutlinedButton.icon(
                onPressed: widget.controller.isLocalContextExpanded(object.id)
                    ? () => widget.controller.hideLocalContext(object.id)
                    : widget.controller.expandSelected,
                icon: Icon(
                  widget.controller.isLocalContextExpanded(object.id)
                      ? Icons.visibility_off_outlined
                      : Icons.hub_outlined,
                  size: 18,
                ),
                label: Text(
                  widget.controller.isLocalContextExpanded(object.id)
                      ? 'Скрыть связи'
                      : 'Показать связи',
                ),
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
        if (object.kind == 'person') ...[
          const SizedBox(height: 12),
          _rootedPersonDetail(context, object.id),
        ],
        const SizedBox(height: 12),
        _DetailSectionHeader(title: 'Связи'),
        _DirectRelationInventory(
          objectId: object.id,
          controller: widget.controller,
          apiClient: widget.apiClient,
          onAuthFailure: widget.authController.handleAuthenticationFailure,
          trailingBuilder: (edge) => _relationTrailing(context, edge),
        ),
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
                      isExpanded: true,
                      itemHeight: 48,
                      items: [
                        const DropdownMenuItem(
                          value: 'related_to',
                          child: GraphRelationChoiceLabel(
                            name: 'Связано с',
                            type: 'related_to',
                            meaning: 'симметричная связь',
                          ),
                        ),
                        const DropdownMenuItem(
                          value: 'references',
                          child: GraphRelationChoiceLabel(
                            name: 'Ссылается на',
                            type: 'references',
                            meaning: 'источник → цель',
                          ),
                        ),
                        const DropdownMenuItem(
                          value: 'depends_on',
                          child: GraphRelationChoiceLabel(
                            name: 'Зависит от',
                            type: 'depends_on',
                            meaning: 'зависимый → предпосылка',
                          ),
                        ),
                        if (source.kind == 'task')
                          const DropdownMenuItem(
                            value: 'part_of',
                            child: GraphRelationChoiceLabel(
                              name: 'Входит в',
                              type: 'part_of',
                              meaning: 'дочерняя → родитель',
                            ),
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
      await widget.controller.applyCreatedRelation(
        sourceId: source.id,
        sourceKind: source.kind,
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
      final sourceKind = widget.controller.nodeById(edge.sourceId)?.kind;
      final targetKind = widget.controller.nodeById(edge.targetId)?.kind;
      await widget.controller.applyDeletedRelation(
        edge,
        sourceKind: sourceKind,
        targetKind: targetKind,
      );
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
      final sourceKind = widget.controller.nodeById(edge.sourceId)?.kind;
      final targetKind = widget.controller.nodeById(edge.targetId)?.kind;
      await widget.controller.applyRelationDecision(
        previous: edge,
        updated: response.edge,
        sourceKind: sourceKind,
        targetKind: targetKind,
      );
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
    required this.onRename,
    required this.onMerged,
    required this.onOpenTask,
    required this.onOpenFlow,
  });

  final PersonPresentation person;
  final SecretaryApiClient apiClient;
  final Future<void> Function() onChanged;
  final Future<void> Function() onRename;
  final Future<void> Function(String survivorId) onMerged;
  final Future<void> Function(String taskId) onOpenTask;
  final Future<void> Function(String objectId) onOpenFlow;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final cues = person.identities
        .where((item) => item.state == 'effective')
        .map((item) => item.displayValue)
        .take(3)
        .join(' · ');
    final lastContact = _latestContactLabel(person);
    return Column(
      key: const ValueKey('person-summary-header'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            CircleAvatar(
              radius: 18,
              backgroundColor: scheme.surfaceContainerHighest,
              child: Icon(iconForKind('person'), color: scheme.onSurfaceVariant),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    person.title,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.titleLarge?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  TextButton(
                    key: const ValueKey('person-rename'),
                    onPressed: onRename,
                    child: const Text('Переименовать'),
                  ),
                  TextButton(
                    key: const ValueKey('person-merge'),
                    onPressed: () => _openMerge(context),
                    child: const Text('Объединить с…'),
                  ),
                  if (cues.isNotEmpty)
                    Text(
                      cues,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: scheme.onSurfaceVariant,
                      ),
                    ),
                ],
              ),
            ),
            if (person.identityConflict)
              Icon(
                Icons.report_outlined,
                color: scheme.error,
                semanticLabel: 'Конфликт идентичности',
              ),
          ],
        ),
        if (person.consolidations.isNotEmpty)
          for (final item in person.consolidations)
            Wrap(
              crossAxisAlignment: WrapCrossAlignment.center,
              spacing: 4,
              children: [
                Text('Объединено: ${item.duplicateTitle}'),
                if (item.undoAvailable)
                  TextButton(
                    key: ValueKey('person-merge-undo-${item.duplicateId}'),
                    onPressed: () async {
                      await apiClient.undoPersonMerge(
                        survivorId: person.personId,
                        duplicateId: item.duplicateId,
                      );
                      await onChanged();
                    },
                    child: const Text('Отменить'),
                  ),
              ],
            ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: [
            _metricChip(context, linkedTaskMetric(person.openTaskCount)),
            if (messageCountMetric(
                  person.recentCommunicationCount,
                  truncated: person.recentCommunicationCountTruncated,
                )
                case final message?)
              _metricChip(context, message)
            else
              Tooltip(
                message: 'Переписка посчитана не полностью',
                child: _metricChip(context, 'Сообщения · часть'),
              ),
            if (person.salience != null)
              _metricChip(context, personSalienceTierLabel(person.salience!.tier)),
            if (lastContact != null) _metricChip(context, 'Последний контакт · $lastContact'),
          ],
        ),
        const SizedBox(height: 12),
        const _DetailSectionHeader(title: 'Участие в задачах'),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton(
            key: const ValueKey('person-task-link'),
            onPressed: () => _linkTask(context),
            child: const Text('Связать с задачей'),
          ),
        ),
        if (person.taskInvolvement.isEmpty)
          const Text(
            'Нет участия в текущих задачах',
            key: ValueKey('person-task-empty'),
          )
        else
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: person.taskInvolvement.map((row) => _taskTile(context, row)).toList(),
          ),
        if (person.taskInvolvementTruncated) const Text('Показаны не все задачи'),
        const SizedBox(height: 8),
        const _DetailSectionHeader(title: 'Недавние сообщения'),
        if (person.recentCommunications.isEmpty)
          const Text(
            'Нет недавних коммуникаций',
            key: ValueKey('person-flow-empty'),
          )
        else
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: person.recentCommunications.map((row) => _flowTile(context, row)).toList(),
          ),
        if (person.recentCommunicationsTruncated) const Text('Показаны не все сообщения'),
        const SizedBox(height: 12),
        const _DetailSectionHeader(title: 'Известные контакты'),
        if (person.salience != null)
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton(
              onPressed: () => _addEmail(context),
              child: const Text('Добавить email'),
            ),
          ),
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
        if (person.salience != null &&
            (person.identityCandidates.isNotEmpty || person.identityCandidatesTruncated)) ...[
          const _DetailSectionHeader(title: 'Возможные контакты'),
          ...person.identityCandidates.map((candidate) => _candidateBlock(context, candidate)),
          if (person.identityCandidatesTruncated)
            const Text('Показаны не все возможные контакты'),
        ],
        if (person.salience != null && person.rejectedIdentityCandidates.isNotEmpty) ...[
          const _DetailSectionHeader(title: 'Отклонённые предложения'),
          ...person.rejectedIdentityCandidates.map(_rejectedCandidateRow),
        ],
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
        if (person.salience != null) ...[
          const _DetailSectionHeader(title: 'Активность'),
          Text(
            '${personSalienceTierLabel(person.salience!.tier)} · ${person.salience!.score}',
          ),
          const Text(
            'Сигнал активности и контекста, не оценка важности человека или сообщения.',
          ),
          if (person.salience!.truncated)
            const Text(
              'Показана часть активности: расчёт ограничен доступной выборкой коммуникаций.',
            ),
          ...person.salience!.components.map(
            (component) => Text(
              '${personSalienceComponentLabel(component.name)}: ${component.value}',
            ),
          ),
        ],
      ],
    );
  }

  Future<void> _openMerge(
    BuildContext context, {
    String? otherPersonId,
    String? identityCue,
  }) async {
    final survivorId = await showDialog<String>(
      context: context,
      builder: (context) => _MergePersonDialog(
        apiClient: apiClient,
        currentPersonId: person.personId,
        currentTitle: person.title,
        otherPersonId: otherPersonId,
        identityCue: identityCue,
      ),
    );
    if (survivorId == null) {
      return;
    }
    await onMerged(survivorId);
  }

  Widget _candidateBlock(BuildContext context, PersonIdentityCandidate candidate) {
    final exact = candidate.displayValue == candidate.canonicalValue
        ? ''
        : candidate.canonicalValue;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ListTile(
          dense: true,
          title: Text(candidate.displayValue),
          subtitle: Text(
            [
              providerLabel(candidate.provider),
              if (exact.isNotEmpty) exact,
              personCandidateExplanation(candidate.reasons),
              if (candidate.state == 'conflicted') 'конфликт',
            ].join(' · '),
          ),
        ),
        if (candidate.confirmable)
          Wrap(
            spacing: 4,
            children: [
              TextButton(
                onPressed: () => _correctTuple(candidate, 'confirm'),
                child: const Text('Подтвердить'),
              ),
              TextButton(
                onPressed: () => _correctTuple(candidate, 'reject'),
                child: const Text('Это не этот человек'),
              ),
            ],
          ),
        if (candidate.state == 'conflicted' && candidate.conflictingPersonId != null)
          TextButton(
            key: ValueKey('person-merge-conflict-${candidate.canonicalValue}'),
            onPressed: () => _openMerge(
              context,
              otherPersonId: candidate.conflictingPersonId,
              identityCue: candidate.displayValue == candidate.canonicalValue
                  ? candidate.canonicalValue
                  : '${candidate.displayValue} · ${candidate.canonicalValue}',
            ),
            child: const Text('Возможно, это один человек → Объединить'),
          ),
        ...candidate.sources.take(3).map(_flowRow),
      ],
    );
  }

  Widget _rejectedCandidateRow(PersonRejectedIdentityCandidate candidate) {
    return ListTile(
      dense: true,
      title: Text(candidate.displayValue),
      subtitle: Text(providerLabel(candidate.provider)),
      trailing: TextButton(
        onPressed: () => _correctTuple(candidate, 'retract'),
        child: const Text('Вернуть'),
      ),
    );
  }

  Future<void> _correctTuple(Object candidate, String action) async {
    final String identityType;
    final String provider;
    final String realm;
    final String canonicalValue;
    if (candidate is PersonIdentityCandidate) {
      identityType = candidate.identityType;
      provider = candidate.provider;
      realm = candidate.realm;
      canonicalValue = candidate.canonicalValue;
    } else if (candidate is PersonRejectedIdentityCandidate) {
      identityType = candidate.identityType;
      provider = candidate.provider;
      realm = candidate.realm;
      canonicalValue = candidate.canonicalValue;
    } else {
      return;
    }
    await apiClient.correctPersonIdentity(
      personId: person.personId,
      action: action,
      identityType: identityType,
      provider: provider,
      realm: realm,
      canonicalValue: canonicalValue,
    );
    await onChanged();
  }

  Widget _metricChip(BuildContext context, String label) {
    return Chip(
      visualDensity: VisualDensity.compact,
      label: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis),
      padding: EdgeInsets.zero,
    );
  }

  String? _latestContactLabel(PersonPresentation person) {
    DateTime? latest;
    for (final row in person.recentCommunications) {
      final parsed = DateTime.tryParse(row.occurredAt ?? '');
      if (parsed != null && (latest == null || parsed.isAfter(latest))) {
        latest = parsed;
      }
    }
    if (latest == null) {
      return null;
    }
    return _shortWhen(latest.toIso8601String());
  }

  Widget _taskTile(BuildContext context, PersonTaskInvolvement row) {
    final proposal = taskRelationProposalLabel(row.edgeOrigin, row.edgeState);
    final due = _shortWhen(row.dueAt);
    final kind = row.completionMode == 'ongoing' ? 'Направление' : 'Задача';
    final tileId = row.edgeId.isEmpty ? row.taskId : row.edgeId;
    final removable = row.edgeId.isNotEmpty &&
        row.edgeState == 'confirmed' &&
        (row.edgeOrigin == 'user' || row.edgeOrigin == 'agent');
    final proposed = row.edgeId.isNotEmpty && row.edgeState == 'proposed';
    return SizedBox(
      width: 168,
      child: Material(
        key: ValueKey('person-task-tile-$tileId'),
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            InkWell(
              onTap: () => onOpenTask(row.taskId),
              borderRadius: BorderRadius.circular(8),
              child: Padding(
                padding: const EdgeInsets.all(8),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      row.title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      [
                        kind,
                        personActorRoleLabel(row.role),
                        if (proposal.isNotEmpty) proposal,
                        if (due.isNotEmpty) due,
                      ].join(' · '),
                      maxLines: 3,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.labelSmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            if (proposed)
              Row(
                children: [
                  IconButton(
                    key: ValueKey('person-task-confirm-${row.edgeId}'),
                    tooltip: 'Подтвердить',
                    visualDensity: VisualDensity.compact,
                    icon: const Icon(Icons.check_circle_outline, size: 18),
                    onPressed: () => _changeTaskLink(
                      () => apiClient.decideRelation(edgeId: row.edgeId, decision: 'confirm'),
                    ),
                  ),
                  IconButton(
                    key: ValueKey('person-task-reject-${row.edgeId}'),
                    tooltip: 'Отклонить',
                    visualDensity: VisualDensity.compact,
                    icon: const Icon(Icons.cancel_outlined, size: 18),
                    onPressed: () => _changeTaskLink(
                      () => apiClient.decideRelation(edgeId: row.edgeId, decision: 'reject'),
                    ),
                  ),
                ],
              ),
            if (removable)
              IconButton(
                key: ValueKey('person-task-remove-${row.edgeId}'),
                tooltip: 'Убрать роль',
                visualDensity: VisualDensity.compact,
                icon: const Icon(Icons.close, size: 18),
                onPressed: () => _changeTaskLink(
                  () => apiClient.removeTaskActor(taskId: row.taskId, edgeId: row.edgeId),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _linkTask(BuildContext context) async {
    final selected = await showDialog<(String, String)>(
      context: context,
      builder: (context) => _LinkPersonTaskDialog(
        apiClient: apiClient,
        personTitle: person.title,
      ),
    );
    if (selected == null) {
      return;
    }
    await apiClient.addTaskActor(
      taskId: selected.$2,
      personId: person.personId,
      role: selected.$1,
    );
    await onChanged();
  }

  Future<void> _changeTaskLink(Future<Object?> Function() action) async {
    await action();
    await onChanged();
  }

  Widget _flowTile(BuildContext context, PersonFlowPreview row) {
    final when = _shortWhen(row.occurredAt);
    return SizedBox(
      width: 148,
      child: Material(
        key: ValueKey('person-flow-tile-${row.objectId}'),
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(8),
        child: InkWell(
          onTap: () => onOpenFlow(row.objectId),
          borderRadius: BorderRadius.circular(8),
          child: Padding(
            padding: const EdgeInsets.all(6),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(iconForKind(row.kind), size: 14),
                    const SizedBox(width: 4),
                    Expanded(
                      child: Text(
                        row.provider == null ? row.kind : providerLabel(row.provider!),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context).textTheme.labelSmall,
                      ),
                    ),
                  ],
                ),
                Text(
                  row.title ?? row.kind,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
                if (when.isNotEmpty)
                  Text(
                    when,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.labelSmall,
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _flowRow(PersonFlowPreview row) {
    final when = _shortWhen(row.occurredAt);
    return ListTile(
      dense: true,
      title: Text(row.title ?? row.kind),
      subtitle: Text(
        [
          if (row.provider != null) providerLabel(row.provider!),
          if (when.isNotEmpty) when,
        ].join(' · '),
      ),
      onTap: () => onOpenFlow(row.objectId),
    );
  }

  String _shortWhen(String? iso) {
    if (iso == null || iso.isEmpty) {
      return '';
    }
    final parsed = DateTime.tryParse(iso);
    if (parsed == null) {
      return '';
    }
    final local = parsed.toLocal();
    final day = local.day.toString().padLeft(2, '0');
    final month = local.month.toString().padLeft(2, '0');
    final hour = local.hour.toString().padLeft(2, '0');
    final minute = local.minute.toString().padLeft(2, '0');
    return '$day.$month.${local.year} $hour:$minute';
  }

  Future<void> _addEmail(BuildContext context) async {
    final added = await showDialog<bool>(
      context: context,
      builder: (context) => _AddPersonEmailDialog(
        onSubmit: (email) => apiClient.bindPersonEmail(
          personId: person.personId,
          email: email,
        ),
      ),
    );
    if (added == true) {
      await onChanged();
    }
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

String linkedTaskMetric(int count) => 'Связанные задачи · $count';

String? messageCountMetric(int count, {required bool truncated}) {
  if (truncated && count == 0) {
    return null;
  }
  if (truncated) {
    return 'Сообщения · ≥$count';
  }
  return 'Сообщения · $count';
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
    this.compact = false,
    this.person,
    this.bookmarkColor,
  });

  final SecretaryObject object;
  final bool selected;
  final bool focusDimmed;
  final VoidCallback onTap;
  final bool compact;
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
          width: compact ? kPeopleLandscapeOverviewCardWidth : kGraphNodeWidth,
          height: compact ? kPeopleLandscapeOverviewCardHeight : kGraphNodeHeight,
          padding: EdgeInsets.all(compact ? 6 : 8),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(10),
            border: Border.all(
              color: selected ? scheme.primary : scheme.outlineVariant,
              width: selected ? 2 : 1,
            ),
          ),
          child: object.kind == 'person'
              ? (compact
                    ? _compactPersonNodeBody(context, scheme)
                    : _personNodeBody(context, scheme))
              : _genericNodeBody(context, scheme),
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

  Widget _genericNodeBody(BuildContext context, ColorScheme scheme) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(iconForKind(object.kind), size: 16),
            const SizedBox(width: 4),
            Expanded(
              child: Text(
                humanTaskModeLabel(object),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.labelSmall,
              ),
            ),
            if (object.provider != null)
              SizedBox(
                width: 18,
                height: 18,
                child: FittedBox(child: providerBadge(context, object.provider!)),
              ),
          ],
        ),
        const SizedBox(height: 4),
        Expanded(
          child: Text(
            object.title,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(fontWeight: FontWeight.w600),
          ),
        ),
        Text(
          _graphNodeFooterLabel(object),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: Theme.of(context).textTheme.labelSmall?.copyWith(color: scheme.onSurfaceVariant),
        ),
      ],
    );
  }

  Widget _compactPersonNodeBody(BuildContext context, ColorScheme scheme) {
    final current = person;
    final cue = current == null
        ? ''
        : current.identities
              .where((item) => item.state == 'effective')
              .map((item) => providerLabel(item.provider))
              .where((label) => label.isNotEmpty)
              .take(2)
              .join(' · ');
    final shortCue = cue.length <= kPeopleLandscapeCompactCueLimit ? cue : '';
    return Column(
      key: ValueKey('person-summary-card-${object.id}'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                object.title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            if (current?.identityConflict ?? false)
              Icon(
                Icons.report_outlined,
                key: Key('person-identity-conflict-${object.id}'),
                size: 14,
                color: scheme.error,
                semanticLabel: 'Конфликт идентичности',
              ),
          ],
        ),
        if (shortCue.isNotEmpty)
          Text(
            shortCue,
            key: Key('person-provider-cues-${object.id}'),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: scheme.onSurfaceVariant,
            ),
          ),
      ],
    );
  }

  Widget _personNodeBody(BuildContext context, ColorScheme scheme) {
    final current = person;
    if (current == null) {
      return Row(
        children: [
          CircleAvatar(
            radius: 12,
            backgroundColor: scheme.surfaceContainerHighest,
            child: Icon(iconForKind('person'), size: 14, color: scheme.onSurfaceVariant),
          ),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              object.title,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w700),
            ),
          ),
        ],
      );
    }
    final cues = current.identities
        .where((item) => item.state == 'effective')
        .map((item) => providerLabel(item.provider))
        .take(2)
        .join(' · ');
    return Column(
      key: ValueKey('person-summary-card-${object.id}'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            CircleAvatar(
              radius: 12,
              backgroundColor: scheme.surfaceContainerHighest,
              child: Icon(iconForKind('person'), size: 14, color: scheme.onSurfaceVariant),
            ),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                object.title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            if (current.identityConflict)
              Icon(
                Icons.report_outlined,
                key: Key('person-identity-conflict-${object.id}'),
                size: 16,
                color: scheme.error,
                semanticLabel: 'Конфликт идентичности',
              ),
          ],
        ),
        if (cues.isNotEmpty)
          Text(
            cues,
            key: Key('person-provider-cues-${object.id}'),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(color: scheme.onSurfaceVariant),
          ),
        const Spacer(),
        Text(
          linkedTaskMetric(current.openTaskCount),
          key: Key('person-activity-footer-${object.id}'),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: Theme.of(context).textTheme.labelSmall?.copyWith(color: scheme.onSurfaceVariant),
        ),
        if (messageCountMetric(
              current.recentCommunicationCount,
              truncated: current.recentCommunicationCountTruncated,
            )
            case final message?)
          Text(
            message,
            key: Key('person-message-metric-${object.id}'),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(color: scheme.onSurfaceVariant),
          )
        else
          Tooltip(
            message: 'Переписка посчитана не полностью',
            child: Text(
              'Сообщения · часть',
              key: Key('person-message-partial-${object.id}'),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.labelSmall?.copyWith(color: scheme.onSurfaceVariant),
            ),
          ),
      ],
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
            ..color = colorScheme.tertiary.withValues(
              alpha: dimmed ? 0.28 : 0.34,
            ),
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

class _AddPersonEmailDialog extends StatefulWidget {
  const _AddPersonEmailDialog({required this.onSubmit});

  final Future<void> Function(String email) onSubmit;

  @override
  State<_AddPersonEmailDialog> createState() => _AddPersonEmailDialogState();
}

class _AddPersonEmailDialogState extends State<_AddPersonEmailDialog> {
  final _email = TextEditingController();
  var _submitting = false;
  String? _error;

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final email = _email.text.trim();
    if (email.isEmpty || _submitting) {
      return;
    }
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      await widget.onSubmit(email);
      if (!mounted) {
        return;
      }
      Navigator.of(context).pop(true);
    } on ApiException catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _submitting = false;
        _error = _emailBindError(error);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final canSubmit = _email.text.trim().isNotEmpty && !_submitting;
    return AlertDialog(
      title: const Text('Добавить email'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          TextField(
            controller: _email,
            autofocus: true,
            decoration: const InputDecoration(
              labelText: 'Email',
              helperText:
                  'Добавляется только точный адрес, который вы подтверждаете как принадлежащий этому человеку.',
            ),
            onChanged: (_) => setState(() {}),
            onSubmitted: canSubmit ? (_) => _submit() : null,
          ),
          if (_error != null) ...[
            const SizedBox(height: 8),
            Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
        ],
      ),
      actions: [
        TextButton(
          onPressed: _submitting ? null : () => Navigator.of(context).pop(),
          child: const Text('Отмена'),
        ),
        FilledButton(
          onPressed: canSubmit ? _submit : null,
          child: const Text('Добавить'),
        ),
      ],
    );
  }
}

String _emailBindError(ApiException error) {
  final message = error.message;
  if (message.contains('already bound')) {
    return 'Этот email уже принадлежит другому человеку.';
  }
  if (message.contains('malformed')) {
    return 'Укажите точный email.';
  }
  return message;
}

class _MergePersonDialog extends StatefulWidget {
  const _MergePersonDialog({
    required this.apiClient,
    required this.currentPersonId,
    required this.currentTitle,
    this.otherPersonId,
    this.identityCue,
  });

  final SecretaryApiClient apiClient;
  final String currentPersonId;
  final String currentTitle;
  final String? otherPersonId;
  final String? identityCue;

  @override
  State<_MergePersonDialog> createState() => _MergePersonDialogState();
}

class _MergePersonDialogState extends State<_MergePersonDialog> {
  final _query = TextEditingController();
  List<PersonPresentation> _results = const [];
  String? _otherId;
  var _currentSurvives = true;
  PersonMergePreview? _preview;
  var _busy = false;

  @override
  void initState() {
    super.initState();
    _otherId = widget.otherPersonId;
    if (_otherId != null) {
      _loadPreview();
    }
  }

  @override
  void dispose() {
    _query.dispose();
    super.dispose();
  }

  Future<void> _search(String value) async {
    final cleaned = value.trim();
    if (cleaned.isEmpty) {
      setState(() => _results = const []);
      return;
    }
    final found = await widget.apiClient.getPeopleWorkspace(query: cleaned, seedLimit: 24);
    if (!mounted) {
      return;
    }
    setState(() {
      _results = found.people.where((item) => item.personId != widget.currentPersonId).toList();
    });
  }

  Future<void> _loadPreview() async {
    final otherId = _otherId;
    if (otherId == null) {
      return;
    }
    final survivorId = _currentSurvives ? widget.currentPersonId : otherId;
    final duplicateId = _currentSurvives ? otherId : widget.currentPersonId;
    final preview = await widget.apiClient.previewPersonMerge(
      survivorId: survivorId,
      duplicateId: duplicateId,
    );
    if (!mounted) {
      return;
    }
    setState(() => _preview = preview);
  }

  Future<void> _confirm() async {
    final preview = _preview;
    if (preview == null || !preview.canMerge || _busy) {
      return;
    }
    setState(() => _busy = true);
    final survivorId = await widget.apiClient.applyPersonMerge(
      survivorId: preview.survivorId,
      duplicateId: preview.duplicateId,
    );
    if (!mounted) {
      return;
    }
    Navigator.of(context).pop(survivorId);
  }

  @override
  Widget build(BuildContext context) {
    final preview = _preview;
    final viewport = MediaQuery.sizeOf(context).width;
    return AlertDialog(
      title: const Text('Объединить с…'),
      content: SizedBox(
        width: viewport < 480 ? viewport - 112 : 360,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              key: const ValueKey('person-merge-search'),
              controller: _query,
              decoration: const InputDecoration(labelText: 'Найти человека'),
              onChanged: _search,
            ),
            for (final item in _results)
              ListTile(
                key: ValueKey('person-merge-option-${item.personId}'),
                title: Text(item.title),
                onTap: () {
                  setState(() => _otherId = item.personId);
                  _loadPreview();
                },
              ),
            if (widget.identityCue != null)
              Text(
                'Предложен из-за контакта: ${widget.identityCue}',
                key: const ValueKey('person-merge-conflict-cue'),
              ),
            if (preview != null) ...[
              const SizedBox(height: 8),
              Text(
                'Остаётся: ${preview.survivorTitle}',
                key: const ValueKey('person-merge-survivor'),
              ),
              Text(
                'Исчезает: ${preview.duplicateTitle}',
                key: const ValueKey('person-merge-duplicate'),
              ),
              Text('Контакты: ${preview.identityCount}'),
              for (final cue in preview.identities) Text(cue),
              Text('Связанные задачи: ${preview.actorCounts.values.fold<int>(0, (sum, value) => sum + value)}'),
              if (preview.blockers.isNotEmpty)
                Text(preview.blockers.join(' '), key: const ValueKey('person-merge-blocker')),
              TextButton(
                key: const ValueKey('person-merge-swap'),
                onPressed: () {
                  setState(() => _currentSurvives = !_currentSurvives);
                  _loadPreview();
                },
                child: const Text('Поменять, кто останется'),
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Отмена')),
        FilledButton(
          key: const ValueKey('person-merge-confirm'),
          onPressed: preview != null && preview.canMerge && !_busy ? _confirm : null,
          child: const Text('Объединить людей'),
        ),
      ],
    );
  }
}

class _LinkPersonTaskDialog extends StatefulWidget {
  const _LinkPersonTaskDialog({required this.apiClient, required this.personTitle});

  final SecretaryApiClient apiClient;
  final String personTitle;

  @override
  State<_LinkPersonTaskDialog> createState() => _LinkPersonTaskDialogState();
}

class _LinkPersonTaskDialogState extends State<_LinkPersonTaskDialog> {
  static const _roles = [
    'requested_by',
    'delegated_to',
    'waiting_on',
    'involves',
  ];

  final _query = TextEditingController();
  String? _role;
  SecretaryObject? _task;
  List<SecretaryObject> _results = const [];

  @override
  void dispose() {
    _query.dispose();
    super.dispose();
  }

  Future<void> _search(String value) async {
    final cleaned = value.trim();
    if (cleaned.isEmpty) {
      setState(() => _results = const []);
      return;
    }
    final found = await widget.apiClient.searchObjects(query: cleaned, kind: 'task');
    if (!mounted) {
      return;
    }
    setState(() {
      _results = found
          .where(
            (item) =>
                item.kind == 'task' &&
                item.deletedAt == null &&
                !isTerminalTaskStatusForReads(item.status),
          )
          .toList();
    });
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Связать с задачей'),
      content: SizedBox(
        width: 360,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 6,
              children: [
                for (final role in _roles)
                  ChoiceChip(
                    key: ValueKey('person-task-role-$role'),
                    label: Text(personTaskLinkChoiceLabel(role)),
                    selected: _role == role,
                    onSelected: (selected) => setState(() => _role = selected ? role : null),
                  ),
              ],
            ),
            TextField(
              key: const ValueKey('person-task-search'),
              controller: _query,
              decoration: const InputDecoration(labelText: 'Найти задачу'),
              onChanged: _search,
            ),
            for (final item in _results)
              ListTile(
                key: ValueKey('person-task-option-${item.id}'),
                title: Text(item.title),
                subtitle: Text(
                  [
                    taskStatusLabel(item.status),
                    if (item.dueAt != null && item.dueAt!.isNotEmpty) item.dueAt!,
                  ].join(' · '),
                ),
                selected: _task?.id == item.id,
                onTap: () => setState(() => _task = item),
              ),
            if (_role != null && _task != null)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Text(
                  personTaskLinkFact(
                    role: _role!,
                    personTitle: widget.personTitle,
                    taskTitle: _task!.title,
                  ),
                  key: const ValueKey('person-task-role-summary'),
                ),
              ),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Отмена')),
        FilledButton(
          key: const ValueKey('person-task-add'),
          onPressed: _role == null || _task == null
              ? null
              : () => Navigator.of(context).pop((_role!, _task!.id)),
          child: const Text('Добавить'),
        ),
      ],
    );
  }
}

class _RenamePersonDialog extends StatefulWidget {
  const _RenamePersonDialog({required this.initialTitle});

  final String initialTitle;

  @override
  State<_RenamePersonDialog> createState() => _RenamePersonDialogState();
}

class _RenamePersonDialogState extends State<_RenamePersonDialog> {
  late final TextEditingController _name = TextEditingController(text: widget.initialTitle);

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Переименовать'),
      content: TextField(
        controller: _name,
        autofocus: true,
        decoration: const InputDecoration(labelText: 'Имя'),
        onSubmitted: (value) => Navigator.of(context).pop(value),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Отмена'),
        ),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(_name.text),
          child: const Text('Сохранить'),
        ),
      ],
    );
  }
}

class _AddPersonDialog extends StatefulWidget {
  const _AddPersonDialog({required this.onSubmit});

  final Future<SecretaryObject> Function(String title) onSubmit;

  @override
  State<_AddPersonDialog> createState() => _AddPersonDialogState();
}

class _AddPersonDialogState extends State<_AddPersonDialog> {
  final _name = TextEditingController();
  var _submitting = false;

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final title = _name.text.trim();
    if (title.isEmpty || _submitting) {
      return;
    }
    setState(() => _submitting = true);
    try {
      final created = await widget.onSubmit(title);
      if (!mounted) {
        return;
      }
      Navigator.of(context).pop(created);
    } on ApiException catch (error) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error.message)));
      setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final canSubmit = _name.text.trim().isNotEmpty && !_submitting;
    return AlertDialog(
      title: const Text('Добавить человека'),
      content: TextField(
        controller: _name,
        autofocus: true,
        decoration: const InputDecoration(
          labelText: 'Имя',
          helperText:
              'Контакты и связанные аккаунты можно подтвердить после создания.',
        ),
        onChanged: (_) => setState(() {}),
        onSubmitted: canSubmit ? (_) => _submit() : null,
      ),
      actions: [
        TextButton(
          onPressed: _submitting ? null : () => Navigator.of(context).pop(),
          child: const Text('Отмена'),
        ),
        FilledButton(
          onPressed: canSubmit ? _submit : null,
          child: const Text('Добавить'),
        ),
      ],
    );
  }
}

class _DirectRelationInventory extends StatefulWidget {
  const _DirectRelationInventory({
    required this.objectId,
    required this.controller,
    required this.apiClient,
    required this.onAuthFailure,
    required this.trailingBuilder,
  });

  final String objectId;
  final GraphWorkspaceController controller;
  final SecretaryApiClient apiClient;
  final VoidCallback onAuthFailure;
  final Widget? Function(SecretaryEdge edge) trailingBuilder;

  @override
  State<_DirectRelationInventory> createState() => _DirectRelationInventoryState();
}

class _DirectRelationInventoryState extends State<_DirectRelationInventory> {
  List<NeighborOut> _neighbors = const [];
  String? _error;
  int _requestGeneration = 0;
  String _loadedSignature = '';

  @override
  void initState() {
    super.initState();
    _loadedSignature = _edgeSignature(widget.controller);
    _load();
  }

  @override
  void didUpdateWidget(covariant _DirectRelationInventory oldWidget) {
    super.didUpdateWidget(oldWidget);
    final signature = _edgeSignature(widget.controller);
    if (oldWidget.objectId != widget.objectId || signature != _loadedSignature) {
      _loadedSignature = signature;
      _load();
    }
  }

  String _edgeSignature(GraphWorkspaceController controller) {
    return controller.edges.map((edge) => '${edge.id}:${edge.state}').join('|');
  }

  Future<void> _load() async {
    final generation = ++_requestGeneration;
    final objectId = widget.objectId;
    try {
      final response = await widget.apiClient.getObjectNeighbors(objectId);
      if (!mounted || generation != _requestGeneration || widget.objectId != objectId) {
        return;
      }
      setState(() {
        _neighbors = response.neighbors;
        _error = null;
      });
    } on AuthenticationException {
      widget.onAuthFailure();
    } on ApiException {
      if (!mounted || generation != _requestGeneration) {
        return;
      }
      setState(() {
        _error = 'Не удалось загрузить полный список связей.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final rows = <_RelationRow>[];
    final seen = <String>{};
    for (final edge in widget.controller.edges) {
      if (edge.sourceId != widget.objectId && edge.targetId != widget.objectId) {
        continue;
      }
      final otherId = edge.sourceId == widget.objectId ? edge.targetId : edge.sourceId;
      final other = widget.controller.nodeById(otherId);
      rows.add(
        _RelationRow(
          edge: edge,
          otherId: otherId,
          sourceTitle: widget.controller.nodeById(edge.sourceId)?.title ?? edge.sourceId,
          targetTitle: widget.controller.nodeById(edge.targetId)?.title ?? edge.targetId,
          onMap: other != null,
        ),
      );
      seen.add(edge.id);
    }
    for (final neighbor in _neighbors) {
      if (seen.contains(neighbor.edge.id)) {
        continue;
      }
      final onMap = widget.controller.nodeById(neighbor.object.id) != null;
      final sourceIsSelected = neighbor.edge.sourceId == widget.objectId;
      rows.add(
        _RelationRow(
          edge: neighbor.edge,
          otherId: neighbor.object.id,
          sourceTitle: sourceIsSelected ? 'Этот объект' : neighbor.object.title,
          targetTitle: sourceIsSelected ? neighbor.object.title : 'Этот объект',
          onMap: onMap,
        ),
      );
      seen.add(neighbor.edge.id);
    }

    return Column(
      children: [
        for (final row in rows)
          ListTile(
            key: ValueKey('graph-relation-${row.edge.id}'),
            dense: true,
            selected: widget.controller.selectedEdgeId == row.edge.id,
            onTap: () {
              widget.controller.selectEdge(row.edge.id);
              if (widget.controller.nodeById(row.otherId) != null) {
                widget.controller.selectObject(row.otherId);
              } else {
                widget.controller.reRoot(row.otherId);
              }
            },
            leading: row.edge.state == 'proposed'
                ? Icon(
                    Icons.diamond_outlined,
                    size: 16,
                    color: Theme.of(context).colorScheme.tertiary,
                    key: ValueKey('graph-relation-proposed-${row.edge.id}'),
                  )
                : null,
            title: Text(
              graphRelationAuditText(
                edge: row.edge,
                sourceTitle: row.sourceTitle,
                targetTitle: row.targetTitle,
                selectedObjectId: widget.objectId,
              ),
              key: ValueKey('graph-relation-audit-${row.edge.id}'),
            ),
            subtitle: Text(
              row.onMap
                  ? '${originLabel(row.edge.origin)} · ${provenanceStateLabel(row.edge.state)}'
                  : '${originLabel(row.edge.origin)} · ${provenanceStateLabel(row.edge.state)} · не на карте',
              key: row.onMap ? null : ValueKey('graph-off-canvas-${row.edge.id}'),
            ),
            trailing: widget.trailingBuilder(row.edge),
          ),
        if (_error != null)
          ListTile(
            key: const ValueKey('graph-relation-inventory-error'),
            dense: true,
            title: Text(_error!),
            trailing: TextButton(
              key: const ValueKey('graph-relation-inventory-retry'),
              onPressed: _load,
              child: const Text('Повторить'),
            ),
          ),
      ],
    );
  }
}

class _RelationRow {
  const _RelationRow({
    required this.edge,
    required this.otherId,
    required this.sourceTitle,
    required this.targetTitle,
    required this.onMap,
  });

  final SecretaryEdge edge;
  final String otherId;
  final String sourceTitle;
  final String targetTitle;
  final bool onMap;
}
