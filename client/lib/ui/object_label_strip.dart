import 'package:flutter/material.dart';

import '../api/api_models.dart';
import 'app_spacing.dart';

class ObjectLabelStrip extends StatelessWidget {
  const ObjectLabelStrip({
    super.key,
    required this.labels,
    this.maxVisible = 2,
    this.alignment = WrapAlignment.start,
  });

  final List<LabelItem> labels;
  final int maxVisible;
  final WrapAlignment alignment;

  @override
  Widget build(BuildContext context) {
    if (labels.isEmpty) {
      return const SizedBox.shrink();
    }
    final visible = labels.take(maxVisible).toList();
    final overflow = labels.length - visible.length;
    final scheme = Theme.of(context).colorScheme;
    final style = Theme.of(context).textTheme.labelSmall?.copyWith(
          color: scheme.onSurfaceVariant,
          fontWeight: FontWeight.w500,
          height: 1.1,
          fontSize: 11,
        );
    return Wrap(
      spacing: 4,
      runSpacing: 2,
      alignment: alignment,
      children: [
        for (final label in visible)
          Tooltip(
            message: _tooltip(label),
            child: Semantics(
              label: _tooltip(label),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 180),
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    color: scheme.surfaceContainerHighest.withValues(alpha: 0.7),
                    borderRadius: BorderRadius.circular(3),
                    border: Border.all(color: scheme.outlineVariant),
                  ),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 6,
                      vertical: 1,
                    ),
                    child: Text(
                      label.title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: style,
                    ),
                  ),
                ),
              ),
            ),
          ),
        if (overflow > 0)
          Tooltip(
            message: labels.skip(maxVisible).map((e) => e.title).join(', '),
            child: Semantics(
              label: '+$overflow',
              child: DecoratedBox(
                key: const Key('object_label_overflow'),
                decoration: BoxDecoration(
                  color: scheme.surfaceContainerHighest.withValues(alpha: 0.7),
                  borderRadius: BorderRadius.circular(3),
                  border: Border.all(color: scheme.outlineVariant),
                ),
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 6,
                    vertical: 1,
                  ),
                  child: Text('+$overflow', style: style),
                ),
              ),
            ),
          ),
      ],
    );
  }

  String _tooltip(LabelItem label) {
    final description = label.description?.trim();
    if (description == null || description.isEmpty) {
      return label.title;
    }
    return '${label.title}\n$description';
  }
}

/// Compact actions + labels row shared by Inbox / Today / Search cards.
class ObjectMetaActionRow extends StatelessWidget {
  const ObjectMetaActionRow({
    super.key,
    this.actions = const [],
    this.labels = const [],
  });

  final List<Widget> actions;
  final List<LabelItem> labels;

  @override
  Widget build(BuildContext context) {
    if (actions.isEmpty && labels.isEmpty) {
      return const SizedBox.shrink();
    }
    final wide = isWideLayout(context);
    final labelStrip = labels.isEmpty
        ? null
        : ObjectLabelStrip(
            labels: labels,
            alignment: wide ? WrapAlignment.end : WrapAlignment.start,
          );
    if (!wide) {
      return Padding(
        padding: const EdgeInsets.only(top: 2),
        child: Wrap(
          spacing: AppSpacing.xs,
          runSpacing: 2,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            ...actions,
            if (labelStrip != null) labelStrip,
          ],
        ),
      );
    }
    return Padding(
      padding: const EdgeInsets.only(top: 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          if (actions.isNotEmpty)
            Wrap(
              spacing: AppSpacing.xs,
              runSpacing: 2,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: actions,
            ),
          if (labelStrip != null) ...[
            if (actions.isNotEmpty) const SizedBox(width: AppSpacing.sm),
            Expanded(
              child: Align(
                alignment: Alignment.centerRight,
                child: labelStrip,
              ),
            ),
          ],
        ],
      ),
    );
  }
}
