import 'package:flutter/material.dart';

import '../api/api_models.dart';
import '../ui/object_bookmark.dart';
import '../ui/object_presentation.dart';
import '../ui/provider_icon.dart';
import 'relation_target_label.dart';

/// One compact Add-relation candidate. Kind, provider, title, and bookmark
/// share a single row. Kind text stays in semantics, not a second line.
class RelationTargetRow extends StatelessWidget {
  const RelationTargetRow({
    super.key,
    required this.object,
    required this.results,
    required this.confirmedParentTitleByTaskId,
    required this.selected,
    required this.onTap,
    this.bookmarkColor,
  });

  final SecretaryObject object;
  final List<SecretaryObject> results;
  final Map<String, String?> confirmedParentTitleByTaskId;
  final bool selected;
  final VoidCallback onTap;
  final String? bookmarkColor;

  @override
  Widget build(BuildContext context) {
    final ongoing = object.isOngoingTask;
    final label = relationTargetLabel(
      object: object,
      results: results,
      confirmedParentTitleByTaskId: confirmedParentTitleByTaskId,
    );
    final kindName = ongoing ? 'Направление' : objectKindLabel(object.kind);
    return Semantics(
      label: kindName,
      selected: selected,
      button: true,
      child: ListTile(
        key: ValueKey('relation-target-${object.id}'),
        dense: true,
        visualDensity: VisualDensity.compact,
        minVerticalPadding: 0,
        contentPadding: const EdgeInsets.symmetric(horizontal: 8),
        selected: selected,
        onTap: onTap,
        title: Row(
          children: [
            Icon(
              ongoing ? Icons.all_inclusive : iconForKind(object.kind),
              size: 18,
              key: ValueKey(
                ongoing
                    ? 'relation-target-ongoing-${object.id}'
                    : 'relation-target-kind-${object.id}',
              ),
            ),
            if (providerHasIdentity(object.provider)) ...[
              const SizedBox(width: 6),
              ProviderSourceIcon(provider: object.provider, size: 16),
            ],
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
            if (bookmarkColor != null) ...[
              const SizedBox(width: 6),
              ObjectBookmarkGlyph(
                key: ValueKey('relation-target-bookmark-${object.id}'),
                fillColor: bookmarkTokenColor(
                  bookmarkColor!,
                  Theme.of(context).colorScheme,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
