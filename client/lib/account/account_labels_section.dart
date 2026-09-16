import 'package:flutter/material.dart';

import '../api/api_error.dart';
import '../api/api_models.dart';
import '../api/secretary_api_client.dart';
import '../auth/auth_controller.dart';
import 'account_layout.dart';

String labelConflictMessage(ApiException error) {
  final raw = error.message.toLowerCase();
  if (raw.contains('already exists')) {
    return 'Метка с таким именем уже существует.';
  }
  return error.message;
}

class AccountLabelsSection extends StatefulWidget {
  const AccountLabelsSection({
    super.key,
    required this.apiClient,
    required this.authController,
  });

  final SecretaryApiClient apiClient;
  final AuthController authController;

  @override
  State<AccountLabelsSection> createState() => _AccountLabelsSectionState();
}

class _AccountLabelsSectionState extends State<AccountLabelsSection> {
  List<LabelItem> _labels = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final result = await widget.apiClient.listLabels();
      if (!mounted) {
        return;
      }
      setState(() {
        _labels = result.labels;
        _loading = false;
      });
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (!mounted) {
        return;
      }
      setState(() {
        _loading = false;
        _error = e.message;
      });
    }
  }

  void _upsert(LabelItem label) {
    final next = [..._labels];
    final index = next.indexWhere((item) => item.id == label.id);
    if (index >= 0) {
      next[index] = label;
    } else {
      next.add(label);
    }
    next.sort((a, b) => a.title.toLowerCase().compareTo(b.title.toLowerCase()));
    setState(() => _labels = next);
  }

  Future<void> _create() async {
    final edited = await showLabelEditorDialog(context, title: 'Создать метку');
    if (edited == null || !mounted) {
      return;
    }
    try {
      final result = await widget.apiClient.createLabel(
        edited.name,
        description: edited.description,
      );
      if (!mounted) {
        return;
      }
      _upsert(result.label);
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(labelConflictMessage(e))),
      );
    }
  }

  Future<void> _rename(LabelItem label) async {
    final edited = await showLabelEditorDialog(
      context,
      title: 'Изменить метку',
      initialName: label.title,
      initialDescription: label.description ?? '',
      submitLabel: 'Сохранить',
    );
    if (edited == null || !mounted) {
      return;
    }
    try {
      final result = await widget.apiClient.updateLabel(
        labelId: label.id,
        name: edited.name,
        description: edited.description,
        descriptionSet: true,
      );
      if (!mounted) {
        return;
      }
      _upsert(result.label);
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(labelConflictMessage(e))),
      );
    }
  }

  Future<void> _delete(LabelItem label) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Удалить метку?'),
        content: const Text(
          'Метка будет удалена из Секретаря.\n'
          'Объекты и данные источников удалены не будут.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Удалить'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) {
      return;
    }
    try {
      await widget.apiClient.deleteLabel(label.id);
      if (!mounted) {
        return;
      }
      setState(() {
        _labels = _labels.where((item) => item.id != label.id).toList();
      });
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(e.message)),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return AccountSectionCard(
      title: 'Метки',
      children: [
        if (_loading)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 16),
            child: Center(child: CircularProgressIndicator()),
          )
        else if (_error != null)
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
              const SizedBox(height: 8),
              TextButton(onPressed: _load, child: const Text('Повторить')),
            ],
          )
        else ...[
          if (_labels.isEmpty)
            Text(
              'Нет меток',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          for (final label in _labels)
            ListTile(
              contentPadding: EdgeInsets.zero,
              dense: true,
              title: Text(label.title),
              subtitle: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (label.description != null && label.description!.isNotEmpty)
                    Text(label.description!),
                  Text('объектов: ${label.objectCount}'),
                ],
              ),
              isThreeLine:
                  label.description != null && label.description!.isNotEmpty,
              trailing: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  IconButton(
                    tooltip: 'Переименовать',
                    icon: const Icon(Icons.edit_outlined),
                    onPressed: () => _rename(label),
                  ),
                  IconButton(
                    tooltip: 'Удалить',
                    icon: const Icon(Icons.delete_outline),
                    onPressed: () => _delete(label),
                  ),
                ],
              ),
            ),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              key: const Key('account_create_label'),
              onPressed: _create,
              icon: const Icon(Icons.add),
              label: const Text('Создать метку'),
            ),
          ),
        ],
      ],
    );
  }
}

class LabelEditorResult {
  const LabelEditorResult({required this.name, this.description});

  final String name;
  final String? description;
}

Future<String?> showLabelNameDialog(
  BuildContext context, {
  required String title,
  String initial = '',
  String submitLabel = 'Создать',
}) async {
  final result = await showLabelEditorDialog(
    context,
    title: title,
    initialName: initial,
    submitLabel: submitLabel,
    includeDescription: false,
  );
  return result?.name;
}

Future<LabelEditorResult?> showLabelEditorDialog(
  BuildContext context, {
  required String title,
  String initialName = '',
  String initialDescription = '',
  String submitLabel = 'Создать',
  bool includeDescription = true,
}) {
  return showDialog<LabelEditorResult>(
    context: context,
    builder: (context) => _LabelEditorDialog(
      title: title,
      initialName: initialName,
      initialDescription: initialDescription,
      submitLabel: submitLabel,
      includeDescription: includeDescription,
    ),
  );
}

class _LabelEditorDialog extends StatefulWidget {
  const _LabelEditorDialog({
    required this.title,
    required this.initialName,
    required this.initialDescription,
    required this.submitLabel,
    required this.includeDescription,
  });

  final String title;
  final String initialName;
  final String initialDescription;
  final String submitLabel;
  final bool includeDescription;

  @override
  State<_LabelEditorDialog> createState() => _LabelEditorDialogState();
}

class _LabelEditorDialogState extends State<_LabelEditorDialog> {
  late final TextEditingController _nameController;
  late final TextEditingController _descriptionController;

  @override
  void initState() {
    super.initState();
    _nameController = TextEditingController(text: widget.initialName);
    _descriptionController = TextEditingController(text: widget.initialDescription);
  }

  @override
  void dispose() {
    _nameController.dispose();
    _descriptionController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final trimmed = _nameController.text.trim();
    return AlertDialog(
      title: Text(widget.title),
      content: SizedBox(
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              key: const Key('label_dialog_name'),
              controller: _nameController,
              autofocus: true,
              decoration: const InputDecoration(labelText: 'Название'),
              onChanged: (_) => setState(() {}),
            ),
            if (widget.includeDescription) ...[
              const SizedBox(height: 12),
              TextField(
                key: const Key('label_dialog_description'),
                controller: _descriptionController,
                decoration: const InputDecoration(
                  labelText: 'Описание для Секретаря',
                  helperText: 'Коротко опишите, когда эту метку стоит использовать.',
                  alignLabelWithHint: true,
                ),
                minLines: 2,
                maxLines: 4,
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Отмена'),
        ),
        FilledButton(
          onPressed: trimmed.isEmpty
              ? null
              : () {
                  final description = widget.includeDescription
                      ? _descriptionController.text.trim()
                      : null;
                  Navigator.pop(
                    context,
                    LabelEditorResult(
                      name: trimmed,
                      description: (description == null || description.isEmpty)
                          ? null
                          : description,
                    ),
                  );
                },
          child: Text(widget.submitLabel),
        ),
      ],
    );
  }
}
