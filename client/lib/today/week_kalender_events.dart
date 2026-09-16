import 'package:flutter/material.dart';
import 'package:kalender/kalender.dart';

import '../api/api_models.dart';
import 'week_item_type.dart';

/// Layout-only extent for an exact-start hint whose end is unknown.
///
/// Not busy time. Not persisted. Not a factual `due_at`.
const Duration kWeekUnknownEndVisualDuration = Duration(minutes: 30);

/// Calendar event bound to a Secretary Object.id.
class SecretaryWeekEvent extends CalendarEvent {
  SecretaryWeekEvent({
    required String objectId,
    required super.dateTimeRange,
    required this.title,
    this.provider,
    this.itemType = WeekTemporalItemType.calendarCommitment,
    this.endUnknown = false,
    this.status,
    super.isAllDay = false,
  }) : super(id: objectId, interaction: EventInteraction.allowNone());

  final String title;
  final String? provider;
  final WeekTemporalItemType itemType;
  final bool endUnknown;
  final String? status;

  String get objectId => id;

  bool get completed => status == 'done' || status == 'completed';

  @override
  SecretaryWeekEvent copyWithData({required DateTimeRange dateTimeRange}) {
    return SecretaryWeekEvent(
      objectId: id,
      dateTimeRange: dateTimeRange,
      title: title,
      provider: provider,
      itemType: itemType,
      endUnknown: endUnknown,
      status: status,
      isAllDay: isAllDay,
    );
  }

  @override
  bool operator ==(Object other) {
    return super == other &&
        other is SecretaryWeekEvent &&
        other.title == title &&
        other.provider == provider &&
        other.itemType == itemType &&
        other.endUnknown == endUnknown &&
        other.status == status;
  }

  @override
  int get hashCode =>
      Object.hash(super.hashCode, title, provider, itemType, endUnknown, status);
}

/// Deterministic rendered-projection identity for Week layout updates.
///
/// Covers week identity, today metadata, calendar events, and temporal hints.
/// Unrelated Object metadata is omitted so equivalent snapshots do not relayout.
String weekPresentationSignature(WeekOut week) {
  final buffer = StringBuffer()
    ..write(week.weekStart)
    ..write('|')
    ..write(week.weekEnd)
    ..write('|')
    ..write(week.todayDate)
    ..write('|')
    ..write(week.isCurrentWeek);
  for (final day in week.days) {
    buffer
      ..write('|')
      ..write(day.date)
      ..write(':');
    for (final event in day.events) {
      final object = event.object;
      buffer
        ..write(object.id)
        ..write('\t')
        ..write(object.title)
        ..write('\t')
        ..write(object.provider ?? '')
        ..write('\t')
        ..write(object.startAt ?? '')
        ..write('\t')
        ..write(object.dueAt ?? '')
        ..write('\t')
        ..write(event.allDay)
        ..write(';');
    }
    buffer.write('#h');
    for (final hint in day.temporalHints) {
      buffer
        ..write(hint.id)
        ..write('\t')
        ..write(hint.title)
        ..write('\t')
        ..write(hint.primaryProvider ?? '')
        ..write('\t')
        ..write(hint.startAt)
        ..write('\t')
        ..write(hint.dueAt ?? '')
        ..write('\t')
        ..write(hint.endPrecision)
        ..write('\t')
        ..write(hint.evidenceCount)
        ..write(';');
    }
    buffer.write('#s');
    for (final work in day.scheduledWork) {
      buffer
        ..write(work.id)
        ..write('\t')
        ..write(work.title)
        ..write('\t')
        ..write(work.plannedStartAt)
        ..write('\t')
        ..write(work.plannedEndAt)
        ..write('\t')
        ..write(work.status ?? '')
        ..write(';');
    }
  }
  return buffer.toString();
}

/// Unique events from a Week projection, using original start/end instants.
///
/// The backend repeats an Object on every overlapping local day. Kalender must
/// receive each Object once so it can place overnight and multi-day spans.
/// Temporal hints are a separate typed layer and never become all-day headers.
List<SecretaryWeekEvent> weekOutToKalenderEvents(WeekOut week) {
  final first = <String, WeekEvent>{};
  final allDay = <String, bool>{};
  for (final day in week.days) {
    for (final event in day.events) {
      final id = event.object.id;
      first.putIfAbsent(id, () => event);
      allDay[id] = (allDay[id] ?? false) || event.allDay;
    }
  }
  final events = <SecretaryWeekEvent>[];
  for (final entry in first.entries) {
    final event = entry.value;
    final start = DateTime.tryParse(event.object.startAt ?? '');
    if (start == null) {
      continue;
    }
    var end = DateTime.tryParse(event.object.dueAt ?? '');
    if (end == null || !end.isAfter(start)) {
      end = start.add(kWeekUnknownEndVisualDuration);
    }
    events.add(
      SecretaryWeekEvent(
        objectId: entry.key,
        dateTimeRange: DateTimeRange(start: start, end: end),
        title: event.object.title,
        provider: event.object.provider,
        itemType: WeekTemporalItemType.calendarCommitment,
        isAllDay: allDay[entry.key] ?? false,
      ),
    );
  }
  final firstHint = <String, WeekTemporalHint>{};
  for (final day in week.days) {
    for (final hint in day.temporalHints) {
      firstHint.putIfAbsent(hint.id, () => hint);
    }
  }
  for (final hint in firstHint.values) {
    final start = DateTime.tryParse(hint.startAt);
    if (start == null) {
      continue;
    }
    final factualEnd = DateTime.tryParse(hint.dueAt ?? '');
    final endUnknown = hint.endUnknown ||
        factualEnd == null ||
        !factualEnd.isAfter(start);
    final end = endUnknown
        ? start.add(kWeekUnknownEndVisualDuration)
        : factualEnd;
    events.add(
      SecretaryWeekEvent(
        objectId: hint.id,
        dateTimeRange: DateTimeRange(start: start, end: end),
        title: hint.title,
        provider: hint.primaryProvider,
        itemType: WeekTemporalItemType.temporalHint,
        endUnknown: endUnknown,
      ),
    );
  }
  final firstWork = <String, WeekScheduledWork>{};
  for (final day in week.days) {
    for (final work in day.scheduledWork) {
      firstWork.putIfAbsent(work.id, () => work);
    }
  }
  for (final work in firstWork.values) {
    final start = DateTime.tryParse(work.plannedStartAt);
    final end = DateTime.tryParse(work.plannedEndAt);
    if (start == null || end == null || !end.isAfter(start)) {
      continue;
    }
    events.add(
      SecretaryWeekEvent(
        objectId: work.id,
        dateTimeRange: DateTimeRange(start: start, end: end),
        title: work.title,
        itemType: WeekTemporalItemType.scheduledWork,
        status: work.status,
      ),
    );
  }
  return events;
}
