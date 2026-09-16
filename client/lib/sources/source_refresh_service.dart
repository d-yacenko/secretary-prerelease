import 'dart:async';

import '../api/api_models.dart';
import '../api/secretary_api_client.dart';

/// Result of a bounded source-sync refresh cycle.
class SourceRefreshResult {
  SourceRefreshResult({
    required this.timedOut,
    required this.statuses,
  });

  final bool timedOut;
  final List<SourceSyncStatusOut> statuses;

  bool get hasErrors => statuses.any((row) => row.status == 'error');
}

/// Triggers `POST /sources/sync` and polls `/sources/status` until settled or timeout.
class SourceRefreshService {
  SourceRefreshService({required SecretaryApiClient apiClient})
      : _apiClient = apiClient;

  final SecretaryApiClient _apiClient;

  static const Duration defaultTimeout = Duration(seconds: 12);
  static const Duration pollInterval = Duration(milliseconds: 500);

  /// Local Inbox message shown when manual refresh times out before sources settle.
  static const String syncContinuesMessage =
      'Синхронизация источников продолжается';

  /// Whether a single source row has finished its active sync cycle.
  static bool isStatusSettled(SourceSyncStatusOut row) {
    if (row.status == 'syncing') {
      return false;
    }
    if (row.status == 'error' || row.status == 'scheduled') {
      return true;
    }
    if (row.status == 'pending') {
      if (row.nextSyncAt == null) {
        // Idle connected source with no active recurring job row.
        return true;
      }
      final nextSync = DateTime.tryParse(row.nextSyncAt!);
      if (nextSync != null && nextSync.isAfter(DateTime.now())) {
        return true;
      }
      return false;
    }
    return true;
  }

  /// Whether every source in a snapshot has settled (empty list => settled).
  static bool statusesSettled(List<SourceSyncStatusOut> statuses) {
    return statuses.every(isStatusSettled);
  }

  /// Clear the timeout/progress banner once all sources in a snapshot settled.
  static String? clearSyncContinuesMessageIfSettled({
    required String? message,
    required List<SourceSyncStatusOut> statuses,
  }) {
    if (message == syncContinuesMessage && statusesSettled(statuses)) {
      return null;
    }
    return message;
  }

  Future<SourceRefreshResult> refreshSources({
    Duration timeout = defaultTimeout,
    Duration pollInterval = SourceRefreshService.pollInterval,
  }) async {
    await _apiClient.triggerSourceSync();
    final stopwatch = Stopwatch()..start();
    List<SourceSyncStatusOut> statuses = [];
    while (stopwatch.elapsed < timeout) {
      statuses = await _apiClient.getSourceStatus();
      if (statusesSettled(statuses)) {
        return SourceRefreshResult(timedOut: false, statuses: statuses);
      }
      final remaining = timeout - stopwatch.elapsed;
      if (remaining <= Duration.zero) {
        break;
      }
      await Future.delayed(
        remaining < pollInterval ? remaining : pollInterval,
      );
    }
    statuses = await _apiClient.getSourceStatus();
    return SourceRefreshResult(
      timedOut: !statusesSettled(statuses),
      statuses: statuses,
    );
  }
}
