import 'dart:async';

import 'package:flutter/widgets.dart';

/// Default cadence for passive Inbox/Today snapshot refresh (GET only).
const Duration kPassiveSnapshotRefreshInterval = Duration(seconds: 30);

typedef PassiveSnapshotRefreshCallback = Future<void> Function();

/// Periodic GET snapshot refresh with lifecycle-aware pause/resume.
class PassiveSnapshotRefresh with WidgetsBindingObserver {
  PassiveSnapshotRefresh({
    required this.onRefresh,
    this.interval = kPassiveSnapshotRefreshInterval,
    required this.isPaused,
  });

  final PassiveSnapshotRefreshCallback onRefresh;
  final Duration interval;
  final bool Function() isPaused;

  Timer? _timer;
  bool _disposed = false;
  bool _lifecyclePaused = false;
  bool _refreshInProgress = false;

  void attach() {
    WidgetsBinding.instance.addObserver(this);
    _scheduleNextTick();
  }

  void dispose() {
    _disposed = true;
    WidgetsBinding.instance.removeObserver(this);
    _timer?.cancel();
    _timer = null;
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    switch (state) {
      case AppLifecycleState.resumed:
        _lifecyclePaused = false;
        unawaited(_runRefresh());
        _scheduleNextTick();
        break;
      case AppLifecycleState.inactive:
        // Non-web desktop: visible app without input focus must keep polling.
        break;
      case AppLifecycleState.hidden:
      case AppLifecycleState.paused:
      case AppLifecycleState.detached:
        _lifecyclePaused = true;
        _timer?.cancel();
        _timer = null;
        break;
    }
  }

  void _scheduleNextTick() {
    _timer?.cancel();
    if (_disposed || _lifecyclePaused) {
      return;
    }
    _timer = Timer(interval, () {
      unawaited(_runRefresh(onComplete: _scheduleNextTick));
    });
  }

  Future<void> _runRefresh({void Function()? onComplete}) async {
    if (_disposed || _lifecyclePaused || isPaused()) {
      onComplete?.call();
      return;
    }
    if (_refreshInProgress) {
      onComplete?.call();
      return;
    }
    _refreshInProgress = true;
    try {
      await onRefresh();
    } finally {
      _refreshInProgress = false;
      onComplete?.call();
    }
  }
}
