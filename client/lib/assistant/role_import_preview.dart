import 'package:flutter/material.dart';

import '../api/role_import_models.dart';

class RoleImportPreviewPanel extends StatelessWidget {
  const RoleImportPreviewPanel({
    super.key,
    required this.loading,
    required this.error,
    required this.preview,
    required this.onExtract,
    this.groundingLoading = false,
    this.groundingError,
    this.grounded,
    this.sourceStale = false,
    this.onGround,
  });

  final bool loading;
  final String? error;
  final RoleImportPreview? preview;
  final VoidCallback onExtract;
  final bool groundingLoading;
  final String? groundingError;
  final RoleImportGroundedPreview? grounded;
  final bool sourceStale;
  final VoidCallback? onGround;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          TextButton(
            key: const Key('extract_roles_button'),
            onPressed: loading ? null : onExtract,
            child: const Text('Извлечь роли'),
          ),
          if (loading)
            const Padding(
              padding: EdgeInsets.only(top: 8),
              child: CircularProgressIndicator(
                key: Key('role_import_loading'),
              ),
            ),
          if (error != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(error!, key: const Key('role_import_error')),
                  TextButton(
                    key: const Key('role_import_retry'),
                    onPressed: onExtract,
                    child: const Text('Повторить'),
                  ),
                ],
              ),
            ),
          if (preview != null) ...[
            Text(
              'Черновик извлечения ролей',
              key: const Key('role_import_heading'),
            ),
            const Text(
              'Ничего не сохранено',
              key: Key('role_import_nothing_saved'),
            ),
            if (preview!.items.isEmpty)
              const Text(
                'Роли не найдены',
                key: Key('role_import_empty'),
              ),
            if (preview!.sourceTruncated || preview!.itemsTruncated)
              const Text(
                'Источник или список строк обрезан',
                key: Key('role_import_truncation'),
              ),
            for (final item in preview!.items)
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(item.personName),
                  Text(item.role),
                  if (item.contextText != null) Text(item.contextText!),
                  Text(item.evidenceText),
                  if (item.sourceLocator != null) Text(item.sourceLocator!),
                ],
              ),
            if (preview!.items.isNotEmpty && onGround != null && !sourceStale)
              TextButton(
                key: const Key('ground_roles_button'),
                onPressed: loading || groundingLoading ? null : onGround,
                child: const Text('Сопоставить'),
              ),
            if (sourceStale)
              const Text(
                'Источник изменился — извлеките роли заново',
                key: Key('role_import_source_stale'),
              ),
            if (groundingLoading)
              const Padding(
                padding: EdgeInsets.only(top: 8),
                child: CircularProgressIndicator(
                  key: Key('role_grounding_loading'),
                ),
              ),
            if (groundingError != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(
                  groundingError!,
                  key: const Key('role_grounding_error'),
                ),
              ),
            if (grounded != null)
              for (final item in grounded!.items) _GroundedRow(item: item),
          ],
        ],
      ),
    );
  }
}

class _GroundedRow extends StatelessWidget {
  const _GroundedRow({required this.item});

  final RoleImportGroundedItem item;

  @override
  Widget build(BuildContext context) {
    final person = item.personResolution;
    final role = item.roleResolution;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (person.state == 'resolved')
          Text('Person: ${person.title}', key: const Key('role_person_resolved')),
        if (person.state == 'ambiguous') ...[
          const Text('Нужно выбрать Person', key: Key('role_person_ambiguous')),
          for (final candidate in person.candidates) Text(candidate.title),
        ],
        if (person.state == 'promotion_candidates') ...[
          const Text(
            'Можно предложить нового Person',
            key: Key('role_person_promotion'),
          ),
          for (final candidate in person.promotionCandidates)
            Text(
              '${candidate.displayName} · ${candidate.provider} · ${candidate.directHitCount}',
            ),
        ],
        if (person.state == 'unresolved')
          const Text('Person не найден', key: Key('role_person_unresolved')),
        if (role.state == 'reuse_existing')
          Text(
            'Использовать существующую роль: ${role.displayText}',
            key: const Key('role_existing'),
          ),
        if (role.state == 'propose_new') ...[
          Text('Новая роль: ${role.displayText}', key: const Key('role_new')),
          if (role.suggestions.isNotEmpty) ...[
            const Text('Похожие термины', key: Key('role_suggestions')),
            for (final suggestion in role.suggestions) Text(suggestion),
          ],
        ],
      ],
    );
  }
}
