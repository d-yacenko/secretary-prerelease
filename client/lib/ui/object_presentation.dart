import 'package:flutter/material.dart';

import 'app_spacing.dart';
import 'provider_icon.dart';

/// Shared kind/provider presentation for Search, Graph filters, and cards.

const Map<String, String> objectKindLabels = {
  'task': 'Задача',
  'email': 'Письмо',
  'calendar_event': 'Событие',
  'event': 'Событие',
  'project': 'Проект',
  'note': 'Заметка',
  'web_page': 'Веб-страница',
  'file': 'Файл',
  'folder': 'Папка',
  'document': 'Документ',
  'dataset': 'Таблица',
  'chat': 'Чат',
  'message': 'Сообщение',
  'chat_message': 'Сообщение',
  'label': 'Метка',
  'scheduled_activity': 'Активность',
  'temporal_hint': 'Возможное время',
};

const Map<String, String> providerLabels = {
  'gmail': 'Gmail',
  'yandex_mail': 'Яндекс',
  'local_device': 'Компьютер',
  'upload': 'Загрузка',
  'web': 'Веб',
  'google': 'Google',
  'google_calendar': 'Google Календарь',
  'google_drive': 'Google Диск',
  'yandex': 'Яндекс',
  'yandex_calendar': 'Яндекс Календарь',
  'yandex_disk': 'Яндекс.Диск',
  'calendar': 'Календарь',
  'outlook': 'Outlook',
  'microsoft': 'Microsoft',
  'telegram': 'Telegram',
  'teams': 'Microsoft Teams',
  'slack': 'Slack',
  'mattermost': 'Mattermost',
};

const Map<String, String> providerCompactGlyphs = {
  'gmail': 'G',
  'google_calendar': 'G',
  'yandex_mail': 'Я',
  'yandex_calendar': 'Я',
  'local_device': 'ПК',
  'upload': '↑',
  'web': 'W',
  'google_drive': 'G',
  'yandex_disk': 'Я',
  'mattermost': 'M',
  'telegram': 'T',
  'teams': 'Ms',
};

String objectKindLabel(String kind) => objectKindLabels[kind] ?? kind;

String providerLabel(String? provider) {
  if (provider == null || provider.isEmpty) {
    return 'Источник';
  }
  return providerLabels[provider] ?? provider;
}

String? providerCompactGlyph(String? provider) {
  if (provider == null || provider.isEmpty) {
    return null;
  }
  return providerCompactGlyphs[provider];
}

IconData iconForObjectKind(String kind) {
  switch (kind) {
    case 'task':
      return Icons.task_alt_outlined;
    case 'email':
      return Icons.email_outlined;
    case 'event':
    case 'calendar_event':
      return Icons.event_outlined;
    case 'file':
      return Icons.insert_drive_file_outlined;
    case 'document':
      return Icons.description_outlined;
    case 'dataset':
      return Icons.table_chart_outlined;
    case 'note':
      return Icons.sticky_note_2_outlined;
    case 'web_page':
      return Icons.language_outlined;
    case 'folder':
      return Icons.folder_outlined;
    case 'chat':
    case 'message':
    case 'chat_message':
      return Icons.chat_bubble_outline;
    case 'project':
      return Icons.work_outline;
    case 'label':
      return Icons.label_outline;
    case 'temporal_hint':
      return Icons.schedule_outlined;
    default:
      return Icons.category_outlined;
  }
}

IconData iconForKind(String kind) => iconForObjectKind(kind);

/// Compact provider icon for header rows; null when provider is absent.
Widget? compactProviderGlyphWidget(String? provider, {double size = 14}) {
  if (!providerHasIdentity(provider)) {
    return null;
  }
  return ProviderSourceIcon(provider: provider, size: size);
}

Widget providerCompactIcon(String? provider, {double size = 18}) {
  if (!providerHasIdentity(provider)) {
    return Icon(Icons.source_outlined, size: size);
  }
  return ProviderSourceIcon(provider: provider, size: size);
}

/// Compact title + kind icon + provider icon + trailing metadata on one row.
class ObjectCompactHeaderRow extends StatelessWidget {
  const ObjectCompactHeaderRow({
    super.key,
    required this.title,
    required this.kind,
    this.provider,
    required this.trailingText,
    this.trailingBadges = const [],
    this.semanticsLabel,
    this.trailingTooltip,
    this.onProviderTap,
    this.titleMaxLines,
    this.trailingReserve = 0,
  });

  final String title;
  final String kind;
  final String? provider;
  final String trailingText;
  final List<Widget> trailingBadges;
  final String? semanticsLabel;
  final String? trailingTooltip;
  final VoidCallback? onProviderTap;
  final int? titleMaxLines;

  /// Extra space after trailing metadata so an overlay bookmark does not cover it.
  final double trailingReserve;

  @override
  Widget build(BuildContext context) {
    final kindLabel = objectKindLabel(kind);
    final providerName = providerLabel(provider);
    final label = semanticsLabel ?? '$kindLabel, $providerName';
    final titleStyle = Theme.of(
      context,
    ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w600);
    final metadataStyle = Theme.of(context).textTheme.bodySmall;
    final wide = isWideLayout(context);
    final maxLines = titleMaxLines ?? (wide ? 1 : 2);

    return Semantics(
      label: label,
      child: LayoutBuilder(
        builder: (context, constraints) {
          final trailingMaxWidth = constraints.maxWidth > trailingReserve
              ? constraints.maxWidth - trailingReserve
              : 0.0;
          return Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Icon(
                iconForKind(kind),
                size: AppSpacing.kindIconSize,
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
              if (providerHasIdentity(provider)) ...[
                const SizedBox(width: AppSpacing.xs),
                ProviderSourceIcon(
                  provider: provider,
                  size: AppSpacing.providerIconSize,
                  onPressed: onProviderTap,
                  openTooltip: onProviderTap == null
                      ? providerName
                      : 'Открыть в источнике',
                ),
              ],
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Text(
                  title,
                  style: titleStyle,
                  overflow: TextOverflow.ellipsis,
                  maxLines: maxLines,
                ),
              ),
              ...trailingBadges.map(
                (badge) => Padding(
                  padding: const EdgeInsets.only(left: AppSpacing.xs),
                  child: badge,
                ),
              ),
              if (trailingText.isNotEmpty) ...[
                const SizedBox(width: AppSpacing.sm),
                ConstrainedBox(
                  constraints: BoxConstraints(maxWidth: trailingMaxWidth),
                  child: Tooltip(
                    message: trailingTooltip ?? trailingText,
                    child: Text(
                      key: const Key('object_compact_header_timestamp'),
                      trailingText,
                      style: metadataStyle,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      textAlign: TextAlign.right,
                    ),
                  ),
                ),
              ],
              if (trailingReserve > 0) SizedBox(width: trailingReserve),
            ],
          );
        },
      ),
    );
  }
}
