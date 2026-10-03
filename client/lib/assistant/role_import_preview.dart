import 'package:flutter/material.dart';

import '../api/role_import_models.dart';

class RoleImportPreviewPanel extends StatelessWidget {
  const RoleImportPreviewPanel({
    super.key,
    required this.loading,
    required this.error,
    required this.preview,
    required this.onExtract,
  });

  final bool loading;
  final String? error;
  final RoleImportPreview? preview;
  final VoidCallback onExtract;

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
          ],
        ],
      ),
    );
  }
}
