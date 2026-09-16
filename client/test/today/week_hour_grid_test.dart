import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kalender/kalender.dart';
import 'package:personal_secretary/today/week_hour_grid.dart';

void main() {
  final allDay = TimeOfDayRange.allDay();

  test('weekWholeHourTicks are HH:00 only and skip the range start', () {
    final ticks = weekWholeHourTicks(allDay);
    expect(ticks, isNotEmpty);
    expect(ticks.every((tick) => tick.hour >= 1 && tick.hour <= 23), isTrue);
    expect(ticks.map((tick) => tick.hour).toList(), [
      for (var hour = 1; hour <= 23; hour++) hour,
    ]);
    expect(ticks.map((tick) => tick.offsetMinutes % 60).toSet(), {0});
    expect(ticks.first.offsetMinutes, 60);
  });

  test('13:30 sits halfway between 13:00 and 14:00 ticks', () {
    final ticks = {for (final tick in weekWholeHourTicks(allDay)) tick.hour: tick};
    final thirteen = ticks[13]!;
    final fourteen = ticks[14]!;
    const eventStart = 13 * 60 + 30;
    expect(eventStart - weekTimeOfDayMinutes(allDay.start), 13 * 60 + 30);
    expect(
      (thirteen.offsetMinutes + fourteen.offsetMinutes) / 2,
      13 * 60 + 30,
    );
  });

  testWidgets('whole-hour lines and labels render without :30 marks', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: SizedBox(
          width: 200,
          height: 1600,
          child: Stack(
            children: [
              WeekWholeHourHourLines(
                heightPerMinute: 0.9,
                timeOfDayRange: allDay,
              ),
              WeekWholeHourTimeLine(
                heightPerMinute: 0.9,
                timeOfDayRange: allDay,
              ),
            ],
          ),
        ),
      ),
    );

    expect(find.byKey(weekHourLineKey(13)), findsOneWidget);
    expect(find.byKey(weekHourLineKey(14)), findsOneWidget);
    expect(find.byKey(TimeLine.getTimeKey(13, 0)), findsOneWidget);
    expect(find.byKey(TimeLine.getTimeKey(14, 0)), findsOneWidget);
    expect(find.byKey(TimeLine.getTimeKey(13, 30)), findsNothing);
    expect(find.byKey(TimeLine.getTimeKey(14, 30)), findsNothing);
    expect(find.byKey(const Key('week_hour_line_13_30')), findsNothing);
    expect(find.byKey(const Key('time-13-30')), findsNothing);

    final thirteen = tester.getRect(find.byKey(weekHourLineKey(13)));
    final fourteen = tester.getRect(find.byKey(weekHourLineKey(14)));
    expect(fourteen.top - thirteen.top, closeTo(60 * 0.9, 0.5));
  });
}
