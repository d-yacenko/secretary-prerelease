import 'dart:async';

import 'package:flutter/material.dart';

import '../api/api_error.dart';
import '../api/api_models.dart';
import '../api/secretary_api_client.dart';
import '../assistant/assistant_controller.dart';
import '../auth/auth_controller.dart';
import '../capture/capture_controller.dart';
import '../navigation/secretary_navigation.dart';
import '../ui/date_format.dart';
import '../ui/object_bookmark_controller.dart';
import '../ui/passive_snapshot_refresh.dart';
import 'availability_sheet.dart';
import 'week_kalender_events.dart';
import 'week_time_grid.dart';

enum WeekLoadState { loading, ready, error }

class WeekScreen extends StatefulWidget {
  const WeekScreen({
    super.key,
    required this.apiClient,
    required this.authController,
    required this.captureController,
    this.assistantController,
    this.onAskSecretary,
    this.onShowInGraph,
    this.bookmarkController,
    this.now,
    this.passiveRefreshInterval = kPassiveSnapshotRefreshInterval,
    this.isActive = true,
  });

  final SecretaryApiClient apiClient;
  final AuthController authController;
  final CaptureController captureController;
  final AssistantController? assistantController;
  final AskSecretaryHandler? onAskSecretary;
  final ShowInGraphHandler? onShowInGraph;
  final ObjectBookmarkController? bookmarkController;
  final DateTime Function()? now;
  final Duration passiveRefreshInterval;
  final bool isActive;

  @override
  State<WeekScreen> createState() => _WeekScreenState();
}

class _WeekScreenState extends State<WeekScreen> {
  WeekLoadState _loadState = WeekLoadState.loading;
  WeekOut? _week;
  String? _activeWeekStart;
  String? _errorMessage;
  late final ObjectBookmarkController _bookmarks;
  var _ownsBookmarks = false;
  late final PassiveSnapshotRefresh _passiveRefresh;
  var _requestGeneration = 0;

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
    _passiveRefresh = PassiveSnapshotRefresh(
      interval: widget.passiveRefreshInterval,
      isPaused: () => !widget.isActive,
      onRefresh: () => _loadWeek(
        weekStart: _activeWeekStart,
        showFullLoader: false,
        passive: true,
      ),
    );
    _passiveRefresh.attach();
    _loadWeek();
  }

  @override
  void didUpdateWidget(covariant WeekScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.isActive && !oldWidget.isActive) {
      unawaited(
        _loadWeek(
          weekStart: _activeWeekStart,
          showFullLoader: false,
          passive: true,
        ),
      );
    }
  }

  @override
  void dispose() {
    _passiveRefresh.dispose();
    if (_ownsBookmarks) {
      _bookmarks.dispose();
    }
    super.dispose();
  }

  Future<void> _loadWeek({
    String? weekStart,
    bool showFullLoader = true,
    bool passive = false,
  }) async {
    if (!mounted) {
      return;
    }
    if (passive && !widget.isActive) {
      return;
    }
    final generation = ++_requestGeneration;
    _activeWeekStart = weekStart;
    if (showFullLoader && !passive) {
      setState(() {
        _loadState = WeekLoadState.loading;
        _errorMessage = null;
      });
    }
    try {
      final snapshot = await widget.apiClient.getWeek(weekStart: weekStart);
      if (!mounted || generation != _requestGeneration) {
        return;
      }
      if (_loadState == WeekLoadState.ready &&
          _week != null &&
          weekPresentationSignature(snapshot) ==
              weekPresentationSignature(_week!)) {
        return;
      }
      setState(() {
        _week = snapshot;
        _loadState = WeekLoadState.ready;
      });
      final ids = [
        for (final day in snapshot.days) ...[
          for (final event in day.events) event.object.id,
          for (final work in day.scheduledWork) work.id,
          for (final hint in day.temporalHints) hint.id,
        ],
      ];
      await _bookmarks.reconcileVisible(ids);
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (!mounted || generation != _requestGeneration) {
        return;
      }
      if (passive && _week != null) {
        return;
      }
      setState(() {
        _loadState = WeekLoadState.error;
        _errorMessage = e.message;
      });
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
    if (!mounted || result == null || _week == null) {
      return;
    }
    setState(() {
      _week = WeekOut(
        weekStart: _week!.weekStart,
        weekEnd: _week!.weekEnd,
        timezone: _week!.timezone,
        windowStart: _week!.windowStart,
        windowEnd: _week!.windowEnd,
        todayDate: _week!.todayDate,
        isCurrentWeek: _week!.isCurrentWeek,
        days: [
          for (final day in _week!.days)
            WeekDay(
              date: day.date,
              isToday: day.isToday,
              events: day.events
                  .where((event) => event.object.id != result.deletedObjectId)
                  .toList(),
              scheduledWork: day.scheduledWork
                  .where((work) => work.id != result.deletedObjectId)
                  .toList(),
              temporalHints: day.temporalHints
                  .where((hint) => hint.id != result.deletedObjectId)
                  .toList(),
            ),
        ],
      );
    });
    _bookmarks.forget(result.deletedObjectId);
  }

  Future<void> _openAvailability() async {
    final week = _week;
    if (week == null || !mounted) {
      return;
    }
    await showAvailabilitySheet(
      context: context,
      apiClient: widget.apiClient,
      authController: widget.authController,
      week: week,
    );
  }

  void _goRelative(int days) {
    final current = _week?.weekStart;
    if (current == null) {
      return;
    }
    _loadWeek(weekStart: shiftCalendarDate(current, days));
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        _WeekNavigationBar(
          week: _week,
          enabled: _loadState != WeekLoadState.loading,
          onPrevious: () => _goRelative(-7),
          onNext: () => _goRelative(7),
          onCurrent: () => _loadWeek(),
          onAvailability: _openAvailability,
        ),
        Expanded(child: _buildBody()),
      ],
    );
  }

  Widget _buildBody() {
    switch (_loadState) {
      case WeekLoadState.loading:
        return const Center(child: CircularProgressIndicator());
      case WeekLoadState.error:
        return Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(_errorMessage ?? 'Не удалось загрузить неделю'),
              const SizedBox(height: 12),
              FilledButton(
                onPressed: () => _loadWeek(weekStart: _activeWeekStart),
                child: const Text('Повторить'),
              ),
            ],
          ),
        );
      case WeekLoadState.ready:
        return WeekTimeGrid(
          week: _week!,
          onOpen: _openObjectDetail,
          onRequestWeekStart: (weekStart) =>
              _loadWeek(weekStart: weekStart, showFullLoader: false),
          now: widget.now,
          bookmarks: _bookmarks,
        );
    }
  }
}

class _WeekNavigationBar extends StatelessWidget {
  const _WeekNavigationBar({
    required this.week,
    required this.enabled,
    required this.onPrevious,
    required this.onNext,
    required this.onCurrent,
    required this.onAvailability,
  });

  final WeekOut? week;
  final bool enabled;
  final VoidCallback onPrevious;
  final VoidCallback onNext;
  final VoidCallback onCurrent;
  final VoidCallback onAvailability;

  @override
  Widget build(BuildContext context) {
    final range = week == null ? 'Неделя' : formatWeekRange(week!.weekStart);
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 4, 4, 0),
      child: Row(
        children: [
          IconButton(
            key: const Key('week_nav_prev'),
            tooltip: 'Предыдущая неделя',
            onPressed: enabled ? onPrevious : null,
            icon: const Icon(Icons.chevron_left),
          ),
          Expanded(
            child: Text(
              key: const Key('week_range'),
              range,
              textAlign: TextAlign.center,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.titleSmall,
            ),
          ),
          if (week != null && !week!.isCurrentWeek)
            TextButton(
              key: const Key('week_nav_current'),
              onPressed: enabled ? onCurrent : null,
              child: const Text('Эта неделя'),
            ),
          IconButton(
            key: const Key('week_availability_action'),
            tooltip: 'Свободное время',
            onPressed: enabled && week != null ? onAvailability : null,
            icon: const Icon(Icons.event_available_outlined),
          ),
          IconButton(
            key: const Key('week_nav_next'),
            tooltip: 'Следующая неделя',
            onPressed: enabled ? onNext : null,
            icon: const Icon(Icons.chevron_right),
          ),
        ],
      ),
    );
  }
}
