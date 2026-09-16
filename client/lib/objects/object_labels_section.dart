import 'package:flutter/material.dart';

import '../account/account_labels_section.dart';
import '../api/api_error.dart';
import '../api/api_models.dart';
import '../api/secretary_api_client.dart';
import '../auth/auth_controller.dart';

class ObjectLabelsSection extends StatefulWidget {
  const ObjectLabelsSection({
    super.key,
    required this.objectId,
    required this.apiClient,
    required this.authController,
    this.allowAssignment = true,
  });

  final String objectId;
  final SecretaryApiClient apiClient;
  final AuthController authController;
  final bool allowAssignment;

  @override
  State<ObjectLabelsSection> createState() => _ObjectLabelsSectionState();
}

class _ObjectLabelsSectionState extends State<ObjectLabelsSection> {
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
      final result = await widget.apiClient.getObjectLabels(widget.objectId);
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

  Future<void> _remove(LabelItem label) async {
    final previous = List<LabelItem>.from(_labels);
    try {
      await widget.apiClient.removeObjectLabel(
        objectId: widget.objectId,
        labelId: label.id,
      );
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
      setState(() => _labels = previous);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  Future<void> _assign(LabelItem label) async {
    final previous = List<LabelItem>.from(_labels);
    try {
      await widget.apiClient.assignLabel(
        objectId: widget.objectId,
        labelId: label.id,
      );
      if (!mounted) {
        return;
      }
      if (_labels.any((item) => item.id == label.id)) {
        return;
      }
      setState(() => _labels = [..._labels, label]);
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (!mounted) {
        return;
      }
      setState(() => _labels = previous);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  Future<void> _openPicker() async {
    LabelList catalog;
    try {
      catalog = await widget.apiClient.listLabels();
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
      return;
    } on ApiException catch (e) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
      return;
    }
    if (!mounted) {
      return;
    }
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (context) {
        final assigned = {for (final item in _labels) item.id};
        return SafeArea(
          child: ListView(
            shrinkWrap: true,
            children: [
              ListTile(
                leading: const Icon(Icons.add),
                title: const Text('Создать новую метку'),
                onTap: () async {
                  Navigator.pop(context);
                  await _createAndAssign();
                },
              ),
              for (final label in catalog.labels)
                ListTile(
                  title: Text(label.title),
                  selected: assigned.contains(label.id),
                  enabled: !assigned.contains(label.id),
                  onTap: assigned.contains(label.id)
                      ? null
                      : () {
                          Navigator.pop(context);
                          _assign(label);
                        },
                ),
            ],
          ),
        );
      },
    );
  }

  Future<void> _createAndAssign() async {
    final name = await showLabelNameDialog(context, title: 'Создать метку');
    if (name == null || !mounted) {
      return;
    }
    final previous = List<LabelItem>.from(_labels);
    try {
      final created = await widget.apiClient.createLabel(name);
      await widget.apiClient.assignLabel(
        objectId: widget.objectId,
        labelId: created.label.id,
      );
      if (!mounted) {
        return;
      }
      if (_labels.any((item) => item.id == created.label.id)) {
        return;
      }
      setState(() => _labels = [..._labels, created.label]);
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (!mounted) {
        return;
      }
      setState(() => _labels = previous);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(labelConflictMessage(e))),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Метки', style: Theme.of(context).textTheme.titleMedium),
        if (_loading)
          const Padding(
            padding: EdgeInsets.only(top: 8),
            child: LinearProgressIndicator(),
          )
        else if (_error != null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              _error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          )
        else if (_labels.isEmpty)
          const Padding(
            padding: EdgeInsets.only(top: 8),
            child: Text('Нет меток'),
          )
        else
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final label in _labels)
                  InputChip(
                    key: Key('object_label_chip_${label.id}'),
                    label: Text(label.title),
                    deleteIcon: widget.allowAssignment
                        ? Icon(
                            Icons.close,
                            key: Key('object_label_remove_${label.id}'),
                          )
                        : null,
                    onDeleted: widget.allowAssignment ? () => _remove(label) : null,
                  ),
              ],
            ),
          ),
        if (widget.allowAssignment)
          TextButton.icon(
            key: const Key('object_add_label'),
            onPressed: _openPicker,
            icon: const Icon(Icons.add),
            label: const Text('+ Добавить'),
          ),
      ],
    );
  }
}
