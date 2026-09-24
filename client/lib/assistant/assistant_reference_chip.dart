import 'package:flutter/material.dart';

import '../api/api_models.dart';
import '../ui/date_format.dart';
import '../ui/object_presentation.dart';
import '../ui/provider_icon.dart';

class AssistantReferenceChip extends StatelessWidget {
  const AssistantReferenceChip({
    super.key,
    required this.reference,
    required this.onPressed,
  });

  final AssistantReference reference;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final date = formatCompactChipDate(reference.primaryAt);
    final kindLabel = objectKindLabel(reference.kind);
    final provider = reference.provider?.trim();
    final hasProvider = provider != null && provider.isNotEmpty;
    final tooltip = [
      kindLabel,
      if (hasProvider) provider,
      reference.title,
      if (date != null) date,
    ].join(' · ');
    final subdued = Theme.of(context).textTheme.labelSmall?.copyWith(
      color: Theme.of(context).colorScheme.onSurfaceVariant,
    );
    return Tooltip(
      message: tooltip,
      child: Semantics(
        label: tooltip,
        button: true,
        child: ActionChip(
          key: Key('assistant_reference_${reference.objectId}'),
          onPressed: onPressed,
          label: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(iconForObjectKind(reference.kind), size: 16),
              if (hasProvider) ...[
                const SizedBox(width: 4),
                ProviderSourceIcon(provider: provider, size: 16),
              ],
              const SizedBox(width: 4),
              Text(reference.title),
              if (date != null) ...[
                const SizedBox(width: 6),
                Text(date, style: subdued),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
