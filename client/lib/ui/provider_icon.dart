import 'package:flutter/material.dart';

import 'app_spacing.dart';
import 'object_presentation.dart';
import 'provider_source_mark.dart';

export 'provider_source_mark.dart';

class ProviderVisual {
  const ProviderVisual({
    required this.mark,
    required this.label,
    this.icon,
    this.color = const Color(0xFF607D8B),
  });

  final ProviderSourceMark mark;
  final String label;
  final IconData? icon;
  final Color color;
}

ProviderSourceMark providerSourceMark(String? provider) {
  switch (provider?.trim() ?? '') {
    case 'gmail':
    case 'google_calendar':
    case 'google_drive':
    case 'google':
      return ProviderSourceMark.google;
    case 'yandex_mail':
    case 'yandex_calendar':
    case 'yandex_disk':
    case 'yandex':
      return ProviderSourceMark.yandex;
    case 'mattermost':
      return ProviderSourceMark.mattermost;
    case 'telegram':
      return ProviderSourceMark.telegram;
    case 'teams':
      return ProviderSourceMark.teams;
    case 'local_device':
      return ProviderSourceMark.computer;
    case 'web':
      return ProviderSourceMark.web;
    case 'upload':
      return ProviderSourceMark.file;
    case 'cloud':
      return ProviderSourceMark.cloud;
    default:
      return ProviderSourceMark.fallback;
  }
}

ProviderVisual providerVisual(String? provider) {
  final key = provider?.trim() ?? '';
  final mark = providerSourceMark(key);
  final label = providerLabel(key.isEmpty ? provider : key);
  switch (mark) {
    case ProviderSourceMark.google:
      return ProviderVisual(mark: mark, label: label, color: const Color(0xFF4285F4));
    case ProviderSourceMark.yandex:
      return ProviderVisual(mark: mark, label: label, color: const Color(0xFFFC3F1D));
    case ProviderSourceMark.mattermost:
      return ProviderVisual(mark: mark, label: label, color: const Color(0xFF0058CC));
    case ProviderSourceMark.telegram:
      return ProviderVisual(
        mark: mark,
        label: label,
        icon: Icons.telegram,
        color: const Color(0xFF229ED9),
      );
    case ProviderSourceMark.teams:
      return ProviderVisual(
        mark: mark,
        label: label,
        icon: Icons.groups,
        color: const Color(0xFF6264A7),
      );
    case ProviderSourceMark.computer:
      return ProviderVisual(
        mark: mark,
        label: label,
        icon: Icons.computer,
        color: const Color(0xFF5F6368),
      );
    case ProviderSourceMark.cloud:
      return ProviderVisual(
        mark: mark,
        label: label,
        icon: Icons.cloud_outlined,
        color: const Color(0xFF5F6368),
      );
    case ProviderSourceMark.web:
      return ProviderVisual(
        mark: mark,
        label: label,
        icon: Icons.language,
        color: const Color(0xFF1A73E8),
      );
    case ProviderSourceMark.file:
      return ProviderVisual(
        mark: mark,
        label: label,
        icon: Icons.upload_file,
        color: const Color(0xFF7B61FF),
      );
    case ProviderSourceMark.fallback:
      return ProviderVisual(
        mark: mark,
        label: label,
        icon: Icons.source_outlined,
        color: const Color(0xFF607D8B),
      );
  }
}

bool providerHasIdentity(String? provider) {
  return provider != null && provider.trim().isNotEmpty;
}

/// Source-system mark. Distinct from Object kind icons.
class ProviderSourceIcon extends StatelessWidget {
  const ProviderSourceIcon({
    super.key,
    required this.provider,
    this.size = AppSpacing.providerIconSize,
    this.onPressed,
    this.openTooltip,
  });

  final String? provider;
  final double size;
  final VoidCallback? onPressed;
  final String? openTooltip;

  @override
  Widget build(BuildContext context) {
    if (!providerHasIdentity(provider)) {
      return const SizedBox.shrink();
    }
    final visual = providerVisual(provider);
    final artSize = size.clamp(14.0, 18.0);
    final mark = ProviderSourceMarkView(mark: visual.mark, size: artSize);
    final semantics = openTooltip ?? visual.label;
    if (onPressed == null) {
      return KeyedSubtree(
        key: Key('provider_icon_${provider!.trim()}'),
        child: Tooltip(
          message: semantics,
          child: Semantics(
            label: semantics,
            child: SizedBox(
              width: artSize,
              height: artSize,
              child: mark,
            ),
          ),
        ),
      );
    }
    final compact = isWideLayout(context);
    return IconButton(
      key: Key('provider_open_${provider!.trim()}'),
      tooltip: openTooltip ?? 'Открыть в источнике',
      onPressed: onPressed,
      visualDensity:
          compact ? VisualDensity.compact : VisualDensity.standard,
      padding: compact ? const EdgeInsets.all(AppSpacing.xs) : null,
      constraints: compact
          ? const BoxConstraints(minWidth: 32, minHeight: 32)
          : const BoxConstraints(minWidth: 40, minHeight: 40),
      icon: mark,
    );
  }
}
