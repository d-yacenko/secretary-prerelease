import '../ui/date_format.dart';

/// Day-local trailing time for a Week agenda row.
///
/// Uses the backend-projected civil [dayDate] (`YYYY-MM-DD`) and the event's
/// local start/end instants. Never presents a previous-day start as if it
/// belonged to the displayed day.
String weekEventTimeLabel({
  required String dayDate,
  required bool allDay,
  String? startAt,
  String? dueAt,
}) {
  if (allDay) {
    return 'Весь день';
  }
  final start = DateTime.tryParse(startAt ?? '');
  if (start == null) {
    return '';
  }
  final startLocal = start.toLocal();
  final dayCivil = parseCalendarDate(dayDate);
  final dayStart = DateTime(dayCivil.year, dayCivil.month, dayCivil.day);
  final nextCivil = addCalendarDays(dayCivil, 1);
  final dayEnd = DateTime(nextCivil.year, nextCivil.month, nextCivil.day);

  final startsOnDay =
      !startLocal.isBefore(dayStart) && startLocal.isBefore(dayEnd);
  final startsBefore = startLocal.isBefore(dayStart);

  final end = DateTime.tryParse(dueAt ?? '');
  if (end == null) {
    return formatRussianClockTime(startLocal);
  }
  final endLocal = end.toLocal();
  final endsOnDay = endLocal.isAfter(dayStart) && !endLocal.isAfter(dayEnd);
  final continuesAfter = endLocal.isAfter(dayEnd);

  if (startsOnDay && continuesAfter) {
    return 'с ${formatRussianClockTime(startLocal)}';
  }
  if (startsBefore && continuesAfter) {
    return 'Продолжается';
  }
  if (startsBefore && endsOnDay) {
    return 'до ${formatRussianClockTime(endLocal)}';
  }
  if (startsOnDay) {
    return formatRussianClockTime(startLocal);
  }
  if (endsOnDay) {
    return 'до ${formatRussianClockTime(endLocal)}';
  }
  return 'Продолжается';
}