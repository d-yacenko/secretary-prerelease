import 'package:flutter/material.dart';

import '../api/api_error.dart';
import '../api/api_models.dart';
import '../api/secretary_api_client.dart';
import '../auth/auth_controller.dart';
import '../ui/domain_labels.dart';
import 'task_form_fields.dart';

class TaskManagementActions extends StatelessWidget {
  const TaskManagementActions({
    super.key,
    required this.task,
    required this.apiClient,
    required this.authController,
    required this.onTaskUpdated,
    this.compact = false,
  });

  final SecretaryObject task;
  final SecretaryApiClient apiClient;
  final AuthController authController;
  final ValueChanged<SecretaryObject> onTaskUpdated;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    if (task.kind != 'task' || task.isDeletedTask) {
      return const SizedBox.shrink();
    }

    final children = <Widget>[
      _actionButton(
        context,
        tooltip: 'Редактировать задачу',
        icon: Icons.edit_outlined,
        label: 'Редактировать',
        onPressed: () => _editTask(context),
      ),
      _actionButton(
        context,
        tooltip: 'Изменить статус',
        icon: Icons.swap_horiz,
        label: 'Статус',
        onPressed: () => _changeStatus(context),
      ),
    ];

    if (compact) {
      return PopupMenuButton<String>(
        tooltip: 'Действия с задачей',
        itemBuilder: (context) => [
          const PopupMenuItem(value: 'edit', child: Text('Редактировать')),
          const PopupMenuItem(value: 'status', child: Text('Изменить статус')),
        ],
        onSelected: (value) {
          switch (value) {
            case 'edit':
              _editTask(context);
            case 'status':
              _changeStatus(context);
          }
        },
      );
    }

    return Wrap(spacing: 8, runSpacing: 8, children: children);
  }

  Widget _actionButton(
    BuildContext context, {
    required String tooltip,
    required IconData icon,
    required String label,
    required VoidCallback onPressed,
  }) {
    return Tooltip(
      message: tooltip,
      child: OutlinedButton.icon(
        onPressed: onPressed,
        icon: Icon(icon, size: 18),
        label: Text(label),
      ),
    );
  }

  Future<void> _editTask(BuildContext context) async {
    final titleController = TextEditingController(text: task.title);
    final bodyController = TextEditingController(text: task.body ?? '');
    DateTime? dueAt = task.dueAt == null
        ? null
        : DateTime.tryParse(task.dueAt!);
    final originalDueAt = dueAt;
    DateTime? plannedStart = task.plannedStartAt == null
        ? null
        : DateTime.tryParse(task.plannedStartAt!);
    DateTime? plannedEnd = task.plannedEndAt == null
        ? null
        : DateTime.tryParse(task.plannedEndAt!);
    final originalPlannedStart = plannedStart;
    final originalPlannedEnd = plannedEnd;
    bool clearBody = false;
    bool clearDue = false;
    bool dueAtChanged = false;
    bool plannedChanged = false;
    var completionMode = task.effectiveCompletionMode ?? 'finite';

    final saved = await showDialog<bool>(
      context: context,
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setState) {
            return AlertDialog(
              title: const Text('Редактировать задачу'),
              content: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    TaskCompletionModeSelector(
                      mode: completionMode,
                      onChanged: (value) =>
                          setState(() => completionMode = value),
                    ),
                    TextField(
                      controller: titleController,
                      decoration: const InputDecoration(labelText: 'Название'),
                    ),
                    TextField(
                      controller: bodyController,
                      decoration: const InputDecoration(labelText: 'Описание'),
                      minLines: 2,
                      maxLines: 4,
                      enabled: !clearBody,
                    ),
                    CheckboxListTile(
                      contentPadding: EdgeInsets.zero,
                      title: const Text('Очистить описание'),
                      value: clearBody,
                      onChanged: (value) =>
                          setState(() => clearBody = value ?? false),
                    ),
                    TaskDueDateField(
                      dueAt: dueAt,
                      onChanged: (value) => setState(() {
                        dueAt = value;
                        clearDue = value == null;
                        dueAtChanged = true;
                      }),
                    ),
                    TaskPlannedIntervalField(
                      plannedStart: plannedStart,
                      plannedEnd: plannedEnd,
                      onChanged: (start, end) => setState(() {
                        plannedStart = start;
                        plannedEnd = end;
                        plannedChanged = true;
                      }),
                    ),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context, false),
                  child: const Text('Отмена'),
                ),
                FilledButton(
                  onPressed: () => Navigator.pop(context, true),
                  child: const Text('Сохранить'),
                ),
              ],
            );
          },
        );
      },
    );

    if (saved != true) {
      return;
    }

    final request = TaskPatchRequest();
    if (titleController.text.trim() != task.title) {
      request.title = titleController.text.trim();
      request.titleSet = true;
    }
    if (clearBody) {
      request.body = null;
      request.bodySet = true;
    } else if (bodyController.text != (task.body ?? '')) {
      request.body = bodyController.text;
      request.bodySet = true;
    }
    if (completionMode != (task.effectiveCompletionMode ?? 'finite')) {
      request.completionMode = completionMode;
      request.completionModeSet = true;
    }
    if (clearDue) {
      request.dueAt = null;
      request.dueAtSet = true;
    } else if (dueAtChanged && dueAt != null) {
      final newDueIso = dueAt!.toUtc().toIso8601String();
      final oldDueIso = originalDueAt?.toUtc().toIso8601String();
      if (newDueIso != oldDueIso) {
        request.dueAt = newDueIso;
        request.dueAtSet = true;
      }
    }

    var plannedPayload = <String, dynamic>{};
    if (plannedChanged) {
      final newStartIso = plannedStart?.toUtc().toIso8601String();
      final newEndIso = plannedEnd?.toUtc().toIso8601String();
      final oldStartIso = originalPlannedStart?.toUtc().toIso8601String();
      final oldEndIso = originalPlannedEnd?.toUtc().toIso8601String();
      if (newStartIso != oldStartIso || newEndIso != oldEndIso) {
        plannedPayload = {
          'planned_start_at': newStartIso,
          'planned_end_at': newEndIso,
        };
      }
    }

    if (request.isEmpty && plannedPayload.isEmpty) {
      return;
    }

    final requestedMode = request.completionModeSet
        ? request.completionMode
        : null;
    try {
      SecretaryObject updated = task;
      if (!request.isEmpty) {
        final response = await apiClient.patchTask(task.id, request);
        updated = response.object;
      }
      if (plannedPayload.isNotEmpty) {
        updated = await apiClient.patchObject(task.id, plannedPayload);
      }
      onTaskUpdated(updated);
      if (!context.mounted) {
        return;
      }
      if (requestedMode != null &&
          updated.effectiveCompletionMode != requestedMode) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Изменение режима не сохранилось')),
        );
        return;
      }
      final message =
          requestedMode == 'ongoing' ||
              (requestedMode == null && updated.isOngoingTask)
          ? (requestedMode == null
                ? 'Направление обновлено'
                : 'Направление сохранено')
          : (requestedMode == 'finite'
                ? 'Задача сохранена'
                : 'Задача обновлена');
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(message)));
    } on AuthenticationException {
      authController.handleAuthenticationFailure();
    } on ApiException catch (error) {
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(error.message)));
      }
    }
  }

  Future<void> _changeStatus(BuildContext context) async {
    final options = _statusOptionsFor(task.status);
    final selected = await showDialog<String>(
      context: context,
      builder: (context) => SimpleDialog(
        title: const Text('Изменить статус'),
        children: options
            .map(
              (status) => SimpleDialogOption(
                onPressed: () => Navigator.pop(context, status),
                child: Text(taskStatusLabel(status)),
              ),
            )
            .toList(),
      ),
    );
    if (selected == null) {
      return;
    }
    try {
      final response = await apiClient.setTaskStatus(task.id, selected);
      onTaskUpdated(response.object);
    } on AuthenticationException {
      authController.handleAuthenticationFailure();
    } on ApiException catch (error) {
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(error.message)));
      }
    }
  }

  Future<void> _deleteTask(BuildContext context) async {
    await confirmAndDeleteTask(
      context,
      task: task,
      apiClient: apiClient,
      authController: authController,
      onTaskUpdated: onTaskUpdated,
    );
  }

  List<String> _statusOptionsFor(String? status) {
    final List<String> options;
    switch (status) {
      case 'open':
      case null:
        options = ['in_progress', 'done', 'cancelled', 'archived'];
      case 'in_progress':
        options = ['open', 'done', 'cancelled', 'archived'];
      case 'done':
      case 'cancelled':
      case 'archived':
      case 'completed':
        options = ['open'];
      default:
        options = ['open', 'in_progress', 'done', 'cancelled', 'archived'];
    }
    if (!task.isOngoingTask) {
      return options;
    }
    return options.where((item) => item != 'done').toList();
  }
}

Future<void> confirmAndDeleteTask(
  BuildContext context, {
  required SecretaryObject task,
  required SecretaryApiClient apiClient,
  required AuthController authController,
  required ValueChanged<SecretaryObject> onTaskUpdated,
}) async {
  final confirmed = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      title: const Text('Удалить задачу?'),
      content: Text(
        '${task.title}\n\nЗадача будет скрыта из обычного поиска и активных представлений. '
        'История в графе и связи сохранятся.',
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
  if (confirmed != true) {
    return;
  }
  try {
    final response = await apiClient.softDeleteTask(task.id);
    onTaskUpdated(response.object);
  } on AuthenticationException {
    authController.handleAuthenticationFailure();
  } on ApiException catch (error) {
    if (context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error.message)));
    }
  }
}
