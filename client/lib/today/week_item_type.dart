import 'package:flutter/material.dart';

/// Semantic temporal kind occupying the Week time map.
///
/// Independent of source provider (Google / Yandex) and of bookmark color.
enum WeekTemporalItemType {
  /// Confirmed provider calendar event.
  calendarCommitment,

  /// User-planned task execution interval. Not busy time.
  scheduledWork,

  /// Derived exact-time hint. Not busy time.
  temporalHint,
}

const double kWeekWideTypeGlyphSize = 13;
const double kWeekPhoneTypeGlyphSize = 13.5;
const double kWeekIdentityRailGap = 2;

IconData weekTemporalItemTypeIcon(WeekTemporalItemType type) {
  switch (type) {
    case WeekTemporalItemType.calendarCommitment:
      return Icons.calendar_today_outlined;
    case WeekTemporalItemType.scheduledWork:
      return Icons.check_box_outlined;
    case WeekTemporalItemType.temporalHint:
      return Icons.schedule_outlined;
  }
}

String weekTemporalItemTypeSemantics(WeekTemporalItemType type) {
  switch (type) {
    case WeekTemporalItemType.calendarCommitment:
      return 'Календарное событие';
    case WeekTemporalItemType.scheduledWork:
      return 'Запланированная задача';
    case WeekTemporalItemType.temporalHint:
      return 'Возможное время';
  }
}

Key weekTemporalItemTypeKey(WeekTemporalItemType type, String objectId) {
  switch (type) {
    case WeekTemporalItemType.calendarCommitment:
      return Key('week_type_calendar_$objectId');
    case WeekTemporalItemType.scheduledWork:
      return Key('week_type_task_$objectId');
    case WeekTemporalItemType.temporalHint:
      return Key('week_type_hint_$objectId');
  }
}

/// Display-only type glyph. Does not handle taps or API calls.
class WeekTemporalItemTypeGlyph extends StatelessWidget {
  const WeekTemporalItemTypeGlyph({
    super.key,
    required this.objectId,
    required this.itemType,
    required this.size,
    required this.color,
  });

  final String objectId;
  final WeekTemporalItemType itemType;
  final double size;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: Semantics(
        label: weekTemporalItemTypeSemantics(itemType),
        child: Icon(
          key: weekTemporalItemTypeKey(itemType, objectId),
          weekTemporalItemTypeIcon(itemType),
          size: size,
          color: color,
        ),
      ),
    );
  }
}
