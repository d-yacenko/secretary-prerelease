import 'package:flutter/material.dart';

import '../api/api_models.dart';
import 'source_history_days_format.dart';
import 'source_sync_interval_format.dart';

const Map<String, String> sourcePreferenceLabels = {
  'gmail': 'Gmail',
  'google_calendar': 'Google Календарь',
  'yandex_mail': 'Яндекс Почта',
  'yandex_calendar': 'Яндекс Календарь',
  'mattermost': 'Mattermost',
  'teams': 'Microsoft Teams',
};

bool sourcePreferenceConnected(String source, Connections connections) {
  switch (source) {
    case 'gmail':
      return connections.google.gmailAvailable;
    case 'google_calendar':
      return connections.google.calendarAvailable;
    case 'yandex_mail':
      return connections.yandexMail.connected;
    case 'yandex_calendar':
      return connections.yandexCalendar.connected;
    case 'mattermost':
      return connections.mattermost.isNotEmpty;
    case 'teams':
      return connections.teams.connected;
    default:
      return false;
  }
}

String sourcePreferenceLabel(String source) =>
    sourcePreferenceLabels[source] ?? source;

class SourcePreferencesList extends StatelessWidget {
  const SourcePreferencesList({
    super.key,
    required this.preferences,
    required this.connections,
    required this.savingSources,
    required this.rowErrors,
    required this.onToggleEnabled,
    required this.onCadenceChanged,
    required this.onHistoryChanged,
    required this.onReset,
  });

  final List<SourcePreference> preferences;
  final Connections connections;
  final Set<String> savingSources;
  final Map<String, String> rowErrors;
  final Future<void> Function(String source, bool enabled) onToggleEnabled;
  final Future<void> Function(String source, int seconds) onCadenceChanged;
  final Future<void> Function(String source, int days) onHistoryChanged;
  final Future<void> Function(String source) onReset;

  @override
  Widget build(BuildContext context) {
    final rows = <Widget>[];
    for (var index = 0; index < preferences.length; index++) {
      final preference = preferences[index];
      rows.add(
        _SourcePreferenceRow(
          key: Key('source-preference-${preference.source}'),
          preference: preference,
          connected: sourcePreferenceConnected(preference.source, connections),
          saving: savingSources.contains(preference.source),
          rowError: rowErrors[preference.source],
          onToggleEnabled: onToggleEnabled,
          onCadenceChanged: onCadenceChanged,
          onHistoryChanged: onHistoryChanged,
          onReset: onReset,
        ),
      );
      if (index < preferences.length - 1) {
        rows.add(const Divider(height: 20));
      }
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: rows,
    );
  }
}

class _SourcePreferenceRow extends StatelessWidget {
  const _SourcePreferenceRow({
    super.key,
    required this.preference,
    required this.connected,
    required this.saving,
    required this.rowError,
    required this.onToggleEnabled,
    required this.onCadenceChanged,
    required this.onHistoryChanged,
    required this.onReset,
  });

  final SourcePreference preference;
  final bool connected;
  final bool saving;
  final String? rowError;
  final Future<void> Function(String source, bool enabled) onToggleEnabled;
  final Future<void> Function(String source, int seconds) onCadenceChanged;
  final Future<void> Function(String source, int days) onHistoryChanged;
  final Future<void> Function(String source) onReset;

  @override
  Widget build(BuildContext context) {
    final cadenceChoices = availableSyncIntervalChoices(
      currentSeconds: preference.syncIntervalSeconds,
      minSeconds: preference.minSyncIntervalSeconds,
      maxSeconds: preference.maxSyncIntervalSeconds,
    );
    final historyChoices = availableHistoryDayChoices(
      currentDays: preference.historyDays,
      minDays: preference.minHistoryDays,
      maxDays: preference.maxHistoryDays,
    );
    final subdued = Theme.of(context).textTheme.bodySmall?.copyWith(
          color: Theme.of(context).colorScheme.onSurfaceVariant,
        );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Expanded(
              child: Wrap(
                spacing: 8,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  Text(
                    sourcePreferenceLabel(preference.source),
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                  if (!connected) Text('Не подключено', style: subdued),
                ],
              ),
            ),
            if (saving)
              const Padding(
                padding: EdgeInsets.only(right: 8),
                child: SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              ),
            Switch(
              value: preference.enabled,
              onChanged: saving
                  ? null
                  : (value) => onToggleEnabled(preference.source, value),
            ),
          ],
        ),
        const SizedBox(height: 4),
        Wrap(
          spacing: 12,
          runSpacing: 4,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text('Интервал:',
                    style: Theme.of(context).textTheme.bodyMedium),
                const SizedBox(width: 8),
                DropdownButton<int>(
                  value: preference.syncIntervalSeconds,
                  items: cadenceChoices
                      .map(
                        (seconds) => DropdownMenuItem(
                          value: seconds,
                          child: Text(formatSyncIntervalSeconds(seconds)),
                        ),
                      )
                      .toList(),
                  onChanged: saving
                      ? null
                      : (value) {
                          if (value != null &&
                              value != preference.syncIntervalSeconds) {
                            onCadenceChanged(preference.source, value);
                          }
                        },
                ),
              ],
            ),
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text('История:', style: Theme.of(context).textTheme.bodyMedium),
                const SizedBox(width: 8),
                DropdownButton<int>(
                  key: Key('source-history-dropdown-${preference.source}'),
                  value: preference.historyDays,
                  items: historyChoices
                      .map(
                        (days) => DropdownMenuItem(
                          value: days,
                          child: Text(formatHistoryDays(days)),
                        ),
                      )
                      .toList(),
                  onChanged: saving
                      ? null
                      : (value) {
                          if (value != null &&
                              value != preference.historyDays) {
                            onHistoryChanged(preference.source, value);
                          }
                        },
                ),
                const SizedBox(width: 8),
                Text(
                  'По умолчанию: ${formatHistoryDays(preference.defaultHistoryDays)}',
                  style: subdued,
                ),
              ],
            ),
            TextButton(
              onPressed: saving ? null : () => onReset(preference.source),
              child: const Text('По умолчанию'),
            ),
          ],
        ),
        if (rowError != null)
          Text(
            rowError!,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
      ],
    );
  }
}
