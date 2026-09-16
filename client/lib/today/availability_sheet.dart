import 'package:flutter/material.dart';

import '../api/api_error.dart';
import '../api/api_models.dart';
import '../api/secretary_api_client.dart';
import '../auth/auth_controller.dart';
import '../ui/date_format.dart';

const _presetStart = TimeOfDay(hour: 9, minute: 0);
const _presetEnd = TimeOfDay(hour: 18, minute: 0);
const _presetMinMinutes = 30;
const _minDurationChoices = [15, 30, 45, 60, 90, 120];

DateTime availabilityInitialSearchDate(WeekOut week) {
  final weekStart = parseCalendarDate(week.weekStart);
  final weekEnd = parseCalendarDate(week.weekEnd);
  if (week.isCurrentWeek) {
    final today = parseCalendarDate(week.todayDate);
    if (!today.isBefore(weekStart) && today.isBefore(weekEnd)) {
      return DateTime(today.year, today.month, today.day);
    }
  }
  return DateTime(weekStart.year, weekStart.month, weekStart.day);
}

Future<void> showAvailabilitySheet({
  required BuildContext context,
  required SecretaryApiClient apiClient,
  required AuthController authController,
  required WeekOut week,
}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (context) {
      return AvailabilitySheet(
        apiClient: apiClient,
        authController: authController,
        week: week,
      );
    },
  );
}

class AvailabilitySheet extends StatefulWidget {
  const AvailabilitySheet({
    super.key,
    required this.apiClient,
    required this.authController,
    required this.week,
  });

  final SecretaryApiClient apiClient;
  final AuthController authController;
  final WeekOut week;

  @override
  State<AvailabilitySheet> createState() => _AvailabilitySheetState();
}

class _AvailabilitySheetState extends State<AvailabilitySheet> {
  late DateTime _date;
  TimeOfDay _start = _presetStart;
  TimeOfDay _end = _presetEnd;
  int _minDurationMinutes = _presetMinMinutes;
  var _loading = false;
  String? _error;
  AvailabilityOut? _result;

  @override
  void initState() {
    super.initState();
    _date = availabilityInitialSearchDate(widget.week);
  }

  DateTime get _startLocal =>
      DateTime(_date.year, _date.month, _date.day, _start.hour, _start.minute);

  DateTime get _endLocal =>
      DateTime(_date.year, _date.month, _date.day, _end.hour, _end.minute);

  Future<void> _pickDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _date,
      firstDate: DateTime(2000),
      lastDate: DateTime(2100),
    );
    if (picked == null || !mounted) {
      return;
    }
    setState(() {
      _date = DateTime(picked.year, picked.month, picked.day);
      _result = null;
      _error = null;
    });
  }

  Future<void> _pickTime({required bool start}) async {
    final picked = await showTimePicker(
      context: context,
      initialTime: start ? _start : _end,
      initialEntryMode: TimePickerEntryMode.input,
      builder: (context, child) {
        return MediaQuery(
          data: MediaQuery.of(context).copyWith(alwaysUse24HourFormat: true),
          child: child ?? const SizedBox.shrink(),
        );
      },
    );
    if (picked == null || !mounted) {
      return;
    }
    setState(() {
      if (start) {
        _start = picked;
      } else {
        _end = picked;
      }
      _result = null;
      _error = null;
    });
  }

  Future<void> _search() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final snapshot = await widget.apiClient.getAvailability(
        startAt: _startLocal,
        endAt: _endLocal,
        minDurationMinutes: _minDurationMinutes,
      );
      if (!mounted) {
        return;
      }
      setState(() {
        _result = snapshot;
        _loading = false;
      });
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
      if (mounted) {
        Navigator.of(context).pop();
      }
    } on ApiException catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _loading = false;
        _error = error.message;
        _result = null;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.fromLTRB(
          16,
          0,
          16,
          16 + MediaQuery.viewInsetsOf(context).bottom,
        ),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('Свободное время', style: theme.textTheme.titleMedium),
              const SizedBox(height: 8),
              ListTile(
                key: const Key('availability_date'),
                contentPadding: EdgeInsets.zero,
                dense: true,
                title: const Text('Дата'),
                subtitle: Text(formatRussianNumericDate(_date)),
                trailing: const Icon(Icons.event_outlined),
                onTap: _pickDate,
              ),
              ListTile(
                key: const Key('availability_start'),
                contentPadding: EdgeInsets.zero,
                dense: true,
                title: const Text('Начало'),
                subtitle: Text(formatRussianClockTime(_startLocal)),
                trailing: const Icon(Icons.schedule_outlined),
                onTap: () => _pickTime(start: true),
              ),
              ListTile(
                key: const Key('availability_end'),
                contentPadding: EdgeInsets.zero,
                dense: true,
                title: const Text('Конец'),
                subtitle: Text(formatRussianClockTime(_endLocal)),
                trailing: const Icon(Icons.schedule_outlined),
                onTap: () => _pickTime(start: false),
              ),
              ListTile(
                contentPadding: EdgeInsets.zero,
                dense: true,
                title: const Text('Мин. длительность'),
                trailing: DropdownButton<int>(
                  key: const Key('availability_min_duration'),
                  value: _minDurationMinutes,
                  onChanged: (value) {
                    if (value == null) {
                      return;
                    }
                    setState(() {
                      _minDurationMinutes = value;
                      _result = null;
                      _error = null;
                    });
                  },
                  items: [
                    for (final minutes in _minDurationChoices)
                      DropdownMenuItem(
                        value: minutes,
                        child: Text(formatDurationMinutes(minutes)),
                      ),
                  ],
                ),
              ),
              Align(
                alignment: Alignment.centerLeft,
                child: FilledButton(
                  key: const Key('availability_search'),
                  onPressed: _loading ? null : _search,
                  child: _loading
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Text('Найти'),
                ),
              ),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(_error!, style: theme.textTheme.bodyMedium),
              ],
              if (_result != null) ...[
                const SizedBox(height: 12),
                _AvailabilityResult(result: _result!),
              ],
              const SizedBox(height: 12),
              Text(
                key: const Key('availability_soft_note'),
                'Запланированные задачи и возможные времена не блокируют доступность.',
                style: theme.textTheme.bodySmall,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _AvailabilityResult extends StatelessWidget {
  const _AvailabilityResult({required this.result});

  final AvailabilityOut result;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    if (!result.availabilityComplete) {
      return Text(
        key: const Key('availability_incomplete'),
        'Не удалось надёжно определить свободное время: у календарного события не указано время окончания.',
        style: theme.textTheme.bodyMedium,
      );
    }
    if (result.freeIntervals.isEmpty) {
      return Text(
        key: const Key('availability_empty'),
        'Свободных окон заданной длительности нет',
        style: theme.textTheme.bodyMedium,
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final interval in result.freeIntervals)
          Padding(
            key: Key('availability_free_interval_${interval.startAt}'),
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Text(
              '${formatUserTime(interval.startAt)}–${formatUserTime(interval.endAt)}   ${formatDurationMinutes(interval.durationMinutes)}',
              style: theme.textTheme.bodyLarge,
            ),
          ),
      ],
    );
  }
}
