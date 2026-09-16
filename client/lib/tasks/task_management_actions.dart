import 'package:flutter/material.dart';

import '../api/api_error.dart';
import '../api/api_models.dart';
import '../api/secretary_api_client.dart';
import '../auth/auth_controller.dart';
import '../ui/date_format.dart';
import '../ui/domain_labels.dart';

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
    DateTime? dueAt = task.dueAt == null ? null : DateTime.tryParse(task.dueAt!);
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
                      onChanged: (value) => setState(() => clearBody = value ?? false),
                    ),
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      title: Text(
                        dueAt == null
                            ? 'Без срока'
                            : formatUserDateTimeFromDateTime(dueAt),
                      ),
                      trailing: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          IconButton(
                            tooltip: 'Установить срок',
                            onPressed: () async {
                              final pickedDate = await showDatePicker(
                                context: context,
                                initialDate: dueAt?.toLocal() ?? DateTime.now(),
                                firstDate: DateTime(2000),
                                lastDate: DateTime(2100),
                              );
                              if (pickedDate == null) {
                                return;
                              }
                              final pickedTime = await showTimePicker(
                                context: context,
                                initialTime: dueAt != null
                                    ? TimeOfDay.fromDateTime(dueAt!.toLocal())
                                    : TimeOfDay.now(),
                              );
                              if (pickedTime == null) {
                                return;
                              }
                              setState(() {
                                dueAt = DateTime(
                                  pickedDate.year,
                                  pickedDate.month,
                                  pickedDate.day,
                                  pickedTime.hour,
                                  pickedTime.minute,
                                );
                                clearDue = false;
                                dueAtChanged = true;
                              });
                            },
                            icon: const Icon(Icons.event_outlined),
                          ),
                          IconButton(
                            tooltip: 'Очистить срок',
                            onPressed: () => setState(() {
                              clearDue = true;
                              dueAt = null;
                              dueAtChanged = true;
                            }),
                            icon: const Icon(Icons.event_busy_outlined),
                          ),
                        ],
                      ),
                    ),
                    ListTile(
                      key: const Key('task_planned_interval'),
                      contentPadding: EdgeInsets.zero,
                      title: const Text('Запланированное время'),
                      subtitle: Text(
                        plannedStart == null || plannedEnd == null
                            ? 'Не задано'
                            : formatPlannedExecutionInterval(
                                start: plannedStart!,
                                end: plannedEnd!,
                              ),
                      ),
                      trailing: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          IconButton(
                            key: const Key('task_planned_interval_set'),
                            tooltip: 'Установить запланированное время',
                            onPressed: () async {
                              final initialStart =
                                  plannedStart?.toLocal() ?? DateTime.now();
                              final pickedDate = await showDatePicker(
                                context: context,
                                initialDate: initialStart,
                                firstDate: DateTime(2000),
                                lastDate: DateTime(2100),
                              );
                              if (pickedDate == null) {
                                return;
                              }
                              if (!context.mounted) {
                                return;
                              }
                              final pickedStart = await showTimePicker(
                                context: context,
                                initialTime: TimeOfDay.fromDateTime(initialStart),
                              );
                              if (pickedStart == null) {
                                return;
                              }
                              if (!context.mounted) {
                                return;
                              }
                              final initialEnd = plannedEnd?.toLocal() ??
                                  DateTime(
                                    pickedDate.year,
                                    pickedDate.month,
                                    pickedDate.day,
                                    pickedStart.hour,
                                    pickedStart.minute,
                                  ).add(const Duration(hours: 1));
                              final pickedEnd = await showTimePicker(
                                context: context,
                                initialTime: TimeOfDay.fromDateTime(initialEnd),
                              );
                              if (pickedEnd == null) {
                                return;
                              }
                              final start = DateTime(
                                pickedDate.year,
                                pickedDate.month,
                                pickedDate.day,
                                pickedStart.hour,
                                pickedStart.minute,
                              );
                              var end = DateTime(
                                pickedDate.year,
                                pickedDate.month,
                                pickedDate.day,
                                pickedEnd.hour,
                                pickedEnd.minute,
                              );
                              if (!end.isAfter(start)) {
                                end = end.add(const Duration(days: 1));
                              }
                              setState(() {
                                plannedStart = start;
                                plannedEnd = end;
                                plannedChanged = true;
                              });
                            },
                            icon: const Icon(Icons.schedule_outlined),
                          ),
                          IconButton(
                            key: const Key('task_planned_interval_clear'),
                            tooltip: 'Очистить запланированное время',
                            onPressed: () => setState(() {
                              plannedStart = null;
                              plannedEnd = null;
                              plannedChanged = true;
                            }),
                            icon: const Icon(Icons.timer_off_outlined),
                          ),
                        ],
                      ),
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
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Задача обновлена')),
        );
      }
    } on AuthenticationException {
      authController.handleAuthenticationFailure();
    } on ApiException catch (error) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(error.message)),
        );
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
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(error.message)),
        );
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
    switch (status) {
      case 'open':
      case null:
        return ['in_progress', 'done', 'cancelled', 'archived'];
      case 'in_progress':
        return ['open', 'done', 'cancelled', 'archived'];
      case 'done':
      case 'cancelled':
      case 'archived':
      case 'completed':
        return ['open'];
      default:
        return ['open', 'in_progress', 'done', 'cancelled', 'archived'];
    }
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
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(error.message)),
      );
    }
  }
}
