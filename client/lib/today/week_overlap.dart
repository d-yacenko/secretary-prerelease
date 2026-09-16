import 'package:flutter/material.dart';
import 'package:kalender/kalender.dart';

/// Presentation clamp: depth 3 and deeper share one inset/tone step.
const int kWeekOverlapMaxDepth = 3;

/// Left inset of the day column for stack depths 0..3.
///
/// Useful widths are the complement: 100%, 96%, 93%, 90%.
const List<double> kWeekOverlapLeftInsets = [0.00, 0.04, 0.07, 0.10];

const double kWeekWideEventTitleSize = 10.5;
const double kWeekWideEventTitleHeight = 1.15;
const double kWeekWideProviderGlyphSize = 10;
const double kWeekPhoneProviderGlyphSize = 11;

/// Day-local timed span used for overlap depth and horizontal inset.
class WeekOverlapSpan {
  const WeekOverlapSpan({
    required this.id,
    required this.start,
    required this.end,
  });

  final String id;
  final DateTime start;
  final DateTime end;

  Duration get duration => end.difference(start);
}

bool weekOverlapSpansOverlap(WeekOverlapSpan a, WeekOverlapSpan b) {
  return a.start.isBefore(b.end) && b.start.isBefore(a.end);
}

int weekOverlapClampDepth(int depth) {
  if (depth < 0) {
    return 0;
  }
  if (depth > kWeekOverlapMaxDepth) {
    return kWeekOverlapMaxDepth;
  }
  return depth;
}

double weekOverlapLeftInset(int depth) {
  return kWeekOverlapLeftInsets[weekOverlapClampDepth(depth)];
}

double weekOverlapWidthFactor(int depth) {
  return 1.0 - weekOverlapLeftInset(depth);
}

int _compareOverlapOrder(WeekOverlapSpan a, WeekOverlapSpan b) {
  final byDuration = b.duration.compareTo(a.duration);
  if (byDuration != 0) {
    return byDuration;
  }
  final byStart = b.start.compareTo(a.start);
  if (byStart != 0) {
    return byStart;
  }
  return a.id.compareTo(b.id);
}

/// Deterministic day-local stack depths. Longest first (kalender overlap
/// order), then later start, then id. Depth is the count of already-placed
/// time-overlapping events, clamped to [kWeekOverlapMaxDepth].
Map<String, int> weekOverlapDepths(Iterable<WeekOverlapSpan> spans) {
  final items = spans.toList()..sort(_compareOverlapOrder);
  final depths = <String, int>{};
  final placed = <WeekOverlapSpan>[];
  for (final item in items) {
    var depth = 0;
    for (final prev in placed) {
      if (weekOverlapSpansOverlap(item, prev)) {
        depth += 1;
      }
    }
    depths[item.id] = weekOverlapClampDepth(depth);
    placed.add(item);
  }
  return depths;
}

/// Timed events intersecting [date], clipped to that local day.
List<WeekOverlapSpan> weekOverlapSpansOnDate({
  required Iterable<CalendarEvent> events,
  required InternalDateTime date,
  Location? location,
}) {
  final spans = <WeekOverlapSpan>[];
  for (final event in events) {
    if (event.isAllDay) {
      continue;
    }
    final range = event
        .internalRange(location: location)
        .dateTimeRangeOnDate(date);
    if (range == null || !range.end.isAfter(range.start)) {
      continue;
    }
    spans.add(
      WeekOverlapSpan(id: event.id, start: range.start, end: range.end),
    );
  }
  return spans;
}

Map<String, int> weekOverlapDepthsOnDate({
  required Iterable<CalendarEvent> events,
  required InternalDateTime date,
  Location? location,
}) {
  return weekOverlapDepths(
    weekOverlapSpansOnDate(events: events, date: date, location: location),
  );
}

class WeekOverlapTone {
  const WeekOverlapTone({required this.fill, required this.foreground});

  final Color fill;
  final Color foreground;
}

/// Theme-aware, non-semantic stack tones. Bookmark tokens stay independent.
WeekOverlapTone weekOverlapTone(ColorScheme scheme, int depth) {
  final fill = _weekOverlapFill(scheme, weekOverlapClampDepth(depth));
  return WeekOverlapTone(
    fill: fill,
    foreground: _weekOverlapForeground(fill, scheme),
  );
}

double weekOverlapContrastRatio(Color a, Color b) {
  final l1 = a.computeLuminance();
  final l2 = b.computeLuminance();
  final lighter = l1 > l2 ? l1 : l2;
  final darker = l1 > l2 ? l2 : l1;
  return (lighter + 0.05) / (darker + 0.05);
}

Color _weekOverlapForeground(Color fill, ColorScheme scheme) {
  final darkText = scheme.onSurface;
  final lightText = scheme.brightness == Brightness.light
      ? scheme.surface
      : scheme.onPrimary;
  return weekOverlapContrastRatio(fill, darkText) >=
          weekOverlapContrastRatio(fill, lightText)
      ? darkText
      : lightText;
}

Color _weekOverlapFill(ColorScheme scheme, int depth) {
  final base = scheme.primaryContainer;
  switch (depth) {
    case 0:
      return Color.lerp(base, scheme.onSurface, 0.12)!;
    case 1:
      return base;
    case 2:
      return Color.lerp(base, scheme.tertiaryContainer, 0.42)!;
    default:
      return Color.lerp(base, scheme.secondaryContainer, 0.48)!;
  }
}

TextStyle weekEventTitleStyle(
  TextTheme textTheme, {
  required Color color,
  required bool compact,
}) {
  if (compact) {
    return (textTheme.labelSmall ?? const TextStyle()).copyWith(color: color);
  }
  return TextStyle(
    fontSize: kWeekWideEventTitleSize,
    height: kWeekWideEventTitleHeight,
    fontWeight: FontWeight.w400,
    color: color,
  );
}
