import 'package:flutter/material.dart';

import 'provider_icon.dart';

export 'object_presentation.dart'
    show iconForKind, objectKindLabel, providerLabel, providerCompactGlyph;
export 'provider_icon.dart'
    show
        ProviderSourceIcon,
        providerVisual,
        providerHasIdentity,
        providerSourceMark,
        ProviderSourceMark;

Widget providerBadge(BuildContext context, String? provider) {
  if (!providerHasIdentity(provider)) {
    return const SizedBox.shrink();
  }
  final visual = providerVisual(provider);
  return Tooltip(
    message: visual.label,
    child: ProviderSourceIcon(provider: provider, size: 16),
  );
}
