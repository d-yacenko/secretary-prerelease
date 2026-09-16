import 'dart:async';

import 'package:flutter/material.dart';

import '../api/api_error.dart';
import '../api/api_models.dart';
import '../api/secretary_api_client.dart';
import '../assistant/assistant_controller.dart';
import '../auth/auth_controller.dart';
import '../capture/capture_controller.dart';
import '../inbox/notification_labels.dart';
import '../navigation/secretary_navigation.dart';
import '../sources/source_refresh_service.dart';
import '../ui/assigned_labels_loader.dart';
import '../ui/date_format.dart';
import '../ui/object_bookmark.dart';
import '../ui/object_bookmark_controller.dart';
import '../ui/object_label_strip.dart';
import '../ui/object_presentation.dart';
import '../ui/passive_snapshot_refresh.dart';
import '../ui/today_event_emphasis.dart';

enum TodayLoadState { loading, ready, error }

class TodayScreen extends StatefulWidget {
  const TodayScreen({
    super.key,
    required this.apiClient,
    required this.authController,
    required this.captureController,
    this.assistantController,
    this.onAskSecretary,
    this.onShowInGraph,
    this.passiveRefreshInterval = kPassiveSnapshotRefreshInterval,
    this.now,
    this.clockTick = const Duration(minutes: 1),
    this.bookmarkController,
  });

  final SecretaryApiClient apiClient;
  final AuthController authController;
  final CaptureController captureController;
  final AssistantController? assistantController;
  final AskSecretaryHandler? onAskSecretary;
  final ShowInGraphHandler? onShowInGraph;
  final Duration passiveRefreshInterval;
  final DateTime Function()? now;
  final Duration clockTick;
  final ObjectBookmarkController? bookmarkController;

  @override
  State<TodayScreen> createState() => _TodayScreenState();
}

class _TodayScreenState extends State<TodayScreen> {
  TodayLoadState _loadState = TodayLoadState.loading;
  TodayOut? _today;
  Map<String, List<LabelItem>> _labelsByObject = {};
  String? _errorMessage;
  String? _refreshStatusMessage;
  bool _isSourceRefreshing = false;
  late DateTime _now;
  Timer? _clock;

  late final SourceRefreshService _sourceRefreshService =
      SourceRefreshService(apiClient: widget.apiClient);
  late final PassiveSnapshotRefresh _passiveRefresh;
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
    _now = (widget.now ?? DateTime.now)().toLocal();
    _clock = Timer.periodic(widget.clockTick, (_) {
      if (!mounted) {
        return;
      }
      setState(() {
        _now = (widget.now ?? DateTime.now)().toLocal();
      });
    });
    _passiveRefresh = PassiveSnapshotRefresh(
      interval: widget.passiveRefreshInterval,
      isPaused: () => _isSourceRefreshing,
      onRefresh: () => _loadToday(showFullLoader: false, passive: true),
    );
    _passiveRefresh.attach();
    _loadToday();
  }

  @override
  void dispose() {
    _bookmarks.removeListener(_onBookmarksChanged);
    if (_ownsBookmarks) {
      _bookmarks.dispose();
    }
    _clock?.cancel();
    _passiveRefresh.dispose();
    super.dispose();
  }

  void _onBookmarksChanged() {
    if (mounted) {
      setState(() {});
    }
  }

  Future<void> _loadToday(
      {bool showFullLoader = true, bool passive = false}) async {
    if (!mounted) {
      return;
    }
    if (passive && _isSourceRefreshing) {
      return;
    }
    if (showFullLoader && !passive) {
      setState(() {
        _loadState = TodayLoadState.loading;
        _errorMessage = null;
      });
    }

    try {
      final snapshot = await widget.apiClient.getToday();
      if (!mounted) {
        return;
      }
      setState(() {
        _today = snapshot;
        _loadState = TodayLoadState.ready;
      });
      final labels = await loadAssignedLabelsByObjects(
        apiClient: widget.apiClient,
        onAuthFailure: widget.authController.handleAuthenticationFailure,
        objectIds: [
          ...snapshot.tasks.map((item) => item.id),
          ...snapshot.calendarEvents.map((item) => item.id),
        ],
      );
      if (!mounted) {
        return;
      }
      setState(() => _labelsByObject = labels);
      await _bookmarks.reconcileVisible([
        ...snapshot.tasks.map((item) => item.id),
        ...snapshot.calendarEvents.map((item) => item.id),
      ]);
      if (!mounted) {
        return;
      }
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (!mounted) {
        return;
      }
      if (passive && _today != null) {
        return;
      }
      setState(() {
        _loadState = TodayLoadState.error;
        _errorMessage = e.message;
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
      if (_today == null) {
        _loadState = TodayLoadState.loading;
      }
    });
    try {
      final result = await _sourceRefreshService.refreshSources();
      if (!mounted) {
        return;
      }
      await _loadToday(showFullLoader: _today == null);
      if (!mounted) {
        return;
      }
      if (result.timedOut) {
        setState(() {
          _refreshStatusMessage = 'Синхронизация источников продолжается';
        });
      }
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (!mounted) {
        return;
      }
      setState(() {
        _refreshStatusMessage = e.message;
        if (_today == null) {
          _loadState = TodayLoadState.error;
          _errorMessage = e.message;
        }
      });
    } finally {
      if (mounted) {
        setState(() => _isSourceRefreshing = false);
      }
    }
  }

  Future<void> _openObjectDetail(String objectId) async {
    final result = await openObjectDetail(
      context,
      objectId: objectId,
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
      final today = _today;
      if (today == null) {
        return;
      }
      setState(() {
        _today = TodayOut(
          date: today.date,
          timezone: today.timezone,
          dayStart: today.dayStart,
          tasks: today.tasks
              .where((task) => task.id != result.deletedObjectId)
              .toList(),
          calendarEvents: today.calendarEvents
              .where((event) => event.id != result.deletedObjectId)
              .toList(),
          notifications: today.notifications,
        );
      });
      _bookmarks.forget(result.deletedObjectId);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Align(
          alignment: Alignment.centerRight,
          child: IconButton(
            tooltip: 'Обновить',
            onPressed: _isSourceRefreshing ? null : _refreshWithSources,
            icon: _isSourceRefreshing
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.refresh),
          ),
        ),
        Expanded(child: _buildBody()),
      ],
    );
  }

  Widget _buildBody() {
    switch (_loadState) {
      case TodayLoadState.loading:
        return const Center(child: CircularProgressIndicator());
      case TodayLoadState.error:
        return Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(_errorMessage ?? 'Не удалось загрузить «Сегодня»'),
              const SizedBox(height: 12),
              FilledButton(
                onPressed: _loadToday,
                child: const Text('Повторить'),
              ),
            ],
          ),
        );
      case TodayLoadState.ready:
        final today = _today!;
        return ListView(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          children: [
            if (_refreshStatusMessage != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text(_refreshStatusMessage!),
              ),
            Text('${today.date} (${today.timezone})'),
            const SizedBox(height: 16),
            _SectionHeader(title: 'Задачи'),
            if (today.tasks.isEmpty)
              const _EmptySection(message: 'Нет задач на сегодня')
            else
              ...today.tasks.map((task) => _TaskRow(
                    task: task,
                    today: today,
                    labels: _labelsByObject[task.id] ?? const [],
                    bookmarkColor: _bookmarks.colorFor(task.id),
                    onBookmarkSelect: (color) =>
                        _bookmarks.setColor(task.id, color),
                    onBookmarkClear: () => _bookmarks.clear(task.id),
                    onTap: () => _openObjectDetail(task.id),
                  )),
            const SizedBox(height: 16),
            _SectionHeader(title: 'Календарь'),
            if (today.calendarEvents.isEmpty)
              const _EmptySection(message: 'Нет событий в календаре')
            else
              ...today.calendarEvents.indexed.expand((indexed) {
                final (i, event) = indexed;
                return [
                  _EventRow(
                    event: event,
                    emphasis: todayEventEmphasis(event, now: _now),
                    labels: _labelsByObject[event.id] ?? const [],
                    bookmarkColor: _bookmarks.colorFor(event.id),
                    onBookmarkSelect: (color) =>
                        _bookmarks.setColor(event.id, color),
                    onBookmarkClear: () => _bookmarks.clear(event.id),
                    onTap: () => _openObjectDetail(event.id),
                  ),
                  if (i < today.calendarEvents.length - 1)
                    Divider(
                      key: Key('today_event_separator_${event.id}'),
                      height: 1,
                      thickness: 1,
                      color: Theme.of(context).colorScheme.outlineVariant,
                    ),
                ];
              }),
            const SizedBox(height: 16),
            _SectionHeader(title: 'Важные уведомления'),
            if (today.notifications.isEmpty)
              const _EmptySection(message: 'Нет важных уведомлений')
            else
              ...today.notifications.map((notification) => _NotificationRow(
                    notification: notification,
                    onTap: () => openNotificationContext(
                      context,
                      notification: notification,
                      apiClient: widget.apiClient,
                      authController: widget.authController,
                      captureController: widget.captureController,
                      assistantController: widget.assistantController,
                      onAskSecretary: widget.onAskSecretary,
                      onShowInGraph: widget.onShowInGraph,
                      bookmarkController: _bookmarks,
                    ),
                  )),
          ],
        );
    }
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

class _EmptySection extends StatelessWidget {
  const _EmptySection({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Text(message),
    );
  }
}

Widget? _todayBookmarkSubtitle({
  required List<LabelItem> labels,
  required String? bookmarkColor,
  required ValueChanged<String> onSelect,
  required VoidCallback onClear,
}) {
  final actions = <Widget>[
    if (bookmarkColor == null)
      ObjectBookmarkControl(
        color: bookmarkColor,
        onSelect: onSelect,
        onClear: onClear,
      ),
  ];
  if (actions.isEmpty && labels.isEmpty) {
    return null;
  }
  return ObjectMetaActionRow(
    actions: actions,
    labels: labels,
  );
}

class _TaskRow extends StatelessWidget {
  const _TaskRow({
    required this.task,
    required this.today,
    required this.labels,
    this.bookmarkColor,
    required this.onBookmarkSelect,
    required this.onBookmarkClear,
    required this.onTap,
  });

  final SecretaryObject task;
  final TodayOut today;
  final List<LabelItem> labels;
  final String? bookmarkColor;
  final ValueChanged<String> onBookmarkSelect;
  final VoidCallback onBookmarkClear;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final overdue = today.isTaskOverdue(task);
    final dueAt = formatUserDateTime(task.dueAt);
    final when = dueAt.isEmpty ? 'Нет срока' : dueAt;
    final trailing = overdue ? 'Просрочено • $when' : when;
    return ObjectBookmarkRibbon(
      color: bookmarkColor,
      onSelect: onBookmarkSelect,
      onClear: onBookmarkClear,
      child: ListTile(
      title: ObjectCompactHeaderRow(
        title: task.title,
        kind: task.kind,
        provider: task.provider,
        trailingText: trailing,
        trailingReserve: bookmarkColor != null ? kBookmarkRibbonReserve : 0,
        trailingBadges: task.state == 'proposed'
            ? [
                Padding(
                  padding: const EdgeInsets.only(left: 6),
                  child: Text(
                    'Предложено',
                    style: Theme.of(context).textTheme.labelMedium,
                  ),
                ),
              ]
            : const [],
      ),
      subtitle: _todayBookmarkSubtitle(
        labels: labels,
        bookmarkColor: bookmarkColor,
        onSelect: onBookmarkSelect,
        onClear: onBookmarkClear,
      ),
      onTap: onTap,
    ),
    );
  }
}

class _EventRow extends StatelessWidget {
  const _EventRow({
    required this.event,
    required this.emphasis,
    required this.labels,
    this.bookmarkColor,
    required this.onBookmarkSelect,
    required this.onBookmarkClear,
    required this.onTap,
  });

  final SecretaryObject event;
  final TodayEventEmphasis emphasis;
  final List<LabelItem> labels;
  final String? bookmarkColor;
  final ValueChanged<String> onBookmarkSelect;
  final VoidCallback onBookmarkClear;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final time = formatUserTime(event.startAt);
    final scheme = Theme.of(context).colorScheme;
    Color? background;
    Color? stripe;
    switch (emphasis) {
      case TodayEventEmphasis.current:
        background = scheme.errorContainer.withValues(alpha: 0.35);
        stripe = scheme.error;
      case TodayEventEmphasis.soon:
        background = scheme.tertiaryContainer.withValues(alpha: 0.45);
        stripe = scheme.tertiary;
      case TodayEventEmphasis.none:
        break;
    }
    return DecoratedBox(
      key: Key('today_event_${emphasis.name}_${event.id}'),
      decoration: BoxDecoration(
        color: background,
        border: stripe == null
            ? null
            : Border(left: BorderSide(color: stripe, width: 3)),
      ),
      child: ObjectBookmarkRibbon(
        color: bookmarkColor,
        onSelect: onBookmarkSelect,
        onClear: onBookmarkClear,
        child: ListTile(
        title: ObjectCompactHeaderRow(
          title: event.title,
          kind: event.kind,
          provider: event.provider,
          trailingText: time.isEmpty ? 'Нет времени' : time,
          trailingReserve: bookmarkColor != null ? kBookmarkRibbonReserve : 0,
        ),
        subtitle: _todayBookmarkSubtitle(
          labels: labels,
          bookmarkColor: bookmarkColor,
          onSelect: onBookmarkSelect,
          onClear: onBookmarkClear,
        ),
        onTap: onTap,
      ),
      ),
    );
  }
}

class _NotificationRow extends StatelessWidget {
  const _NotificationRow({required this.notification, required this.onTap});

  final NotificationOut notification;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      title: Text(notification.title),
      subtitle: Text(
        '${notificationPriorityLabel(notification.priority)} • ${notificationEvidenceLabel(notification)}',
      ),
      onTap: onTap,
    );
  }
}
