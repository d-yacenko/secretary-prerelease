import 'package:flutter/material.dart';

import '../ui/date_format.dart';

class TaskCompletionModeSelector extends StatelessWidget {
  const TaskCompletionModeSelector({
    super.key,
    required this.mode,
    required this.onChanged,
    this.enabled = true,
    this.selectorKey = const Key('task_completion_mode'),
  });

  final String mode;
  final ValueChanged<String>? onChanged;
  final bool enabled;
  final Key selectorKey;

  @override
  Widget build(BuildContext context) {
    return SegmentedButton<String>(
      key: selectorKey,
      segments: const [
        ButtonSegment(value: 'finite', label: Text('Задача')),
        ButtonSegment(value: 'ongoing', label: Text('Направление')),
      ],
      selected: {mode},
      onSelectionChanged: !enabled || onChanged == null
          ? null
          : (selection) => onChanged!(selection.first),
    );
  }
}

class TaskDueDateField extends StatelessWidget {
  const TaskDueDateField({
    super.key,
    required this.dueAt,
    required this.onChanged,
    this.enabled = true,
  });

  final DateTime? dueAt;
  final ValueChanged<DateTime?> onChanged;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      title: Text(
        dueAt == null ? 'Без срока' : formatUserDateTimeFromDateTime(dueAt),
      ),
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          IconButton(
            tooltip: 'Установить срок',
            onPressed: enabled ? () => _pick(context) : null,
            icon: const Icon(Icons.event_outlined),
          ),
          IconButton(
            tooltip: 'Очистить срок',
            onPressed: enabled && dueAt != null ? () => onChanged(null) : null,
            icon: const Icon(Icons.event_busy_outlined),
          ),
        ],
      ),
    );
  }

  Future<void> _pick(BuildContext context) async {
    final pickedDate = await showDatePicker(
      context: context,
      initialDate: dueAt?.toLocal() ?? DateTime.now(),
      firstDate: DateTime(2000),
      lastDate: DateTime(2100),
    );
    if (pickedDate == null || !context.mounted) {
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
    onChanged(
      DateTime(
        pickedDate.year,
        pickedDate.month,
        pickedDate.day,
        pickedTime.hour,
        pickedTime.minute,
      ),
    );
  }
}

class TaskPlannedIntervalField extends StatelessWidget {
  const TaskPlannedIntervalField({
    super.key,
    required this.plannedStart,
    required this.plannedEnd,
    required this.onChanged,
    this.enabled = true,
  });

  final DateTime? plannedStart;
  final DateTime? plannedEnd;
  final void Function(DateTime? start, DateTime? end) onChanged;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final hasInterval = plannedStart != null && plannedEnd != null;
    return ListTile(
      key: const Key('task_planned_interval'),
      contentPadding: EdgeInsets.zero,
      title: const Text('Запланированное время'),
      subtitle: Text(
        hasInterval
            ? formatPlannedExecutionInterval(
                start: plannedStart!,
                end: plannedEnd!,
              )
            : 'Не задано',
      ),
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          IconButton(
            key: const Key('task_planned_interval_set'),
            tooltip: 'Установить запланированное время',
            onPressed: enabled ? () => _pick(context) : null,
            icon: const Icon(Icons.schedule_outlined),
          ),
          IconButton(
            key: const Key('task_planned_interval_clear'),
            tooltip: 'Очистить запланированное время',
            onPressed: enabled && hasInterval
                ? () => onChanged(null, null)
                : null,
            icon: const Icon(Icons.timer_off_outlined),
          ),
        ],
      ),
    );
  }

  Future<void> _pick(BuildContext context) async {
    final initialStart = plannedStart?.toLocal() ?? DateTime.now();
    final pickedDate = await showDatePicker(
      context: context,
      initialDate: initialStart,
      firstDate: DateTime(2000),
      lastDate: DateTime(2100),
    );
    if (pickedDate == null || !context.mounted) {
      return;
    }
    final pickedStart = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(initialStart),
    );
    if (pickedStart == null || !context.mounted) {
      return;
    }
    final initialEnd =
        plannedEnd?.toLocal() ??
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
    onChanged(start, end);
  }
}
