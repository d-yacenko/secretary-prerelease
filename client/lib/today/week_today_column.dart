import 'package:flutter/material.dart';
import 'package:kalender/kalender.dart';

import '../api/api_models.dart';
import 'week_hour_grid.dart';

/// Monday–Sunday index of today in [week], or null when no body highlight.
int? weekTodayColumnIndex(WeekOut week) {
  if (!week.isCurrentWeek) {
    return null;
  }
  final index = week.days.indexWhere((day) => day.date == week.todayDate);
  if (index < 0 || index > 6) {
    return null;
  }
  return index;
}

const double kWeekTodayColumnTintAlpha = 0.085;
const double kWeekTodayHeaderBadgeRadius = 5;
const EdgeInsets kWeekTodayHeaderBadgePadding = EdgeInsets.symmetric(
  horizontal: 6,
  vertical: 2,
);

/// Saturated Today header fill. Independent of provider, overlap, bookmark.
///
/// App primary (indigo seed) is too muted/lavender, so this uses a local
/// semantic blue. Light and dark both keep a strong blue with white text.
const Color kWeekTodayBadgeBlue = Color(0xFF1565C0);
const Color kWeekTodayBadgeOnFill = Color(0xFFFFFFFF);

/// Theme-aware full-column Today tint. Distinct from bare [ColorScheme.surface].
Color weekTodayColumnColor(ColorScheme scheme) {
  return Color.alphaBlend(
    scheme.primary.withValues(alpha: kWeekTodayColumnTintAlpha),
    scheme.surface,
  );
}

Color weekTodayBadgeFill(ColorScheme scheme) {
  return kWeekTodayBadgeBlue;
}

Color weekTodayBadgeForeground(ColorScheme scheme) {
  return kWeekTodayBadgeOnFill;
}

/// Hour-lines layer with a restrained today-column tint behind the lines.
///
/// Public kalender API only: custom [HourLinesBuilder] + whole-hour lines.
class WeekTodayColumnHourLines extends StatelessWidget {
  const WeekTodayColumnHourLines({
    super.key,
    required this.todayIndex,
    required this.heightPerMinute,
    required this.timeOfDayRange,
  });

  final int? todayIndex;
  final double heightPerMinute;
  final TimeOfDayRange timeOfDayRange;

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        if (todayIndex != null)
          Positioned.fill(
            child: LayoutBuilder(
              builder: (context, constraints) {
                final scheme = Theme.of(context).colorScheme;
                final tint = weekTodayColumnColor(scheme);
                return Row(
                  children: [
                    for (var i = 0; i < 7; i++)
                      Expanded(
                        child: i == todayIndex
                            ? ColoredBox(
                                key: const Key('week_today_column_highlight'),
                                color: tint,
                              )
                            : const SizedBox.expand(),
                      ),
                  ],
                );
              },
            ),
          ),
        WeekWholeHourHourLines(
          heightPerMinute: heightPerMinute,
          timeOfDayRange: timeOfDayRange,
        ),
      ],
    );
  }
}
