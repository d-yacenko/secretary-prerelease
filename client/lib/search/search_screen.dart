import 'package:flutter/material.dart';

import '../api/api_error.dart';
import '../api/api_models.dart';
import '../api/secretary_api_client.dart';
import '../assistant/assistant_controller.dart';
import '../auth/auth_controller.dart';
import '../capture/capture_controller.dart';
import '../navigation/app_route_observer.dart';
import '../navigation/secretary_navigation.dart';
import '../ui/assigned_labels_loader.dart';
import '../ui/compact_object_filters.dart';
import '../ui/domain_labels.dart';
import '../ui/object_bookmark.dart';
import '../ui/object_bookmark_controller.dart';
import '../ui/object_dates.dart';
import '../ui/object_label_strip.dart';
import '../ui/object_presentation.dart';

enum SearchLoadState { idle, loading, ready, empty, error }

class SearchScreen extends StatefulWidget {
  const SearchScreen({
    super.key,
    required this.apiClient,
    required this.authController,
    required this.captureController,
    this.assistantController,
    this.onAskSecretary,
    this.onShowInGraph,
    this.bookmarkController,
  });

  final SecretaryApiClient apiClient;
  final AuthController authController;
  final CaptureController captureController;
  final AssistantController? assistantController;
  final AskSecretaryHandler? onAskSecretary;
  final ShowInGraphHandler? onShowInGraph;
  final ObjectBookmarkController? bookmarkController;

  @override
  State<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends State<SearchScreen> with RouteAware {
  final _queryController = TextEditingController();
  SearchLoadState _loadState = SearchLoadState.idle;
  List<SecretaryObject> _results = [];
  String? _errorMessage;
  String? _selectedKind;
  String? _selectedProvider;
  String _selectedSort = 'relevance';
  SearchFacetsOut? _facets;
  List<LabelItem> _labels = [];
  Map<String, List<LabelItem>> _assignedByObject = {};
  String? _selectedLabelId;
  late final ObjectBookmarkController _bookmarks;
  var _ownsBookmarks = false;

  @override
  void initState() {
    super.initState();
    final provided = widget.bookmarkController;
    if (provided != null) {
      _bookmarks = provided;
    } else {
      _ownsBookmarks = true;
      _bookmarks = ObjectBookmarkController(
        apiClient: widget.apiClient,
        authController: widget.authController,
      );
    }
    _bookmarks.addListener(_onBookmarksChanged);
    _loadFacets();
    _loadLabels();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final route = ModalRoute.of(context);
    if (route != null) {
      appRouteObserver.subscribe(this, route);
    }
  }

  @override
  void didPopNext() {
    _loadLabels();
  }

  Future<void> _loadFacets() async {
    try {
      final facets = await widget.apiClient.getSearchFacets();
      if (mounted) {
        setState(() => _facets = facets);
      }
    } catch (_) {}
  }

  Future<void> _loadLabels() async {
    try {
      final result = await widget.apiClient.listLabels();
      if (!mounted) {
        return;
      }
      final selectedId = _selectedLabelId;
      final selectedStillExists = selectedId == null ||
          result.labels.any((label) => label.id == selectedId);
      final rerunSearch =
          !selectedStillExists && _queryController.text.trim().isNotEmpty;
      setState(() {
        _labels = result.labels;
        if (!selectedStillExists) {
          _selectedLabelId = null;
        }
      });
      if (rerunSearch) {
        await _search();
      }
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException {
      if (mounted) {
        setState(() => _labels = []);
      }
    }
  }

  @override
  void dispose() {
    _bookmarks.removeListener(_onBookmarksChanged);
    if (_ownsBookmarks) {
      _bookmarks.dispose();
    }
    appRouteObserver.unsubscribe(this);
    _queryController.dispose();
    super.dispose();
  }

  void _onBookmarksChanged() {
    if (mounted) {
      setState(() {});
    }
  }

  Future<void> _search() async {
    final query = _queryController.text.trim();
    if (query.isEmpty) {
      return;
    }
    if (!mounted) {
      return;
    }
    setState(() {
      _loadState = SearchLoadState.loading;
      _errorMessage = null;
    });

    try {
      final results = await widget.apiClient.searchObjects(
        query: query,
        kind: _selectedKind,
        provider: _selectedProvider,
        sort: _selectedSort,
        labelId: _selectedLabelId,
      );
      if (!mounted) {
        return;
      }
      setState(() {
        _results = results;
        _loadState = results.isEmpty ? SearchLoadState.empty : SearchLoadState.ready;
      });
      final assigned = await loadAssignedLabelsByObjects(
        apiClient: widget.apiClient,
        onAuthFailure: widget.authController.handleAuthenticationFailure,
        objectIds: results.map((item) => item.id),
      );
      if (!mounted) {
        return;
      }
      setState(() => _assignedByObject = assigned);
      await _bookmarks.reconcileVisible(results.map((item) => item.id));
      if (!mounted) {
        return;
      }
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (!mounted) {
        return;
      }
      setState(() {
        _loadState = SearchLoadState.error;
        _errorMessage = e.message;
      });
    }
  }

  Future<void> _openObject(SecretaryObject object) async {
    final result = await openObjectDetail(
      context,
      objectId: object.id,
      apiClient: widget.apiClient,
      authController: widget.authController,
      captureController: widget.captureController,
      assistantController: widget.assistantController,
      onAskSecretary: widget.onAskSecretary,
      onShowInGraph: widget.onShowInGraph,
      bookmarkController: _bookmarks,
    );
    if (!mounted) {
      return;
    }
    if (result != null) {
      setState(() {
        _results =
            _results.where((row) => row.id != result.deletedObjectId).toList();
        if (_results.isEmpty && _loadState == SearchLoadState.ready) {
          _loadState = SearchLoadState.empty;
        }
      });
      _bookmarks.forget(result.deletedObjectId);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _queryController,
                      decoration: const InputDecoration(
                        labelText: 'Поиск',
                        hintText: 'Найти задачи, письма, проекты…',
                        border: OutlineInputBorder(),
                      ),
                      textInputAction: TextInputAction.search,
                      onSubmitted: (_) => _search(),
                    ),
                  ),
                  CompactObjectFilters(
                    facets: _facets,
                    selectedKind: _selectedKind,
                    selectedProvider: _selectedProvider,
                    selectedSort: _selectedSort,
                    showSort: true,
                    labels: _labels,
                    selectedLabelId: _selectedLabelId,
                    onLabelChanged: (value) {
                      setState(() => _selectedLabelId = value);
                      if (_queryController.text.trim().isNotEmpty) {
                        _search();
                      }
                    },
                    onKindChanged: (value) {
                      setState(() => _selectedKind = value);
                      if (_queryController.text.trim().isNotEmpty) {
                        _search();
                      }
                    },
                    onProviderChanged: (value) {
                      setState(() => _selectedProvider = value);
                      if (_queryController.text.trim().isNotEmpty) {
                        _search();
                      }
                    },
                    onSortChanged: (value) {
                      setState(() => _selectedSort = value);
                      if (_queryController.text.trim().isNotEmpty) {
                        _search();
                      }
                    },
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Align(
                alignment: Alignment.centerRight,
                child: FilledButton(
                  onPressed: _loadState == SearchLoadState.loading ? null : _search,
                  child: const Text('Поиск'),
                ),
              ),
            ],
          ),
        ),
        Expanded(child: _buildBody()),
      ],
    );
  }

  Widget _buildBody() {
    switch (_loadState) {
      case SearchLoadState.idle:
        return const Center(child: Text('Введите запрос и нажмите «Поиск»'));
      case SearchLoadState.loading:
        return const Center(child: CircularProgressIndicator());
      case SearchLoadState.empty:
        return const Center(child: Text('Ничего не найдено'));
      case SearchLoadState.error:
        return Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(_errorMessage ?? 'Ошибка поиска'),
              const SizedBox(height: 12),
              FilledButton(onPressed: _search, child: const Text('Повторить')),
            ],
          ),
        );
      case SearchLoadState.ready:
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
              child: Text(
                'Показано: ${_results.length}',
                style: Theme.of(context).textTheme.labelMedium,
              ),
            ),
            Expanded(
              child: ListView.separated(
                itemCount: _results.length,
                separatorBuilder: (_, __) => const Divider(height: 1),
                itemBuilder: (context, index) {
                  final object = _results[index];
                  return _SearchResultTile(
                    object: object,
                    labels: _assignedByObject[object.id] ?? const [],
                    bookmarkColor: _bookmarks.colorFor(object.id),
                    onBookmarkSelect: (color) =>
                        _bookmarks.setColor(object.id, color),
                    onBookmarkClear: () => _bookmarks.clear(object.id),
                    onTap: () => _openObject(object),
                  );
                },
              ),
            ),
          ],
        );
    }
  }
}

class _SearchResultTile extends StatelessWidget {
  const _SearchResultTile({
    required this.object,
    required this.labels,
    this.bookmarkColor,
    required this.onBookmarkSelect,
    required this.onBookmarkClear,
    required this.onTap,
  });

  final SecretaryObject object;
  final List<LabelItem> labels;
  final String? bookmarkColor;
  final ValueChanged<String> onBookmarkSelect;
  final VoidCallback onBookmarkClear;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final snippet = SearchResultSnippet.fromBody(object.body);
    final dateLabel = objectPrimaryDateLabel(object);
    final statusLine = _statusLine(object, snippet);

    return MouseRegion(
      cursor: SystemMouseCursors.click,
      child: ObjectBookmarkRibbon(
        color: bookmarkColor,
        onSelect: onBookmarkSelect,
        onClear: onBookmarkClear,
        child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ObjectCompactHeaderRow(
                title: object.title,
                kind: object.kind,
                provider: object.provider,
                trailingText: dateLabel,
                trailingReserve:
                    bookmarkColor != null ? kBookmarkRibbonReserve : 0,
              ),
              if (statusLine.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 2),
                  child: Text(
                    statusLine,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.bodySmall,
                  ),
                ),
              ObjectMetaActionRow(
                actions: [
                  if (bookmarkColor == null)
                    ObjectBookmarkControl(
                      color: bookmarkColor,
                      onSelect: onBookmarkSelect,
                      onClear: onBookmarkClear,
                    ),
                ],
                labels: labels,
              ),
            ],
          ),
        ),
        ),
        ),
    );
  }

  String _statusLine(SecretaryObject object, String snippet) {
    if (object.kind == 'task' && object.status != null) {
      return taskStatusLabel(object.status);
    }
    if (snippet.isNotEmpty) {
      return snippet;
    }
    if (object.state.isNotEmpty) {
      return provenanceStateLabel(object.state);
    }
    return '';
  }
}
