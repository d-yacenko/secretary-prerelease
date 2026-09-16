import '../api/api_models.dart';

enum TodayEventEmphasis { none, soon, current }

const Duration kTodaySoonWindow = Duration(minutes: 60);

DateTime? _parse(String? iso) {
  if (iso == null || iso.trim().isEmpty) {
    return null;
  }
  return DateTime.tryParse(iso)?.toLocal();
}

bool _isEventKind(SecretaryObject object) {
  return object.kind == 'event' || object.kind == 'calendar_event';
}

/// Presentation-only classification. Does not invent duration.
/// An event without a known end is never "current".
TodayEventEmphasis todayEventEmphasis(
  SecretaryObject event, {
  required DateTime now,
}) {
  if (!_isEventKind(event)) {
    return TodayEventEmphasis.none;
  }
  final start = _parse(event.startAt);
  if (start == null) {
    return TodayEventEmphasis.none;
  }
  final localNow = now.toLocal();
  final end = _parse(event.dueAt);
  if (end != null && !end.isBefore(start) && !start.isAfter(localNow) && localNow.isBefore(end)) {
    return TodayEventEmphasis.current;
  }
  if (start.isAfter(localNow) && start.difference(localNow) <= kTodaySoonWindow) {
    return TodayEventEmphasis.soon;
  }
  return TodayEventEmphasis.none;
}
