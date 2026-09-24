import 'dart:io';

import 'package:desktop_drop/desktop_drop.dart';
import 'package:flutter/foundation.dart' show defaultTargetPlatform, kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/api_error.dart';
import '../api/api_models.dart';
import '../api/secretary_api_client.dart';
import '../assistant/assistant_controller.dart';
import '../auth/auth_controller.dart';
import '../capture/capture_controller.dart';
import '../local/local_intake_actions.dart';
import '../navigation/secretary_navigation.dart';
import '../sources/source_refresh_service.dart';
import '../sources/source_sync_error_presentation.dart';
import '../navigation/source_navigation_service.dart';
import '../ui/assigned_labels_loader.dart';
import '../ui/app_spacing.dart';
import '../ui/date_format.dart';
import '../ui/inbox_date_groups.dart';
import '../ui/object_actions.dart';
import '../ui/object_bookmark.dart';
import '../ui/object_bookmark_controller.dart';
import '../ui/object_label_strip.dart';
import '../ui/object_presentation.dart';
import '../ui/passive_snapshot_refresh.dart';
import '../ui/provider_icon.dart';
import '../voice/voice_transcription_controller.dart';
import '../objects/object_delete_actions.dart';
import 'inbox_conversation_groups.dart';
import 'inbox_feed_merge.dart';
import 'inbox_intake_url.dart';
import 'inbox_swipe_to_remove.dart';
import 'notification_labels.dart';

enum InboxLoadState { loading, ready, error }

/// High-visibility Inbox review marker accent. Same color on light and dark.
const Color kInboxReviewMarkerAccent = Color(0xFFFF4D2E);

/// Touch Review Rail hit width. Visible guide is 1–2 px inside this area.
const double kInboxReviewRailHitWidth = 36;

/// Compact vertical gap between Inbox source cards (Android and desktop).
/// The review rail continues through this strip; a tap there still means AFTER
/// that object.
const double kInboxSourceCardGap = 4;

/// Indent for expanded Conversation Stack children. Does not shift the rail.
const double kInboxStackChildIndent = 16;

bool inboxUsesTouchReviewRail([TargetPlatform? platform]) {
  final resolved = platform ?? defaultTargetPlatform;
  return resolved == TargetPlatform.android || resolved == TargetPlatform.iOS;
}

/// Click/tap review rail: phones plus desktop. Independent of Swipe-to-Remove.
bool inboxUsesReviewRail([TargetPlatform? platform]) {
  if (kIsWeb) {
    return false;
  }
  final resolved = platform ?? defaultTargetPlatform;
  return resolved == TargetPlatform.android ||
      resolved == TargetPlatform.iOS ||
      resolved == TargetPlatform.linux ||
      resolved == TargetPlatform.windows ||
      resolved == TargetPlatform.macOS;
}

/// Swipe-to-Remove stays touch-only. Desktop uses click-rail + optional drag.
bool inboxUsesSwipeToRemove([TargetPlatform? platform]) {
  return inboxUsesTouchReviewRail(platform);
}

class InboxScreen extends StatefulWidget {
  const InboxScreen({
    super.key,
    required this.apiClient,
    required this.authController,
    required this.captureController,
    this.assistantController,
    this.onAskSecretary,
    this.onAskSecretaryAboutNotification,
    this.onShowInGraph,
    this.passiveRefreshInterval = kPassiveSnapshotRefreshInterval,
    this.sourceRefreshTimeout,
    this.sourceRefreshPollInterval,
    this.bookmarkController,
  });

  final SecretaryApiClient apiClient;
  final AuthController authController;
  final CaptureController captureController;
  final AssistantController? assistantController;
  final AskSecretaryHandler? onAskSecretary;
  final void Function(NotificationOut notification)?
  onAskSecretaryAboutNotification;
  final ShowInGraphHandler? onShowInGraph;
  final Duration passiveRefreshInterval;
  final Duration? sourceRefreshTimeout;
  final Duration? sourceRefreshPollInterval;
  final ObjectBookmarkController? bookmarkController;

  @override
  State<InboxScreen> createState() => InboxScreenState();
}

class InboxScreenState extends State<InboxScreen> {
  InboxLoadState _loadState = InboxLoadState.loading;
  InboxOut? _inbox;
  List<InboxSourceObjectOut> _feedObjects = [];
  List<InboxConversationGroup> _conversationGroups = [];
  final Set<String> _expandedStackIds = <String>{};
  Map<String, List<LabelItem>> _labelsByObject = {};
  InboxReviewMarker? _reviewMarker;
  String? _markerError;
  String? _errorMessage;
  String? _mutatingNotificationId;
  String? _refreshStatusMessage;
  String? _intakeErrorMessage;
  String? _nextCursor;
  String? _loadMoreError;
  bool _hasMore = false;
  bool _isLoadingMore = false;
  bool _loadedContinuation = false;
  bool _isSourceRefreshing = false;
  bool _isIntakePending = false;
  bool _isDragHovering = false;
  String? _markerHoverObjectId;

  final TextEditingController _intakeController = TextEditingController();
  late final VoiceTranscriptionController _voice;

  late final SourceRefreshService _sourceRefreshService = SourceRefreshService(
    apiClient: widget.apiClient,
  );
  late final SourceNavigationService _sourceNavigation =
      SourceNavigationService(apiClient: widget.apiClient);
  late final PassiveSnapshotRefresh _passiveRefresh;
  late final LocalIntakeActions _localIntakeActions;
  final ScrollController _feedScrollController = ScrollController();
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
    _localIntakeActions = LocalIntakeActions(
      apiClient: widget.apiClient,
      authController: widget.authController,
      forInbox: true,
      onIntakeSuccess: _onLocalIntakeSuccess,
    );
    _voice = VoiceTranscriptionController(
      apiClient: widget.apiClient,
      authController: widget.authController,
    );
    _voice.bindTranscriptConsumer(_handleVoiceTranscript);
    _voice.addListener(_onVoiceChanged);
    _passiveRefresh = PassiveSnapshotRefresh(
      interval: widget.passiveRefreshInterval,
      isPaused: () => _isSourceRefreshing,
      onRefresh: () => _loadInbox(showFullLoader: false, passive: true),
    );
    _passiveRefresh.attach();
    _feedScrollController.addListener(_onFeedScroll);
    _loadInbox();
  }

  @override
  void dispose() {
    _bookmarks.removeListener(_onBookmarksChanged);
    if (_ownsBookmarks) {
      _bookmarks.dispose();
    }
    _voice.removeListener(_onVoiceChanged);
    _voice.dispose();
    _intakeController.dispose();
    _feedScrollController.dispose();
    _passiveRefresh.dispose();
    super.dispose();
  }

  void _onBookmarksChanged() {
    if (mounted) {
      setState(() {});
    }
  }

  void _onVoiceChanged() {
    if (mounted) {
      setState(() {});
    }
  }

  Future<void> _handleVoiceTranscript(String transcript) async {
    final trimmed = transcript.trim();
    if (trimmed.isEmpty) {
      return;
    }
    final current = _intakeController.text;
    if (current.isEmpty) {
      _intakeController.text = trimmed;
    } else {
      _intakeController.text = '$current $trimmed';
    }
    _intakeController.selection = TextSelection.collapsed(
      offset: _intakeController.text.length,
    );
  }

  bool get isIntakePending => _isIntakePending;

  Future<void> handleDroppedPaths(List<String> paths) async {
    if (_isIntakePending || paths.isEmpty) {
      return;
    }
    await _localIntakeActions.registerDroppedFiles(context, paths);
  }

  void _onFeedScroll() {
    if (!_feedScrollController.hasClients) {
      return;
    }
    if (_feedScrollController.position.extentAfter < 480) {
      _loadMore();
    }
  }

  void _scheduleFeedPrefetch() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) {
        return;
      }
      _onFeedScroll();
    });
  }

  Future<void> _onLocalIntakeSuccess() async {
    await _loadInbox(showFullLoader: false);
  }

  Future<void> _loadInbox({
    bool showFullLoader = true,
    bool passive = false,
  }) async {
    if (!mounted) {
      return;
    }
    if (passive && (_isSourceRefreshing || _isLoadingMore)) {
      return;
    }
    if (showFullLoader && !passive) {
      setState(() {
        _loadState = InboxLoadState.loading;
        _errorMessage = null;
        _loadMoreError = null;
      });
    }

    try {
      final snapshot = await widget.apiClient.getInbox();
      if (!mounted) {
        return;
      }
      final firstPageIds = snapshot.recentSourceObjects
          .map((item) => item.id)
          .toSet();
      final preserveTail =
          _loadedContinuation ||
          _isLoadingMore ||
          _feedObjects.any((item) => !firstPageIds.contains(item.id));
      final mergedFeed = mergeInboxFeedHead(
        existing: _feedObjects,
        firstPage: snapshot.recentSourceObjects,
        preserveTail: preserveTail,
      );
      setState(() {
        _inbox = snapshot;
        _feedObjects = mergedFeed;
        if (!preserveTail) {
          _conversationGroups = List<InboxConversationGroup>.of(
            snapshot.conversationGroups,
          );
          _nextCursor = snapshot.recentNextCursor;
          _hasMore = snapshot.recentHasMore;
          _loadedContinuation = false;
        } else {
          _conversationGroups = [
            ...snapshot.conversationGroups,
            ..._conversationGroups.where(
              (group) =>
                  group.coveredIds.every((id) => !firstPageIds.contains(id)),
            ),
          ];
        }
        _loadState = InboxLoadState.ready;
        _refreshStatusMessage =
            SourceRefreshService.clearSyncContinuesMessageIfSettled(
              message: _refreshStatusMessage,
              statuses: snapshot.sourceSyncStatus,
            );
      });
      _scheduleFeedPrefetch();
      final labelIds = preserveTail
          ? snapshot.recentSourceObjects.map((item) => item.id)
          : mergedFeed.map((item) => item.id);
      final labels = await loadAssignedLabelsByObjects(
        apiClient: widget.apiClient,
        onAuthFailure: widget.authController.handleAuthenticationFailure,
        objectIds: labelIds,
      );
      if (!mounted) {
        return;
      }
      setState(() {
        if (preserveTail) {
          _labelsByObject = {..._labelsByObject, ...labels};
        } else {
          _labelsByObject = labels;
        }
      });
      final bookmarkIds = preserveTail
          ? snapshot.recentSourceObjects.map((item) => item.id)
          : mergedFeed.map((item) => item.id);
      await _bookmarks.reconcileVisible(bookmarkIds);
      if (!mounted) {
        return;
      }
      setState(() {
        _reviewMarker = snapshot.reviewMarker;
      });
      _scheduleFeedPrefetch();
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (!mounted) {
        return;
      }
      if (passive && _inbox != null) {
        return;
      }
      setState(() {
        _loadState = InboxLoadState.error;
        _errorMessage = e.message;
      });
    }
  }

  Future<void> _loadMore() async {
    if (_isLoadingMore || !_hasMore || _nextCursor == null) {
      return;
    }
    _isLoadingMore = true;
    setState(() {
      _loadMoreError = null;
    });
    final cursor = _nextCursor!;
    try {
      final page = await widget.apiClient.getInboxFeed(cursor: cursor);
      if (!mounted) {
        _isLoadingMore = false;
        return;
      }
      final known = _feedObjects.map((item) => item.id).toSet();
      final appended = [
        for (final item in page.items)
          if (!known.contains(item.id)) item,
      ];
      setState(() {
        _feedObjects = [..._feedObjects, ...appended];
        _conversationGroups = [
          ..._conversationGroups,
          ...page.conversationGroups,
        ];
        _nextCursor = page.nextCursor;
        _hasMore = page.hasMore;
        _isLoadingMore = false;
        if (appended.isNotEmpty) {
          _loadedContinuation = true;
        }
      });
      _scheduleFeedPrefetch();
      if (appended.isEmpty) {
        return;
      }
      final labels = await loadAssignedLabelsByObjects(
        apiClient: widget.apiClient,
        onAuthFailure: widget.authController.handleAuthenticationFailure,
        objectIds: appended.map((item) => item.id),
      );
      if (!mounted) {
        return;
      }
      setState(() => _labelsByObject = {..._labelsByObject, ...labels});
      await _bookmarks.reconcileVisible(appended.map((item) => item.id));
    } on AuthenticationException {
      _isLoadingMore = false;
      if (mounted) {
        setState(() {});
      }
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      _isLoadingMore = false;
      if (!mounted) {
        return;
      }
      setState(() {
        _loadMoreError = e.message;
      });
    }
  }

  bool get _reviewRail => inboxUsesReviewRail();

  bool get _swipeToRemove => inboxUsesSwipeToRemove();

  bool get _desktopMarkerDrag => !_swipeToRemove;

  Widget _touchContentInset(Widget child) {
    if (!_reviewRail) {
      return child;
    }
    return Padding(
      padding: const EdgeInsets.only(left: AppSpacing.lg),
      child: child,
    );
  }

  void _onReviewRailTap(String? afterObjectId) {
    if (_swipeToRemove) {
      HapticFeedback.selectionClick();
    }
    _persistReviewMarker(afterObjectId);
  }

  Future<void> _persistReviewMarker(String? afterObjectId) async {
    final previous = _reviewMarker;
    try {
      if (afterObjectId == null) {
        await widget.apiClient.deleteInboxReviewMarker();
        if (!mounted) {
          return;
        }
        setState(() {
          _reviewMarker = null;
          _markerError = null;
        });
        return;
      }
      final saved = await widget.apiClient.putInboxReviewMarker(afterObjectId);
      if (!mounted) {
        return;
      }
      setState(() {
        _reviewMarker = saved;
        _markerError = null;
      });
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (!mounted) {
        return;
      }
      setState(() {
        _reviewMarker = previous;
        _markerError = e.message;
      });
    }
  }

  Future<void> _refreshWithSources() async {
    if (!mounted) {
      return;
    }
    setState(() {
      _isSourceRefreshing = true;
      _refreshStatusMessage = null;
      if (_inbox == null) {
        _loadState = InboxLoadState.loading;
      }
    });
    try {
      final result = await _sourceRefreshService.refreshSources(
        timeout:
            widget.sourceRefreshTimeout ?? SourceRefreshService.defaultTimeout,
        pollInterval:
            widget.sourceRefreshPollInterval ??
            SourceRefreshService.pollInterval,
      );
      if (!mounted) {
        return;
      }
      if (result.timedOut) {
        setState(() {
          _refreshStatusMessage = SourceRefreshService.syncContinuesMessage;
        });
      }
      await _loadInbox(showFullLoader: _inbox == null);
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (!mounted) {
        return;
      }
      setState(() {
        _refreshStatusMessage = e.message;
        if (_inbox == null) {
          _loadState = InboxLoadState.error;
          _errorMessage = e.message;
        }
      });
    } finally {
      if (mounted) {
        setState(() => _isSourceRefreshing = false);
      }
    }
  }

  Future<void> _submitIntake() async {
    if (_isIntakePending) {
      return;
    }
    final trimmed = _intakeController.text.trim();
    if (trimmed.isEmpty) {
      return;
    }
    setState(() {
      _isIntakePending = true;
      _intakeErrorMessage = null;
    });
    try {
      if (isExactHttpUrl(trimmed)) {
        final result = await widget.apiClient.intakeLink(trimmed);
        if (!mounted) {
          return;
        }
        _intakeController.clear();
        await _loadInbox(showFullLoader: false);
        if (!mounted) {
          return;
        }
        _showIntakeSnackBar(_intakeLinkSuccessMessage(result));
      } else {
        await widget.apiClient.captureNote(
          CaptureNoteRequest(text: _intakeController.text),
        );
        if (!mounted) {
          return;
        }
        _intakeController.clear();
        await _loadInbox(showFullLoader: false);
        if (!mounted) {
          return;
        }
        _showIntakeSnackBar('Заметка добавлена');
      }
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (!mounted) {
        return;
      }
      setState(() => _intakeErrorMessage = e.message);
    } finally {
      if (mounted) {
        setState(() => _isIntakePending = false);
      }
    }
  }

  String _intakeLinkSuccessMessage(IntakeLinkResult result) {
    final contentStatus = result.contentStatus;
    if (contentStatus == 'ready') {
      if (result.status == 'unchanged') {
        return 'Содержимое уже проиндексировано';
      }
      return 'Добавлено, содержимое проиндексировано';
    }
    switch (contentStatus) {
      case 'pending':
        return 'Добавлено, содержимое обрабатывается';
      case 'metadata_only':
        return 'Добавлено только как метаданные';
      case 'unsupported':
        return 'Добавлено, но содержимое этого формата не индексируется';
      case 'too_large':
        return 'Добавлено, но файл слишком большой для индексации';
      case 'failed':
        return 'Добавлено, но индексация содержимого не удалась';
      default:
        break;
    }
    switch (result.status) {
      case 'updated':
        return 'Обновлено';
      case 'unchanged':
        return 'Уже добавлено';
      default:
        return 'Добавлено';
    }
  }

  void _showIntakeSnackBar(String message) {
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _accept(NotificationOut notification) async {
    if (!mounted) {
      return;
    }
    setState(() => _mutatingNotificationId = notification.id);
    try {
      await widget.apiClient.acceptNotification(notification.id);
      if (!mounted) {
        return;
      }
      setState(() {
        final inbox = _inbox!;
        _inbox = InboxOut(
          unresolvedNotifications: inbox.unresolvedNotifications
              .where((row) => row.id != notification.id)
              .toList(),
          recentSourceObjects: inbox.recentSourceObjects,
          sourceSyncStatus: inbox.sourceSyncStatus,
          recentNextCursor: inbox.recentNextCursor,
          recentHasMore: inbox.recentHasMore,
          reviewMarker: inbox.reviewMarker,
          conversationGroups: inbox.conversationGroups,
        );
        _mutatingNotificationId = null;
      });
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (!mounted) {
        return;
      }
      setState(() {
        _mutatingNotificationId = null;
        _errorMessage = e.message;
      });
    }
  }

  Future<void> _ignore(NotificationOut notification) async {
    if (!mounted) {
      return;
    }
    setState(() => _mutatingNotificationId = notification.id);
    try {
      await widget.apiClient.ignoreNotification(notification.id);
      if (!mounted) {
        return;
      }
      setState(() {
        final inbox = _inbox!;
        _inbox = InboxOut(
          unresolvedNotifications: inbox.unresolvedNotifications
              .where((row) => row.id != notification.id)
              .toList(),
          recentSourceObjects: inbox.recentSourceObjects,
          sourceSyncStatus: inbox.sourceSyncStatus,
          recentNextCursor: inbox.recentNextCursor,
          recentHasMore: inbox.recentHasMore,
          reviewMarker: inbox.reviewMarker,
          conversationGroups: inbox.conversationGroups,
        );
        _mutatingNotificationId = null;
      });
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (!mounted) {
        return;
      }
      setState(() {
        _mutatingNotificationId = null;
        _errorMessage = e.message;
      });
    }
  }

  Future<void> _openInboxSource(InboxSourceObjectOut sourceObject) async {
    try {
      await _sourceNavigation.launchForObject(sourceObject.id);
    } on SourceLaunchException catch (e) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(e.message)));
    } on ApiException catch (e) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  Future<void> _openSourceObject(InboxSourceObjectOut sourceObject) async {
    final result = await openObjectDetail(
      context,
      objectId: sourceObject.id,
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
      _removeDeletedInboxObject(result.deletedObjectId);
    }
  }

  void _removeDeletedInboxObject(String deletedObjectId) {
    final inbox = _inbox;
    setState(() {
      if (inbox != null) {
        _inbox = InboxOut(
          unresolvedNotifications: inbox.unresolvedNotifications,
          recentSourceObjects: inbox.recentSourceObjects
              .where((row) => row.id != deletedObjectId)
              .toList(),
          sourceSyncStatus: inbox.sourceSyncStatus,
          recentNextCursor: inbox.recentNextCursor,
          recentHasMore: inbox.recentHasMore,
          reviewMarker: inbox.reviewMarker,
          conversationGroups: inbox.conversationGroups
              .where((group) => !group.coveredIds.contains(deletedObjectId))
              .toList(),
        );
      }
      _feedObjects = _feedObjects
          .where((row) => row.id != deletedObjectId)
          .toList();
      _conversationGroups = _conversationGroups
          .where((group) => !group.coveredIds.contains(deletedObjectId))
          .toList();
      _bookmarks.forget(deletedObjectId);
    });
  }

  Future<void> _deleteInboxSource(InboxSourceObjectOut sourceObject) async {
    final object = _secretaryObjectFromInboxSource(sourceObject);
    final direct = objectSupportsDeliberateSwipeDeleteWithoutDialog(object);
    final deleted = direct
        ? await deleteObjectFromSecretary(
            context,
            object: object,
            apiClient: widget.apiClient,
            authController: widget.authController,
          )
        : await confirmAndDeleteObject(
            context,
            object: object,
            apiClient: widget.apiClient,
            authController: widget.authController,
          );
    if (deleted && mounted) {
      _removeDeletedInboxObject(sourceObject.id);
    }
  }

  SecretaryObject _secretaryObjectFromInboxSource(
    InboxSourceObjectOut sourceObject,
  ) {
    return SecretaryObject(
      id: sourceObject.id,
      kind: sourceObject.kind,
      title: sourceObject.title,
      body: sourceObject.excerpt,
      provider: sourceObject.provider,
      externalId: null,
      canonicalUri: null,
      status: sourceObject.status,
      startAt: null,
      dueAt: null,
      occurredAt: sourceObject.primaryAt,
      metadata: const {},
      origin: sourceObject.origin,
      state: sourceObject.state,
      confidence: null,
      createdAt: sourceObject.primaryAt ?? '',
      updatedAt: sourceObject.primaryAt ?? '',
    );
  }

  Widget _sourceObjectCard(InboxSourceObjectOut sourceObject) {
    return _SourceObjectCard(
      sourceObject: sourceObject,
      labels: _labelsByObject[sourceObject.id] ?? const [],
      bookmarkColor: _bookmarks.colorFor(sourceObject.id),
      onBookmarkSelect: (color) => _bookmarks.setColor(sourceObject.id, color),
      onBookmarkClear: () => _bookmarks.clear(sourceObject.id),
      onTap: () => _openSourceObject(sourceObject),
      onOpenSource: providerHasIdentity(sourceObject.provider)
          ? () => _openInboxSource(sourceObject)
          : null,
      onAskSecretary: widget.onAskSecretary == null
          ? null
          : () {
              widget.onAskSecretary!(
                _secretaryObjectFromInboxSource(sourceObject),
              );
            },
      onShowInGraph: widget.onShowInGraph == null
          ? null
          : () => widget.onShowInGraph!(sourceObject.id),
      onDelete: inboxUsesSwipeToRemove()
          ? null
          : () => _deleteInboxSource(sourceObject),
    );
  }

  List<Widget> _inboxFeedChildren(
    BuildContext context,
    List<InboxSourceListEntry> groupedSources,
  ) {
    final reviewRail = _reviewRail;
    final swipe = _swipeToRemove;
    final desktopDrag = _desktopMarkerDrag;
    final widgets = <Widget>[];
    if (reviewRail) {
      widgets.add(
        SizedBox(
          height: kInboxReviewRailHitWidth,
          child: Align(
            alignment: Alignment.centerLeft,
            child: SizedBox(
              width: kInboxReviewRailHitWidth,
              height: kInboxReviewRailHitWidth,
              child: _InboxReviewRailSegment(
                segmentKey: const Key('inbox_review_rail_reset'),
                onTap: () => _onReviewRailTap(null),
              ),
            ),
          ),
        ),
      );
    }
    if (desktopDrag) {
      widgets.add(
        _InboxMarkerDropGap(
          afterObjectId: null,
          onAccept: () => _persistReviewMarker(null),
        ),
      );
      if (_reviewMarker == null) {
        widgets.add(const _InboxReviewMarkerBar(unplaced: true));
      }
    }
    for (final entry in groupedSources) {
      switch (entry) {
        case InboxDateSeparatorEntry():
          widgets.add(
            reviewRail
                ? _InboxTouchRailGutter(child: InboxDateSeparator(entry: entry))
                : InboxDateSeparator(entry: entry),
          );
        case InboxReviewMarkerEntry():
          widgets.add(const _InboxReviewMarkerBar(unplaced: false));
        case InboxConversationStackEntry(:final stack, :final children):
          final expanded = _expandedStackIds.contains(stack.stackId);
          final collapsed = _conversationStackCard(
            stack: stack,
            expanded: expanded,
            onToggle: () {
              setState(() {
                if (expanded) {
                  _expandedStackIds.remove(stack.stackId);
                } else {
                  _expandedStackIds.add(stack.stackId);
                }
              });
            },
          );
          if (reviewRail) {
            widgets.add(
              _InboxTouchRailGutter(
                key: Key('inbox_touch_stack_${stack.stackId}'),
                cardGap: kInboxSourceCardGap,
                rail: _InboxReviewRailSegment(
                  segmentKey: Key('inbox_review_rail_stack_${stack.stackId}'),
                  onTap: () => _onReviewRailTap(children.last.id),
                ),
                child: collapsed,
              ),
            );
          } else {
            widgets.add(collapsed);
          }
          if (expanded) {
            for (final sourceObject in children) {
              _addInboxSourceObjectRow(
                context,
                widgets,
                sourceObject,
                reviewRail: reviewRail,
                swipe: swipe,
                desktopDrag: desktopDrag,
                nestedInStack: true,
              );
            }
          }
        case InboxSourceObjectEntry(:final sourceObject):
          _addInboxSourceObjectRow(
            context,
            widgets,
            sourceObject,
            reviewRail: reviewRail,
            swipe: swipe,
            desktopDrag: desktopDrag,
          );
      }
    }
    return widgets;
  }

  void _addInboxSourceObjectRow(
    BuildContext context,
    List<Widget> widgets,
    InboxSourceObjectOut sourceObject, {
    required bool reviewRail,
    required bool swipe,
    required bool desktopDrag,
    bool nestedInStack = false,
  }) {
    final card = _sourceObjectCard(sourceObject);
    Widget body = card;
    if (nestedInStack) {
      body = _InboxNestedStackChild(
        key: Key('inbox_stack_nested_${sourceObject.id}'),
        child: body,
      );
    }
    if (swipe) {
      final object = _secretaryObjectFromInboxSource(sourceObject);
      final direct = objectSupportsDeliberateSwipeDeleteWithoutDialog(object);
      body = InboxSwipeToRemove(
        key: ValueKey(sourceObject.id),
        objectId: sourceObject.id,
        directDelete: direct,
        onConfirmRemove: () => direct
            ? deleteObjectFromSecretary(
                context,
                object: object,
                apiClient: widget.apiClient,
                authController: widget.authController,
              )
            : confirmAndDeleteObject(
                context,
                object: object,
                apiClient: widget.apiClient,
                authController: widget.authController,
              ),
        onRemoved: () {
          if (!mounted) {
            return;
          }
          _removeDeletedInboxObject(sourceObject.id);
        },
        child: body,
      );
    } else if (desktopDrag) {
      body = _InboxMarkerCardTarget(
        objectId: sourceObject.id,
        onHoverChanged: (hovering) {
          final next = hovering ? sourceObject.id : null;
          if (_markerHoverObjectId == next) {
            return;
          }
          if (!hovering && _markerHoverObjectId != sourceObject.id) {
            return;
          }
          setState(() => _markerHoverObjectId = next);
        },
        onAccept: () {
          setState(() => _markerHoverObjectId = null);
          _persistReviewMarker(sourceObject.id);
        },
        child: body,
      );
    }
    if (reviewRail) {
      widgets.add(
        _InboxTouchRailGutter(
          key: Key('inbox_touch_row_${sourceObject.id}'),
          cardGap: kInboxSourceCardGap,
          rail: _InboxReviewRailSegment(
            segmentKey: Key('inbox_review_rail_${sourceObject.id}'),
            onTap: () => _onReviewRailTap(sourceObject.id),
          ),
          child: body,
        ),
      );
    } else {
      widgets.add(body);
    }
    if (desktopDrag) {
      if (_markerHoverObjectId == sourceObject.id) {
        widgets.add(
          Container(
            key: Key('inbox_review_marker_card_preview_${sourceObject.id}'),
            height: 2,
            width: double.infinity,
            margin: const EdgeInsets.only(bottom: 2),
            color: kInboxReviewMarkerAccent,
          ),
        );
      }
      widgets.add(
        _InboxMarkerDropGap(
          afterObjectId: sourceObject.id,
          onAccept: () => _persistReviewMarker(sourceObject.id),
        ),
      );
    }
  }

  Widget _conversationStackCard({
    required InboxConversationStack stack,
    required bool expanded,
    required VoidCallback onToggle,
  }) {
    final wide = isWideLayout(context);
    final title = inboxStackHeaderTitle(stack);
    final fullTimestamp = formatUserDateTime(stack.startAt);
    return Card(
      key: Key('inbox_conversation_stack_${stack.stackId}'),
      margin: EdgeInsets.zero,
      child: InkWell(
        onTap: onToggle,
        child: Padding(
          padding: EdgeInsets.symmetric(
            horizontal: AppSpacing.md,
            vertical: wide ? AppSpacing.xs : AppSpacing.sm,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ObjectCompactHeaderRow(
                title: title,
                kind: inboxStackCardKind(stack.provider),
                provider: stack.provider,
                trailingText: wide
                    ? fullTimestamp
                    : formatUserTime(stack.startAt),
                trailingTooltip: wide ? null : fullTimestamp,
                titleMaxLines: wide ? 1 : 2,
              ),
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Row(
                  key: Key(
                    'inbox_conversation_stack_disclosure_${stack.stackId}',
                  ),
                  children: [
                    Expanded(
                      child: Text(
                        '${stack.messageCount} сообщений',
                        key: Key(
                          'inbox_conversation_stack_meta_${stack.stackId}',
                        ),
                      ),
                    ),
                    Icon(
                      expanded
                          ? Icons.keyboard_arrow_up
                          : Icons.keyboard_arrow_down,
                      key: Key(
                        expanded
                            ? 'inbox_conversation_stack_chevron_up_${stack.stackId}'
                            : 'inbox_conversation_stack_chevron_down_${stack.stackId}',
                      ),
                      size: 20,
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return _wrapDropTarget(
      Column(
        children: [
          _buildIntakeBar(),
          if (_intakeErrorMessage != null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
              child: Text(
                _intakeErrorMessage!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ),
          Expanded(
            child: Stack(
              children: [
                _buildBody(),
                if (_isDragHovering) const _DropOverlay(),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _onVoicePressed() async {
    if (_voice.voiceState == VoiceState.recording) {
      await _voice.stopAndTranscribe();
      return;
    }
    if (_isIntakePending ||
        (_voice.isVoiceBusy && _voice.voiceState != VoiceState.recording)) {
      return;
    }
    if (_voice.voiceState == VoiceState.error) {
      _voice.clearError();
    }
    await _voice.startRecording();
  }

  Widget _voiceButton() {
    return IconButton(
      key: const Key('inbox_voice_button'),
      visualDensity: VisualDensity.compact,
      tooltip: _voice.voiceState == VoiceState.recording
          ? 'Остановить запись'
          : 'Записать голос',
      padding: EdgeInsets.zero,
      constraints: const BoxConstraints(minWidth: 36, minHeight: 36),
      style: IconButton.styleFrom(
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
      ),
      onPressed: _isIntakePending && _voice.voiceState != VoiceState.recording
          ? null
          : _onVoicePressed,
      icon:
          _voice.voiceState == VoiceState.transcribing ||
              _voice.voiceState == VoiceState.starting
          ? const SizedBox(
              width: 18,
              height: 18,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          : Icon(
              _voice.voiceState == VoiceState.recording
                  ? Icons.stop_circle_outlined
                  : Icons.mic_none_outlined,
            ),
    );
  }

  List<Widget> _intakeSideButtons({required bool inputDisabled}) {
    return [
      Semantics(
        button: true,
        label: 'Добавить во входящие',
        child: Tooltip(
          message: 'Добавить во входящие',
          child: FilledButton(
            key: const Key('inbox_link_add_button'),
            onPressed: inputDisabled ? null : _submitIntake,
            style: FilledButton.styleFrom(
              minimumSize: const Size(40, 40),
              padding: const EdgeInsets.all(8),
              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
            ),
            child: _isIntakePending
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: Colors.white,
                    ),
                  )
                : const Icon(Icons.move_to_inbox_outlined),
          ),
        ),
      ),
      IconButton(
        key: const Key('inbox_add_file_button'),
        tooltip: 'Добавить файл',
        visualDensity: VisualDensity.compact,
        onPressed: inputDisabled
            ? null
            : () => _localIntakeActions.pickAndRegisterFile(context),
        icon: const Icon(Icons.insert_drive_file_outlined),
      ),
      IconButton(
        key: const Key('inbox_add_folder_button'),
        tooltip: 'Добавить папку',
        visualDensity: VisualDensity.compact,
        onPressed: inputDisabled
            ? null
            : () => _localIntakeActions.pickAndRegisterFolder(context),
        icon: const Icon(Icons.folder_outlined),
      ),
      IconButton(
        key: const Key('inbox_refresh_button'),
        tooltip: 'Обновить',
        visualDensity: VisualDensity.compact,
        onPressed: _isSourceRefreshing ? null : _refreshWithSources,
        icon: _isSourceRefreshing
            ? const SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : const Icon(Icons.refresh),
      ),
    ];
  }

  Widget _buildIntakeBar() {
    final voiceBusy = _voice.isVoiceBusy;
    final inputDisabled = _isIntakePending || voiceBusy;
    final wide = isWideLayout(context);
    final fieldEnabled =
        !_isIntakePending &&
        _voice.voiceState != VoiceState.starting &&
        _voice.voiceState != VoiceState.transcribing;
    return Padding(
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.lg,
        AppSpacing.sm,
        AppSpacing.lg,
        0,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_voice.voiceState == VoiceState.recording)
            Material(
              color: Theme.of(context).colorScheme.errorContainer,
              child: Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: AppSpacing.md,
                  vertical: AppSpacing.xs,
                ),
                child: Row(
                  children: [
                    const Icon(Icons.mic, size: 16),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(
                      child: Text(
                        'Запись… нажмите микрофон, чтобы остановить',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: TextField(
                  key: const Key('inbox_link_input'),
                  controller: _intakeController,
                  enabled: fieldEnabled,
                  readOnly: _voice.voiceState == VoiceState.recording,
                  minLines: 1,
                  maxLines: wide ? 2 : 3,
                  decoration: InputDecoration(
                    hintText: 'Введите заметку или вставьте ссылку',
                    isDense: true,
                    border: const OutlineInputBorder(),
                    contentPadding: const EdgeInsets.fromLTRB(12, 10, 4, 10),
                    suffixIcon: _voiceButton(),
                    suffixIconConstraints: const BoxConstraints(
                      minWidth: 40,
                      minHeight: 36,
                    ),
                  ),
                  onSubmitted: (_) => _submitIntake(),
                ),
              ),
              if (wide) ...[
                const SizedBox(width: AppSpacing.xs),
                ..._intakeSideButtons(inputDisabled: inputDisabled),
              ],
            ],
          ),
          if (!wide)
            Padding(
              padding: const EdgeInsets.only(top: AppSpacing.xs),
              child: Wrap(
                spacing: AppSpacing.xs,
                runSpacing: AppSpacing.xs,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: _intakeSideButtons(inputDisabled: inputDisabled),
              ),
            ),
          if (_voice.voiceState == VoiceState.error &&
              _voice.voiceErrorMessage != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                _voice.voiceErrorMessage!,
                style: TextStyle(
                  color: Theme.of(context).colorScheme.error,
                  fontSize: 12,
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _wrapDropTarget(Widget child) {
    if (kIsWeb || !Platform.isLinux) {
      return child;
    }
    return DropTarget(
      onDragEntered: (_) {
        if (!mounted) {
          return;
        }
        setState(() => _isDragHovering = true);
      },
      onDragExited: (_) {
        if (!mounted) {
          return;
        }
        setState(() => _isDragHovering = false);
      },
      onDragDone: (detail) {
        if (!mounted) {
          return;
        }
        setState(() => _isDragHovering = false);
        final paths = [for (final file in detail.files) file.path];
        handleDroppedPaths(paths);
      },
      child: child,
    );
  }

  Widget _buildBody() {
    switch (_loadState) {
      case InboxLoadState.loading:
        return const Center(child: CircularProgressIndicator());
      case InboxLoadState.error:
        return Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(_errorMessage ?? 'Не удалось загрузить входящие'),
              const SizedBox(height: 12),
              FilledButton(
                onPressed: _loadInbox,
                child: const Text('Повторить'),
              ),
            ],
          ),
        );
      case InboxLoadState.ready:
        final inbox = _inbox!;
        final hasNotifications = inbox.unresolvedNotifications.isNotEmpty;
        final hasSources = _feedObjects.isNotEmpty;
        final syncTransientRows = sourceSyncTransientRows(
          inbox.sourceSyncStatus,
        );
        final syncErrorRows = sourceSyncErrorRows(inbox.sourceSyncStatus);
        if (!hasNotifications &&
            !hasSources &&
            syncTransientRows.isEmpty &&
            syncErrorRows.isEmpty) {
          return const Center(child: Text('Входящие пусты'));
        }
        final groupedSources = groupInboxFeedEntries(
          objects: _feedObjects,
          overlay: _conversationGroups,
          marker: _reviewMarker,
          hasMore: _hasMore,
        );
        return ListView(
          key: const Key('inbox_feed_list'),
          controller: _feedScrollController,
          cacheExtent: 1200,
          padding: EdgeInsets.fromLTRB(
            _reviewRail ? 0 : AppSpacing.lg,
            0,
            AppSpacing.lg,
            0,
          ),
          children: [
            if (_refreshStatusMessage != null)
              _touchContentInset(
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Text(_refreshStatusMessage!),
                ),
              ),
            _touchContentInset(
              SourceSyncTransientList(rows: syncTransientRows),
            ),
            _touchContentInset(SourceSyncErrorList(errorRows: syncErrorRows)),
            _touchContentInset(const _SectionHeader(title: 'Требует внимания')),
            if (!hasNotifications)
              _touchContentInset(
                const Padding(
                  padding: EdgeInsets.only(bottom: 8),
                  child: Text('Нет уведомлений'),
                ),
              )
            else
              ...inbox.unresolvedNotifications.map(
                (notification) => _touchContentInset(
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: _NotificationCard(
                      notification: notification,
                      isMutating: _mutatingNotificationId == notification.id,
                      onAccept: () => _accept(notification),
                      onIgnore: () => _ignore(notification),
                      onOpenContext: () => openNotificationContext(
                        context,
                        notification: notification,
                        apiClient: widget.apiClient,
                        authController: widget.authController,
                        captureController: widget.captureController,
                        assistantController: widget.assistantController,
                        onAskSecretary: widget.onAskSecretary,
                        onAskSecretaryAboutNotification:
                            widget.onAskSecretaryAboutNotification,
                        onShowInGraph: widget.onShowInGraph,
                        bookmarkController: _bookmarks,
                      ),
                    ),
                  ),
                ),
              ),
            const SizedBox(height: 16),
            _touchContentInset(
              const _SectionHeader(title: 'Последние входящие'),
            ),
            if (_markerError != null)
              _touchContentInset(
                Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Text(
                    _markerError!,
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ),
              ),
            if (!hasSources)
              _touchContentInset(
                const Padding(
                  padding: EdgeInsets.only(bottom: 8),
                  child: Text('Нет недавних входящих объектов'),
                ),
              )
            else
              ..._inboxFeedChildren(context, groupedSources),
            if (_isLoadingMore)
              _touchContentInset(
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 12),
                  child: Center(
                    child: SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                  ),
                ),
              ),
            if (_loadMoreError != null)
              _touchContentInset(
                Padding(
                  padding: const EdgeInsets.only(bottom: 16),
                  child: Column(
                    children: [
                      Text(_loadMoreError!, textAlign: TextAlign.center),
                      TextButton(
                        key: const Key('inbox_load_more_retry'),
                        onPressed: _loadMore,
                        child: const Text('Повторить'),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        );
    }
  }
}

class _DropOverlay extends StatelessWidget {
  const _DropOverlay();

  @override
  Widget build(BuildContext context) {
    return Positioned.fill(
      child: IgnorePointer(
        child: Container(
          alignment: Alignment.center,
          color: Theme.of(context).colorScheme.primary.withValues(alpha: 0.08),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
            decoration: BoxDecoration(
              border: Border.all(
                color: Theme.of(context).colorScheme.primary,
                width: 2,
              ),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Text(
              'Перетащите файл или папку сюда',
              style: Theme.of(context).textTheme.titleMedium,
            ),
          ),
        ),
      ),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader({required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Text(title, style: Theme.of(context).textTheme.titleMedium),
    );
  }
}

class _NotificationCard extends StatelessWidget {
  const _NotificationCard({
    required this.notification,
    required this.isMutating,
    required this.onAccept,
    required this.onIgnore,
    required this.onOpenContext,
  });

  final NotificationOut notification;
  final bool isMutating;
  final VoidCallback onAccept;
  final VoidCallback onIgnore;
  final VoidCallback onOpenContext;

  @override
  Widget build(BuildContext context) {
    final isTelegramTransport = notification.isTelegramMtprotoTransportEvent;
    final urgent = notificationIsUrgent(notification);
    final isNew = notification.status == 'new';
    final colorScheme = Theme.of(context).colorScheme;

    return Card(
      key: Key('notification_card_${notification.id}'),
      color: urgent
          ? colorScheme.errorContainer.withValues(alpha: isNew ? 0.35 : 0.2)
          : isNew
          ? colorScheme.surfaceContainerHighest
          : null,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              isTelegramTransport
                  ? telegramTransportEventTitle(notification)
                  : notification.title,
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 4),
            if (isTelegramTransport) ...[
              if (telegramTransportEventBody(notification) != null)
                Text(telegramTransportEventBody(notification)!),
              if (telegramTransportEventTimestamp(notification) != null)
                Text(
                  'Время: ${formatUserDateTime(telegramTransportEventTimestamp(notification))}',
                ),
            ] else ...[
              Text(
                'Приоритет: ${notificationPriorityLabel(notification.priority)}',
              ),
              if (notification.proposalType != null)
                Text(
                  'Тип: ${notificationProposalTypeLabel(notification.proposalType!)}',
                ),
              Text('Источник: ${notificationEvidenceLabel(notification)}'),
              if (notification.proposalDescription != null)
                Text(notification.proposalDescription!),
              if (notification.proposedAction != null)
                Text(
                  'Действие: ${notificationProposedActionLabel(notification.proposedAction!)}',
                ),
            ],
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              children: [
                FilledButton(
                  key: Key('notification_accept_${notification.id}'),
                  onPressed: isMutating ? null : onAccept,
                  child: Text(isTelegramTransport ? 'Готово' : 'Принять'),
                ),
                OutlinedButton(
                  key: Key('notification_ignore_${notification.id}'),
                  onPressed: isMutating ? null : onIgnore,
                  child: const Text('Пропустить'),
                ),
                TextButton(
                  key: Key('notification_context_${notification.id}'),
                  onPressed: isMutating ? null : onOpenContext,
                  child: const Text('Открыть контекст'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _SourceObjectCard extends StatelessWidget {
  const _SourceObjectCard({
    required this.sourceObject,
    required this.labels,
    required this.onTap,
    this.bookmarkColor,
    this.onBookmarkSelect,
    this.onBookmarkClear,
    this.onOpenSource,
    this.onAskSecretary,
    this.onShowInGraph,
    this.onDelete,
  });

  final InboxSourceObjectOut sourceObject;
  final List<LabelItem> labels;
  final String? bookmarkColor;
  final ValueChanged<String>? onBookmarkSelect;
  final VoidCallback? onBookmarkClear;
  final VoidCallback onTap;
  final VoidCallback? onOpenSource;
  final VoidCallback? onAskSecretary;
  final VoidCallback? onShowInGraph;
  final VoidCallback? onDelete;

  @override
  Widget build(BuildContext context) {
    final when = formatUserDateTime(sourceObject.primaryAt);
    final feedDate = parseLocalInboxDate(sourceObject.feedStamp);
    final primaryDate = parseLocalInboxDate(sourceObject.primaryAt);
    final isEvent =
        sourceObject.kind == 'event' || sourceObject.kind == 'calendar_event';
    final trailingTooltip =
        isEvent &&
            feedDate != null &&
            primaryDate != null &&
            feedDate != primaryDate
        ? 'Во входящих: ${formatInboxDateSeparator(feedDate)}; событие: $when'
        : null;
    final wide = isWideLayout(context);
    final compactWhen = formatUserTime(sourceObject.primaryAt);
    final actionChildren = <Widget>[
      if (bookmarkColor == null &&
          onBookmarkSelect != null &&
          onBookmarkClear != null)
        ObjectBookmarkControl(
          color: bookmarkColor,
          onSelect: onBookmarkSelect!,
          onClear: onBookmarkClear!,
        ),
      if (onAskSecretary != null) AskSecretaryAction(onPressed: onAskSecretary),
      if (onShowInGraph != null) OpenInGraphAction(onPressed: onShowInGraph),
      if (onDelete != null)
        DeleteObjectAction(
          key: Key('inbox_card_delete_${sourceObject.id}'),
          onPressed: onDelete,
        ),
    ];
    return ObjectBookmarkRibbon(
      color: bookmarkColor,
      onSelect: onBookmarkSelect,
      onClear: onBookmarkClear,
      child: Card(
        margin: EdgeInsets.zero,
        child: InkWell(
          onTap: onTap,
          child: Padding(
            padding: EdgeInsets.symmetric(
              horizontal: AppSpacing.md,
              vertical: wide ? AppSpacing.xs : AppSpacing.sm,
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                ObjectCompactHeaderRow(
                  title: sourceObject.title,
                  kind: sourceObject.kind,
                  provider: sourceObject.provider,
                  trailingText: wide ? when : compactWhen,
                  trailingTooltip: wide
                      ? trailingTooltip
                      : (trailingTooltip ?? when),
                  titleMaxLines: wide ? 1 : 2,
                  onProviderTap: onOpenSource,
                  trailingReserve: bookmarkColor != null
                      ? kBookmarkRibbonReserve
                      : 0,
                ),
                if (sourceObject.excerpt != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Text(
                      sourceObject.excerpt!,
                      maxLines: wide ? 1 : 3,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ObjectMetaActionRow(
                  actions: actionChildren,
                  labels: labels,
                  wrapActions: true,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _InboxMarkerCardTarget extends StatelessWidget {
  const _InboxMarkerCardTarget({
    required this.objectId,
    required this.onAccept,
    required this.onHoverChanged,
    required this.child,
  });

  final String objectId;
  final VoidCallback onAccept;
  final ValueChanged<bool> onHoverChanged;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return DragTarget<String>(
      key: Key('inbox_review_marker_card_$objectId'),
      onWillAcceptWithDetails: (details) {
        final ok = details.data == 'inbox-review-marker';
        if (ok) {
          onHoverChanged(true);
        }
        return ok;
      },
      onLeave: (_) => onHoverChanged(false),
      onAcceptWithDetails: (_) => onAccept(),
      builder: (context, candidate, rejected) => child,
    );
  }
}

class _InboxNestedStackChild extends StatelessWidget {
  const _InboxNestedStackChild({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(left: kInboxStackChildIndent),
      child: DecoratedBox(
        decoration: BoxDecoration(
          border: Border(
            left: BorderSide(
              color: Theme.of(context).colorScheme.outlineVariant,
              width: 2,
            ),
          ),
        ),
        child: Padding(
          padding: const EdgeInsets.only(left: AppSpacing.xs),
          child: child,
        ),
      ),
    );
  }
}

class _InboxTouchRailGutter extends StatelessWidget {
  const _InboxTouchRailGutter({
    super.key,
    required this.child,
    this.rail,
    this.cardGap = 0,
  });

  final Widget child;
  final Widget? rail;
  final double cardGap;

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        Padding(
          padding: EdgeInsets.only(
            left: kInboxReviewRailHitWidth,
            bottom: cardGap,
          ),
          child: child,
        ),
        Positioned(
          left: 0,
          top: 0,
          bottom: 0,
          width: kInboxReviewRailHitWidth,
          child: rail ?? const IgnorePointer(child: _ReviewRailGuide()),
        ),
      ],
    );
  }
}

class _InboxReviewRailSegment extends StatefulWidget {
  const _InboxReviewRailSegment({
    required this.segmentKey,
    required this.onTap,
  });

  final Key segmentKey;
  final VoidCallback onTap;

  @override
  State<_InboxReviewRailSegment> createState() =>
      _InboxReviewRailSegmentState();
}

class _InboxReviewRailSegmentState extends State<_InboxReviewRailSegment> {
  var _hovered = false;

  @override
  Widget build(BuildContext context) {
    return MouseRegion(
      cursor: SystemMouseCursors.click,
      onEnter: (_) => setState(() => _hovered = true),
      onExit: (_) => setState(() => _hovered = false),
      child: GestureDetector(
        key: widget.segmentKey,
        behavior: HitTestBehavior.opaque,
        onTap: widget.onTap,
        child: _ReviewRailGuide(emphasized: _hovered),
      ),
    );
  }
}

class _ReviewRailGuide extends StatelessWidget {
  const _ReviewRailGuide({this.notch = false, this.emphasized = false});

  final bool notch;
  final bool emphasized;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final line = emphasized
        ? kInboxReviewMarkerAccent.withValues(alpha: 0.85)
        : scheme.outlineVariant;
    return CustomPaint(
      painter: _ReviewRailGuidePainter(
        color: line,
        notchColor: notch ? kInboxReviewMarkerAccent : scheme.outline,
        notch: notch,
      ),
      child: const SizedBox.expand(),
    );
  }
}

class _ReviewRailGuidePainter extends CustomPainter {
  _ReviewRailGuidePainter({
    required this.color,
    required this.notchColor,
    required this.notch,
  });

  final Color color;
  final Color notchColor;
  final bool notch;

  @override
  void paint(Canvas canvas, Size size) {
    final x = size.width / 2;
    final line = Paint()
      ..color = color
      ..strokeWidth = 2
      ..strokeCap = StrokeCap.round;
    canvas.drawLine(Offset(x, 2), Offset(x, size.height - 2), line);
    if (!notch) {
      return;
    }
    canvas.drawCircle(
      Offset(x, size.height / 2),
      4,
      Paint()..color = notchColor,
    );
  }

  @override
  bool shouldRepaint(covariant _ReviewRailGuidePainter oldDelegate) {
    return oldDelegate.color != color ||
        oldDelegate.notchColor != notchColor ||
        oldDelegate.notch != notch;
  }
}

class _InboxReviewMarkerBar extends StatelessWidget {
  const _InboxReviewMarkerBar({required this.unplaced});

  final bool unplaced;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final reviewRail = inboxUsesReviewRail();
    final desktopDrag = !inboxUsesSwipeToRemove();
    final accent = unplaced ? scheme.outline : kInboxReviewMarkerAccent;
    final lines = Expanded(
      child: Row(
        children: [
          Expanded(
            child: Divider(
              key: unplaced ? null : const Key('inbox_review_marker_line'),
              height: 2,
              thickness: unplaced ? 1 : 2,
              color: accent,
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8),
            child: Text(
              unplaced ? 'Маркер просмотра' : 'Просмотрено досюда',
              style: Theme.of(context).textTheme.labelSmall?.copyWith(
                color: accent,
                fontWeight: unplaced ? FontWeight.w500 : FontWeight.w600,
              ),
            ),
          ),
          Expanded(
            child: Divider(
              height: 2,
              thickness: unplaced ? 1 : 2,
              color: accent,
            ),
          ),
        ],
      ),
    );
    final handle = desktopDrag ? _markerHandle(context, accent) : null;
    final draggable = handle == null
        ? null
        : Draggable<String>(
            data: 'inbox-review-marker',
            axis: Axis.vertical,
            feedback: _dragFeedback(context, accent),
            childWhenDragging: Opacity(opacity: 0.3, child: handle),
            child: handle,
          );
    return SizedBox(
      key: Key(
        unplaced ? 'inbox_review_marker_unplaced' : 'inbox_review_marker',
      ),
      height: 28,
      child: Row(
        children: [
          if (reviewRail)
            SizedBox(
              key: unplaced ? null : const Key('inbox_review_rail_notch'),
              width: kInboxReviewRailHitWidth,
              height: 28,
              child: IgnorePointer(child: _ReviewRailGuide(notch: !unplaced)),
            ),
          if (draggable != null) ...[
            MouseRegion(cursor: SystemMouseCursors.grab, child: draggable),
            const SizedBox(width: 6),
          ],
          lines,
        ],
      ),
    );
  }

  Widget _markerHandle(BuildContext context, Color color) {
    return SizedBox(
      key: const Key('inbox_review_marker_handle'),
      width: 32,
      height: 28,
      child: Center(
        child: CustomPaint(
          size: const Size(12, 16),
          painter: _ReviewMarkerGrabPainter(color: color),
        ),
      ),
    );
  }

  Widget _dragFeedback(BuildContext context, Color color) {
    return Material(
      color: Colors.transparent,
      child: SizedBox(
        width: 32,
        height: 28,
        child: _markerHandle(context, color),
      ),
    );
  }
}

class _ReviewMarkerGrabPainter extends CustomPainter {
  _ReviewMarkerGrabPainter({required this.color});

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final fill = Paint()
      ..color = color.withValues(alpha: 0.18)
      ..style = PaintingStyle.fill;
    final stroke = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1;
    final rect = RRect.fromRectAndRadius(
      Offset.zero & size,
      const Radius.circular(3),
    );
    canvas.drawRRect(rect, fill);
    canvas.drawRRect(rect, stroke);
    final grip = Paint()
      ..color = color
      ..strokeWidth = 1
      ..strokeCap = StrokeCap.round;
    final x1 = size.width * 0.38;
    final x2 = size.width * 0.62;
    canvas.drawLine(Offset(x1, 4), Offset(x1, size.height - 4), grip);
    canvas.drawLine(Offset(x2, 4), Offset(x2, size.height - 4), grip);
  }

  @override
  bool shouldRepaint(covariant _ReviewMarkerGrabPainter oldDelegate) {
    return oldDelegate.color != color;
  }
}

class _InboxMarkerDropGap extends StatelessWidget {
  const _InboxMarkerDropGap({
    required this.afterObjectId,
    required this.onAccept,
  });

  final String? afterObjectId;
  final VoidCallback onAccept;

  static const double _hitHeight = 10;
  static const double _activeHeight = 14;

  @override
  Widget build(BuildContext context) {
    return DragTarget<String>(
      key: Key('inbox_review_marker_gap_${afterObjectId ?? 'top'}'),
      onWillAcceptWithDetails: (details) =>
          details.data == 'inbox-review-marker',
      onAcceptWithDetails: (_) => onAccept(),
      builder: (context, candidate, rejected) {
        final hovering = candidate.isNotEmpty;
        return AnimatedContainer(
          duration: const Duration(milliseconds: 120),
          height: hovering ? _activeHeight : _hitHeight,
          width: double.infinity,
          alignment: Alignment.center,
          color: hovering
              ? Theme.of(context).colorScheme.tertiary.withValues(alpha: 0.25)
              : Colors.transparent,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 120),
            height: hovering ? 4 : 2,
            width: double.infinity,
            color: hovering
                ? Theme.of(context).colorScheme.tertiary
                : Colors.transparent,
          ),
        );
      },
    );
  }
}
