import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/api_error.dart';
import '../api/api_models.dart';
import '../api/secretary_api_client.dart';
import '../auth/auth_controller.dart';
import '../assistant/assistant_controller.dart';
import '../capture/capture_controller.dart';
import '../navigation/secretary_navigation.dart';
import '../navigation/source_navigation_presenter.dart';
import '../navigation/source_navigation_service.dart';
import '../objects/object_delete_actions.dart';
import '../objects/object_labels_section.dart';
import '../tasks/task_management_actions.dart';
import '../ui/app_spacing.dart';
import '../ui/date_format.dart';
import '../ui/domain_labels.dart';
import '../ui/linkified_text.dart';
import '../ui/object_actions.dart';
import '../ui/object_bookmark.dart';
import '../ui/object_bookmark_controller.dart';
import '../ui/object_dates.dart';
import '../ui/object_presentation.dart';
import '../ui/provider_icon.dart';

enum ObjectDetailLoadState { loading, ready, error }

class ObjectDetailScreen extends StatefulWidget {
  const ObjectDetailScreen({
    super.key,
    required this.objectId,
    required this.apiClient,
    required this.authController,
    required this.captureController,
    this.assistantController,
    this.onAskSecretary,
    this.onShowInGraph,
    this.onTaskUpdated,
    this.bookmarkController,
  });

  final String objectId;
  final SecretaryApiClient apiClient;
  final AuthController authController;
  final CaptureController captureController;
  final AssistantController? assistantController;
  final AskSecretaryHandler? onAskSecretary;
  final ShowInGraphHandler? onShowInGraph;
  final ValueChanged<SecretaryObject>? onTaskUpdated;
  final ObjectBookmarkController? bookmarkController;

  @override
  State<ObjectDetailScreen> createState() => _ObjectDetailScreenState();
}

class _ObjectDetailScreenState extends State<ObjectDetailScreen> {
  ObjectDetailLoadState _loadState = ObjectDetailLoadState.loading;
  SecretaryObject? _object;
  List<NeighborOut> _neighbors = [];
  ContextResponse? _context;
  SourceActionPresentation? _sourcePresentation;
  String? _errorMessage;
  late final SourceNavigationService _sourceNavigation;
  late final SourceNavigationPresenter _sourcePresenter;
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
    _sourceNavigation = SourceNavigationService(apiClient: widget.apiClient);
    _sourcePresenter = SourceNavigationPresenter();
    _load();
  }

  @override
  void dispose() {
    _bookmarks.removeListener(_onBookmarksChanged);
    if (_ownsBookmarks) {
      _bookmarks.dispose();
    }
    super.dispose();
  }

  void _onBookmarksChanged() {
    if (mounted) {
      setState(() {});
    }
  }

  Future<void> _load() async {
    if (!mounted) {
      return;
    }
    setState(() {
      _loadState = ObjectDetailLoadState.loading;
      _errorMessage = null;
    });

    try {
      final object = await widget.apiClient.getObject(widget.objectId);
      if (!mounted) {
        return;
      }
      final neighbors = await widget.apiClient.getObjectNeighbors(widget.objectId);
      if (!mounted) {
        return;
      }
      final context = await widget.apiClient.getObjectContext(widget.objectId);
      if (!mounted) {
        return;
      }
      OpenTarget openTarget;
      SourceActionPresentation? sourcePresentation;
      try {
        openTarget = await widget.apiClient.getOpenTarget(widget.objectId);
        sourcePresentation = await _sourcePresenter.present(openTarget);
      } on ApiException {
        openTarget = OpenTarget(
          available: false,
          action: 'unavailable',
          label: 'Открыть в источнике',
        );
        sourcePresentation = null;
      }
      if (!mounted) {
        return;
      }
      setState(() {
        _object = object;
        _neighbors = neighbors.neighbors;
        _context = context;
        _sourcePresentation = sourcePresentation;
        _loadState = ObjectDetailLoadState.ready;
      });
      await _bookmarks.reconcileVisible([widget.objectId]);
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (!mounted) {
        return;
      }
      setState(() {
        _loadState = ObjectDetailLoadState.error;
        _errorMessage = e.message;
      });
    }
  }

  void _useAsTaskContext() {
    final object = _object;
    if (object == null) {
      return;
    }
    widget.captureController.attachObjectContext(object);
    openCapture(
      context,
      captureController: widget.captureController,
      authController: widget.authController,
    );
  }

  void _askSecretary() {
    final object = _object;
    if (object == null || widget.onAskSecretary == null) {
      return;
    }
    widget.onAskSecretary!(object);
    Navigator.of(context).pop();
  }

  void _notifyTaskUpdated(SecretaryObject updated) {
    setState(() => _object = updated);
    widget.onTaskUpdated?.call(updated);
  }

  Future<void> _openSource() async {
    try {
      await _sourceNavigation.launchForObject(widget.objectId);
    } on SourceLaunchException catch (e) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    } on ApiException catch (e) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  Future<void> _showInFolder() async {
    final path = _sourcePresentation?.localPath;
    if (path == null) {
      return;
    }
    try {
      await _sourceNavigation.showInFolder(path);
    } on SourceLaunchException catch (e) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  List<NeighborOut> get _attachmentNeighbors {
    final object = _object;
    if (object == null || object.kind != 'email') {
      return [];
    }
    return _neighbors.where(
      (neighbor) =>
          neighbor.edge.type == 'contains' &&
          neighbor.direction == 'outgoing' &&
          neighbor.object.kind == 'file' &&
          neighbor.edge.metadata['source_fact'] == 'email_attachment',
    ).toList();
  }

  bool get _showDeleteAction {
    final object = _object;
    return object != null && !object.isTombstoned && object.kind != 'label';
  }

  Future<void> _openNeighborDetail(String objectId) async {
    final result = await openObjectDetail(
      context,
      objectId: objectId,
      apiClient: widget.apiClient,
      authController: widget.authController,
      captureController: widget.captureController,
      assistantController: widget.assistantController,
      onAskSecretary: widget.onAskSecretary,
      onShowInGraph: widget.onShowInGraph,
      onTaskUpdated: widget.onTaskUpdated,
      bookmarkController: _bookmarks,
    );
    if (!mounted || result == null) {
      return;
    }
    setState(() {
      _neighbors = _neighbors
          .where((neighbor) => neighbor.object.id != result.deletedObjectId)
          .toList();
      final contextResponse = _context;
      if (contextResponse != null) {
        _context = ContextResponse(
          object: contextResponse.object,
          edges: contextResponse.edges,
          neighbors: contextResponse.neighbors
              .where((neighbor) => neighbor.id != result.deletedObjectId)
              .toList(),
        );
      }
    });
  }

  Future<void> _deleteObject() async {
    final object = _object;
    if (object == null) {
      return;
    }
    final deleted = await confirmAndDeleteObject(
      context,
      object: object,
      apiClient: widget.apiClient,
      authController: widget.authController,
    );
    if (!mounted || !deleted) {
      return;
    }
    Navigator.of(context).pop(
      ObjectDetailNavigationResult(deletedObjectId: object.id),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_object?.title ?? 'Объект'),
        actions: [
          if (_showDeleteAction)
            IconButton(
              key: const Key('object_detail_delete'),
              tooltip: 'Удалить из Секретаря',
              icon: const Icon(Icons.delete_outline),
              onPressed: _deleteObject,
            ),
          if (_object != null && widget.onShowInGraph != null)
            OpenInGraphAction(
              onPressed: () {
                widget.onShowInGraph!(_object!.id);
                Navigator.of(context).pop();
              },
            ),
          if (_object != null && widget.onAskSecretary != null)
            AskSecretaryAction(onPressed: _askSecretary),
          if (_object != null)
            TextButton(
              onPressed: _useAsTaskContext,
              child: const Text('Использовать как контекст задачи'),
            ),
        ],
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    switch (_loadState) {
      case ObjectDetailLoadState.loading:
        return const Center(child: CircularProgressIndicator());
      case ObjectDetailLoadState.error:
        return Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(_errorMessage ?? 'Не удалось загрузить объект'),
              const SizedBox(height: 12),
              FilledButton(onPressed: _load, child: const Text('Повторить')),
            ],
          ),
        );
      case ObjectDetailLoadState.ready:
        final object = _object!;
        final primaryDateValue = objectPrimaryDateDisplayValue(object);
        final plannedIntervalValue = objectPlannedIntervalDisplayValue(object);
        final wide = isWideLayout(context);
        final bookmarkColor = _bookmarks.colorFor(object.id);
        return SelectionArea(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: ObjectBookmarkRibbon(
              color: bookmarkColor,
              onSelect: (color) => _bookmarks.setColor(object.id, color),
              onClear: () => _bookmarks.clear(object.id),
              child: Padding(
                padding: EdgeInsets.only(
                  right: bookmarkColor != null ? kBookmarkRibbonReserve : 0,
                ),
                child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.xs,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  Icon(iconForKind(object.kind), size: AppSpacing.kindIconSize),
                  if (providerHasIdentity(object.provider))
                    ProviderSourceIcon(
                      provider: object.provider,
                      onPressed: _sourcePresentation?.canOpen == true
                          ? _openSource
                          : null,
                      openTooltip: _sourcePresentation?.canOpen == true
                          ? (_sourcePresentation!.openLabel ??
                              'Открыть в источнике')
                          : providerLabel(object.provider),
                    ),
                  Text(
                    objectKindLabel(object.kind),
                    style: Theme.of(context).textTheme.labelLarge,
                  ),
                  if (primaryDateValue.isNotEmpty)
                    Text(
                      primaryDateValue,
                      style: Theme.of(context).textTheme.bodyMedium,
                    ),
                  if (plannedIntervalValue != null)
                    Text(
                      key: const Key('object_planned_interval'),
                      'Запланированное время: $plannedIntervalValue',
                      style: Theme.of(context).textTheme.bodyMedium,
                    ),
                  if (object.status != null)
                    Text(taskStatusLabel(object.status)),
                  if (object.state == 'proposed')
                    Text(
                      provenanceStateLabel(object.state),
                      style: Theme.of(context).textTheme.labelMedium,
                    ),
                  if (bookmarkColor == null)
                    ObjectBookmarkControl(
                      color: bookmarkColor,
                      onSelect: (color) =>
                          _bookmarks.setColor(object.id, color),
                      onClear: () => _bookmarks.clear(object.id),
                    ),
                ],
              ),
              if (_sourcePresentation != null) ...[
                if (_sourcePresentation!.canOpen && !wide)
                  Padding(
                    padding: const EdgeInsets.only(top: AppSpacing.sm),
                    child: OpenSourceAction(
                      key: const Key('object_detail_open_source'),
                      onPressed: _openSource,
                      label: _sourcePresentation!.openLabel ??
                          'Открыть в источнике',
                    ),
                  ),
                if (_sourcePresentation!.canOpen && wide)
                  Align(
                    alignment: Alignment.centerLeft,
                    child: OpenSourceAction(
                      key: const Key('object_detail_open_source'),
                      onPressed: _openSource,
                      label: _sourcePresentation!.openLabel ??
                          'Открыть в источнике',
                    ),
                  ),
                if (_sourcePresentation!.canShowInFolder)
                  Align(
                    alignment: Alignment.centerLeft,
                    child: TextButton(
                      key: const Key('object_detail_show_in_folder'),
                      onPressed: _showInFolder,
                      child: Text(_sourcePresentation!.showInFolderLabel),
                    ),
                  ),
                if (_sourcePresentation!.isDisabled)
                  Padding(
                    padding: const EdgeInsets.only(top: AppSpacing.sm),
                    child: Text(
                      _sourcePresentation!.disabledReason!,
                      style: TextStyle(color: Theme.of(context).colorScheme.error),
                    ),
                  ),
              ],
              if (object.body != null && object.body!.trim().isNotEmpty) ...[
                const SizedBox(height: AppSpacing.md),
                LinkifiedText(
                  key: const Key('object_detail_body'),
                  text: object.body!,
                ),
              ],
              const SizedBox(height: AppSpacing.lg),
              if (object.kind == 'label')
                Text(
                  'Управлять метками можно в разделе Аккаунт.',
                  style: Theme.of(context).textTheme.bodySmall,
                )
              else
                ObjectLabelsSection(
                  key: const Key('object_labels_section'),
                  objectId: object.id,
                  apiClient: widget.apiClient,
                  authController: widget.authController,
                ),
              if (_attachmentNeighbors.isNotEmpty) ...[
                const SizedBox(height: AppSpacing.lg),
                Text('Вложения', style: Theme.of(context).textTheme.titleMedium),
                ..._attachmentNeighbors.map(
                  (neighbor) => ListTile(
                    leading: const Icon(Icons.attach_file),
                    title: Text(neighbor.object.title),
                    subtitle: Text(_attachmentSubtitle(neighbor.object)),
                    onTap: () => _openNeighborDetail(neighbor.object.id),
                  ),
                ),
              ],
              const SizedBox(height: AppSpacing.lg),
              ExpansionTile(
                key: const Key('object_detail_technical'),
                tilePadding: EdgeInsets.zero,
                title: const Text('Подробности'),
                children: [
                  _FieldRow(label: 'Состояние', value: provenanceStateLabel(object.state)),
                  _FieldRow(label: 'Источник', value: originLabel(object.origin)),
                  _FieldRow(
                    label: 'Создано',
                    value: formatUserDateTime(object.createdAt),
                  ),
                  _FieldRow(
                    label: 'Обновлено',
                    value: formatUserDateTime(object.updatedAt),
                  ),
                  if (object.provider != null)
                    _FieldRow(
                      label: 'Провайдер',
                      value: providerLabel(object.provider!),
                    ),
                  if (object.canonicalUri != null)
                    _CanonicalUriRow(uri: object.canonicalUri!),
                ],
              ),
              const SizedBox(height: AppSpacing.lg),
              Text('Связи', style: Theme.of(context).textTheme.titleMedium),
              if (_neighbors.isEmpty)
                const Padding(
                  padding: EdgeInsets.only(top: 8),
                  child: Text('Нет связей'),
                )
              else
                ..._neighbors.map(
                  (neighbor) => ListTile(
                    title: Text(neighbor.object.title),
                    subtitle: Text(
                      '${relationTypeLabel(neighbor.edge.type)} • '
                      '${neighborDirectionLabel(neighbor.direction)} • '
                      '${objectKindLabel(neighbor.object.kind)}',
                    ),
                    onTap: () => _openNeighborDetail(neighbor.object.id),
                  ),
                ),
              const SizedBox(height: 16),
              if (_object != null)
                TaskManagementActions(
                  task: _object!,
                  apiClient: widget.apiClient,
                  authController: widget.authController,
                  onTaskUpdated: _notifyTaskUpdated,
                ),
              const SizedBox(height: 16),
              Text('Контекст', style: Theme.of(context).textTheme.titleMedium),
              if (_context == null || _context!.neighbors.isEmpty)
                const Padding(
                  padding: EdgeInsets.only(top: 8),
                  child: Text('Нет соседнего контекста'),
                )
              else
                ..._context!.neighbors.map(
                  (neighbor) => ListTile(
                    title: Text(neighbor.title),
                    subtitle: Text(objectKindLabel(neighbor.kind)),
                  ),
                ),
            ],
                ),
              ),
            ),
          ),
        );
    }
  }

  String _attachmentSubtitle(SecretaryObject attachment) {
    final mime = attachment.metadata['mime_type']?.toString();
    final size = attachment.metadata['size'];
    final parts = <String>[];
    if (mime != null && mime.isNotEmpty) {
      parts.add(mime);
    }
    if (size != null) {
      parts.add('$size B');
    }
    if (parts.isEmpty) {
      return objectKindLabel(attachment.kind);
    }
    return parts.join(' • ');
  }
}

class _FieldRow extends StatelessWidget {
  const _FieldRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: Theme.of(context).textTheme.labelLarge),
          Text(value),
        ],
      ),
    );
  }
}

class _CanonicalUriRow extends StatelessWidget {
  const _CanonicalUriRow({required this.uri});

  final String uri;

  @override
  Widget build(BuildContext context) {
    final sanitized = _stripCredentials(uri);
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Канонический URI', style: Theme.of(context).textTheme.labelLarge),
          SelectableText(
            sanitized,
            onTap: () => Clipboard.setData(ClipboardData(text: sanitized)),
          ),
        ],
      ),
    );
  }

  String _stripCredentials(String value) {
    final parsed = Uri.tryParse(value);
    if (parsed == null) {
      return value;
    }
    if (parsed.userInfo.isEmpty) {
      return value;
    }
    return parsed.replace(userInfo: '').toString();
  }
}
