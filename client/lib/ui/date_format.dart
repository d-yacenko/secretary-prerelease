String formatUserDateTime(String? iso) {
  if (iso == null || iso.trim().isEmpty) {
    return '';
  }
  final parsed = DateTime.tryParse(iso);
  if (parsed == null) {
    return iso;
  }
  final local = parsed.toLocal();
  final day = local.day.toString().padLeft(2, '0');
  final month = local.month.toString().padLeft(2, '0');
  final year = local.year.toString();
  final hour = local.hour.toString().padLeft(2, '0');
  final minute = local.minute.toString().padLeft(2, '0');
  return '$day.$month.$year, $hour:$minute';
}

String formatUserDateTimeFromDateTime(DateTime? value) {
  if (value == null) {
    return '';
  }
  return formatUserDateTime(value.toUtc().toIso8601String());
}

String formatUserTime(String? iso) {
  if (iso == null || iso.trim().isEmpty) {
    return '';
  }
  final parsed = DateTime.tryParse(iso);
  if (parsed == null) {
    return iso;
  }
  final local = parsed.toLocal();
  final hour = local.hour.toString().padLeft(2, '0');
  final minute = local.minute.toString().padLeft(2, '0');
  return '$hour:$minute';
}

String formatPlannedExecutionInterval({
  required DateTime start,
  required DateTime end,
}) {
  final startLocal = start.toLocal();
  final endLocal = end.toLocal();
  final startText = formatUserDateTimeFromDateTime(start);
  if (startLocal.year == endLocal.year &&
      startLocal.month == endLocal.month &&
      startLocal.day == endLocal.day) {
    return '$startText – ${formatRussianClockTime(endLocal)}';
  }
  return '$startText – ${formatUserDateTimeFromDateTime(end)}';
}

const _monthGenitive = [
  'января',
  'февраля',
  'марта',
  'апреля',
  'мая',
  'июня',
  'июля',
  'августа',
  'сентября',
  'октября',
  'ноября',
  'декабря',
];

const _weekdays = [
  'понедельник',
  'вторник',
  'среда',
  'четверг',
  'пятница',
  'суббота',
  'воскресенье',
];

String formatRussianNumericDate(DateTime local, {bool twoDigitYear = true}) {
  final day = local.day.toString().padLeft(2, '0');
  final month = local.month.toString().padLeft(2, '0');
  if (twoDigitYear) {
    final year = (local.year % 100).toString().padLeft(2, '0');
    return '$day.$month.$year';
  }
  return '$day.$month.${local.year}';
}

String formatRussianClockTime(DateTime local) {
  final hour = local.hour.toString().padLeft(2, '0');
  final minute = local.minute.toString().padLeft(2, '0');
  return '$hour:$minute';
}

String formatRussianDayMonth(DateTime local, {bool padDay = false}) {
  final day = padDay ? local.day.toString().padLeft(2, '0') : '${local.day}';
  return '$day ${_monthGenitive[local.month - 1]}';
}

String formatRussianWeekday(DateTime local) => _weekdays[local.weekday - 1];

const _weekdaysShort = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

String formatRussianWeekdayShort(DateTime local) =>
    _weekdaysShort[local.weekday - 1];

DateTime parseCalendarDate(String value) {
  final match = RegExp(r'^(\d{4})-(\d{2})-(\d{2})$').firstMatch(value.trim());
  if (match == null) {
    throw FormatException('invalid calendar date: $value');
  }
  return DateTime.utc(
    int.parse(match.group(1)!),
    int.parse(match.group(2)!),
    int.parse(match.group(3)!),
  );
}

DateTime addCalendarDays(DateTime date, int days) {
  return DateTime.utc(date.year, date.month, date.day + days);
}

String shiftCalendarDate(String value, int days) {
  return formatCalendarDate(addCalendarDays(parseCalendarDate(value), days));
}

String formatCalendarDate(DateTime value) {
  final year = value.year.toString().padLeft(4, '0');
  final month = value.month.toString().padLeft(2, '0');
  final day = value.day.toString().padLeft(2, '0');
  return '$year-$month-$day';
}

String formatDurationMinutes(int minutes) {
  final safe = minutes < 0 ? 0 : minutes;
  final hours = safe ~/ 60;
  final rest = safe % 60;
  if (hours > 0 && rest > 0) {
    return '$hours ч $rest мин';
  }
  if (hours > 0) {
    return '$hours ч';
  }
  return '$rest мин';
}

String formatWeekRange(String weekStartIso) {
  final start = parseCalendarDate(weekStartIso);
  final end = addCalendarDays(start, 6);
  if (start.year == end.year && start.month == end.month) {
    return '${start.day}–${formatRussianDayMonth(end)}';
  }
  if (start.year == end.year) {
    return '${formatRussianDayMonth(start)} – ${formatRussianDayMonth(end)}';
  }
  return '${formatRussianDayMonth(start)} ${start.year} – ${formatRussianDayMonth(end)} ${end.year}';
}

