import 'package:flutter/material.dart';
import 'package:kalender/kalender.dart';

/// Whole-hour ticks after the range start. [minute] is always 0.
class WeekHourTick {
  const WeekHourTick({required this.hour, required this.offsetMinutes});

  final int hour;
  final int offsetMinutes;
}

int weekTimeOfDayMinutes(TimeOfDay time) => time.hour * 60 + time.minute;

/// Whole-hour marks strictly after [range.start] and at or before [range.end].
///
/// Matches kalender's default timeline, which skips the first segment label
/// (the top of the day). Event geometry is independent of these ticks.
List<WeekHourTick> weekWholeHourTicks(TimeOfDayRange range) {
  final startMinutes = weekTimeOfDayMinutes(range.start);
  final endMinutes = weekTimeOfDayMinutes(range.end);
  var minute = ((startMinutes + 59) ~/ 60) * 60;
  if (minute == startMinutes) {
    minute += 60;
  }
  final ticks = <WeekHourTick>[];
  while (minute <= endMinutes) {
    ticks.add(
      WeekHourTick(hour: minute ~/ 60, offsetMinutes: minute - startMinutes),
    );
    minute += 60;
  }
  return ticks;
}

Key weekHourLineKey(int hour) => Key('week_hour_line_$hour');

/// Horizontal lines only at whole-hour boundaries. Public kalender types only.
class WeekWholeHourHourLines extends StatelessWidget {
  const WeekWholeHourHourLines({
    super.key,
    required this.heightPerMinute,
    required this.timeOfDayRange,
  });

  final double heightPerMinute;
  final TimeOfDayRange timeOfDayRange;

  @override
  Widget build(BuildContext context) {
    final themeStyle = KalenderTheme.of(context).hourLinesStyle;
    final style = (themeStyle ?? const HourLinesStyle());
    final thickness = style.thickness ?? 1;
    final color = style.color ?? Theme.of(context).colorScheme.outlineVariant;
    final indent = style.indent ?? 0;
    final endIndent = style.endIndent ?? 0;
    return Stack(
      children: [
        for (final tick in weekWholeHourTicks(timeOfDayRange))
          Positioned(
            key: weekHourLineKey(tick.hour),
            top: tick.offsetMinutes * heightPerMinute,
            left: 0,
            right: 0,
            child: Container(
              margin: EdgeInsetsDirectional.only(start: indent, end: endIndent),
              height: thickness,
              color: color,
            ),
          ),
      ],
    );
  }
}

/// Gutter labels only at HH:00. Uses public [TimeLine.getTimeKey].
class WeekWholeHourTimeLine extends StatelessWidget {
  const WeekWholeHourTimeLine({
    super.key,
    required this.heightPerMinute,
    required this.timeOfDayRange,
  });

  final double heightPerMinute;
  final TimeOfDayRange timeOfDayRange;

  @override
  Widget build(BuildContext context) {
    final theme = KalenderTheme.of(context).timelineStyle ?? const TimelineStyle();
    final textStyle =
        theme.textStyle ?? Theme.of(context).textTheme.labelMedium!;
    final textDirection = theme.textDirection ?? TextDirection.ltr;
    final textPadding =
        theme.textPadding ?? const EdgeInsets.symmetric(horizontal: 8, vertical: 36);
    final labelHeight = _labelHeight(textStyle, textDirection) + textPadding.vertical;
    return Stack(
      children: [
        for (final tick in weekWholeHourTicks(timeOfDayRange))
          Positioned(
            top: tick.offsetMinutes * heightPerMinute - labelHeight / 2,
            left: 0,
            right: 0,
            child: Padding(
              padding: textPadding,
              child: Text(
                key: TimeLine.getTimeKey(tick.hour, 0),
                TimeOfDay(hour: tick.hour, minute: 0).format(context),
                style: textStyle,
                textDirection: textDirection,
                textAlign: theme.textAlign,
                overflow: theme.textOverflow,
              ),
            ),
          ),
      ],
    );
  }

  static double _labelHeight(TextStyle style, TextDirection direction) {
    final painter = TextPainter(
      text: TextSpan(text: '23:00', style: style),
      maxLines: 1,
      textDirection: direction,
    )..layout();
    final height = painter.size.height;
    painter.dispose();
    return height;
  }
}
