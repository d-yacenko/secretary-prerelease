import 'package:flutter/material.dart';

import '../api/api_models.dart';
import '../ui/date_format.dart';

/// Friendly provider names for source-sync error diagnostics.
const Map<String, String> sourceSyncProviderLabels = {
  'gmail': 'Gmail',
  'google_calendar': 'Google Calendar',
  'yandex_mail': 'Yandex Mail',
  'yandex_calendar': 'Yandex Calendar',
  'mattermost': 'Mattermost',
  'teams': 'Microsoft Teams',
};

const String _genericSyncErrorReason = 'Не удалось синхронизировать источник';

final RegExp _uuidPattern = RegExp(
  r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
  caseSensitive: false,
);

const List<String> _sensitiveErrorNeedles = [
  'bearer ',
  'authorization:',
  'authorization ',
  'access_token',
  'refresh_token',
  'access-token',
  'personal-access',
  'personal access',
  'encrypted',
  'sk-',
];

String sourceSyncProviderLabel(String provider) =>
    sourceSyncProviderLabels[provider] ?? provider;

bool sourceSyncAccountLabelIsUseful(SourceSyncStatusOut row) {
  final label = row.accountLabel.trim();
  if (label.isEmpty) {
    return false;
  }
  if (label == row.accountId.trim()) {
    return false;
  }
  return !_uuidPattern.hasMatch(label);
}

String sourceSyncErrorHeadline(SourceSyncStatusOut row) {
  final provider = sourceSyncProviderLabel(row.provider);
  if (sourceSyncAccountLabelIsUseful(row)) {
    return '$provider — ${row.accountLabel.trim()}';
  }
  return provider;
}

bool _errorTextIsSafeForDisplay(String text) {
  final lowered = text.toLowerCase();
  for (final needle in _sensitiveErrorNeedles) {
    if (lowered.contains(needle)) {
      return false;
    }
  }
  return true;
}

String sourceSyncSafeErrorReason(SourceSyncStatusOut row) {
  final raw = row.lastError?.trim();
  if (raw == null || raw.isEmpty) {
    return _genericSyncErrorReason;
  }
  final firstLine = raw.split('\n').first.trim();
  if (firstLine.isEmpty || !_errorTextIsSafeForDisplay(firstLine)) {
    return _genericSyncErrorReason;
  }
  return firstLine;
}

String? sourceSyncLastSuccessLine(SourceSyncStatusOut row) {
  final formatted = formatUserDateTime(row.lastSuccessAt);
  if (formatted.isEmpty) {
    return null;
  }
  return 'Последняя успешная синхронизация: $formatted';
}

String? sourceSyncLastAttemptLine(SourceSyncStatusOut row) {
  final formatted = formatUserDateTime(row.lastAttemptAt);
  if (formatted.isEmpty) {
    return null;
  }
  return 'Последняя попытка: $formatted';
}

String? sourceSyncNextAttemptLine(SourceSyncStatusOut row) {
  final formatted = formatUserDateTime(row.nextSyncAt);
  if (formatted.isEmpty) {
    return null;
  }
  return 'Следующая попытка: $formatted';
}

bool sourceSyncIsTransient(SourceSyncStatusOut row) =>
    row.status == 'error' && row.errorKind == 'transient';

List<SourceSyncStatusOut> sourceSyncTransientRows(
  List<SourceSyncStatusOut> rows,
) => rows.where(sourceSyncIsTransient).toList();

List<SourceSyncStatusOut> sourceSyncErrorRows(List<SourceSyncStatusOut> rows) =>
    rows
        .where((row) => row.status == 'error' && !sourceSyncIsTransient(row))
        .toList();

String? sourceSyncActionGuidance(SourceSyncStatusOut row) {
  switch (row.errorKind) {
    case 'authentication':
      if (row.provider == 'yandex_mail') {
        return 'Проверьте пароль приложения для Яндекс Почты и переподключите аккаунт.';
      }
      if (row.provider == 'yandex_calendar') {
        return 'Проверьте пароль приложения для Яндекс Календаря и переподключите аккаунт.';
      }
      return 'Проверьте учётные данные и переподключите аккаунт.';
    case 'permission':
      return 'Проверьте разрешения доступа к источнику. Пароль менять не нужно.';
    default:
      return null;
  }
}

class SourceSyncTransientList extends StatelessWidget {
  const SourceSyncTransientList({super.key, required this.rows});

  final List<SourceSyncStatusOut> rows;

  @override
  Widget build(BuildContext context) {
    if (rows.isEmpty) {
      return const SizedBox.shrink();
    }
    final colorScheme = Theme.of(context).colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: rows.map((row) {
        final lastSuccess = sourceSyncLastSuccessLine(row);
        final lastAttempt = sourceSyncLastAttemptLine(row);
        final nextAttempt = sourceSyncNextAttemptLine(row);
        return Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: DecoratedBox(
            decoration: BoxDecoration(
              color: colorScheme.surfaceContainerHighest.withValues(
                alpha: 0.45,
              ),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    sourceSyncErrorHeadline(row),
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                  const SizedBox(height: 4),
                  const Text(
                    'Временная ошибка синхронизации. Повторим автоматически.',
                  ),
                  if (lastSuccess != null) ...[
                    const SizedBox(height: 4),
                    Text(lastSuccess),
                  ],
                  if (lastAttempt != null) ...[
                    const SizedBox(height: 4),
                    Text(lastAttempt),
                  ],
                  if (nextAttempt != null) ...[
                    const SizedBox(height: 4),
                    Text(nextAttempt),
                  ],
                ],
              ),
            ),
          ),
        );
      }).toList(),
    );
  }
}

class SourceSyncErrorList extends StatelessWidget {
  const SourceSyncErrorList({
    super.key,
    required this.errorRows,
  });

  final List<SourceSyncStatusOut> errorRows;

  @override
  Widget build(BuildContext context) {
    if (errorRows.isEmpty) {
      return const SizedBox.shrink();
    }
    final colorScheme = Theme.of(context).colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: errorRows.map((row) {
        final lastSuccess = sourceSyncLastSuccessLine(row);
        final lastAttempt = sourceSyncLastAttemptLine(row);
        final action = sourceSyncActionGuidance(row);
        return Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Card(
            color: colorScheme.errorContainer.withValues(alpha: 0.35),
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    sourceSyncErrorHeadline(row),
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'Ошибка синхронизации: ${sourceSyncSafeErrorReason(row)}',
                  ),
                  if (action != null) ...[
                    const SizedBox(height: 4),
                    Text(action),
                  ],
                  if (lastSuccess != null) ...[
                    const SizedBox(height: 4),
                    Text(lastSuccess),
                  ],
                  if (lastAttempt != null) ...[
                    const SizedBox(height: 4),
                    Text(lastAttempt),
                  ],
                ],
              ),
            ),
          ),
        );
      }).toList(),
    );
  }
}
