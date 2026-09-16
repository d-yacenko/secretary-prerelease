import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:kalender/kalender.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/capture/capture_controller.dart';
import 'package:personal_secretary/objects/object_detail_screen.dart';
import 'package:personal_secretary/today/temporal_area.dart';
import 'package:personal_secretary/today/today_screen.dart';
import 'package:personal_secretary/today/week_event_time_label.dart';
import 'package:personal_secretary/today/week_item_type.dart';
import 'package:personal_secretary/today/week_kalender_events.dart';
import 'package:personal_secretary/today/week_overlap.dart';
import 'package:personal_secretary/today/week_overlap_layout.dart';
import 'package:personal_secretary/today/week_screen.dart';
import 'package:personal_secretary/today/week_time_grid.dart';
import 'package:personal_secretary/today/week_today_column.dart';
import 'package:personal_secretary/ui/date_format.dart';
import 'package:personal_secretary/ui/object_bookmark.dart';

import '../test_secretary_api_client.dart';

void main() {
  const baseUrl = 'https://secretary.example';
  const token = 'week-token';
  const desktopSize = Size(1280, 768);
  DateTime testNow() => DateTime(2026, 9, 10, 10, 0);

  Map<String, dynamic> secretaryObjectJson({
    required String id,
    required String title,
    String kind = 'event',
    String? provider = 'google_calendar',
    String? startAt,
    String? dueAt,
    bool allDay = false,
    bool includeAllDay = true,
  }) {
    return {
      'id': id,
      'kind': kind,
      'title': title,
      'body': null,
      'provider': provider,
      'external_id': null,
      'canonical_uri': null,
      'status': null,
      'start_at': startAt,
      'due_at': dueAt,
      'occurred_at': startAt,
      'metadata': {},
      'origin': 'source',
      'state': 'observed',
      'confidence': null,
      'created_at': '2026-09-07T08:00:00Z',
      'updated_at': '2026-09-07T08:00:00Z',
      if (includeAllDay) 'all_day': allDay,
    };
  }

  Map<String, dynamic> weekTemporalHintJson({
    required String id,
    required String title,
    required String startAt,
    String? dueAt,
    String endPrecision = 'exact',
    String participation = 'expected',
    String? primaryProvider = 'gmail',
    String? primaryKind = 'email',
    int evidenceCount = 1,
    double? extractionConfidence = 0.9,
  }) {
    return {
      'id': id,
      'title': title,
      'start_at': startAt,
      'due_at': dueAt,
      'end_precision': endPrecision,
      'participation': participation,
      'primary_provider': primaryProvider,
      'primary_kind': primaryKind,
      'evidence_count': evidenceCount,
      'extraction_confidence': extractionConfidence,
    };
  }

  Map<String, dynamic> weekScheduledWorkJson({
    required String id,
    required String title,
    required String plannedStartAt,
    required String plannedEndAt,
    String? status = 'open',
  }) {
    return {
      'id': id,
      'title': title,
      'planned_start_at': plannedStartAt,
      'planned_end_at': plannedEndAt,
      'status': status,
    };
  }

  Map<String, dynamic> weekPayload({
    String weekStart = '2026-09-07',
    bool isCurrentWeek = true,
    String todayDate = '2026-09-10',
    Map<String, List<Map<String, dynamic>>> eventsByDate = const {},
    Map<String, List<Map<String, dynamic>>> scheduledWorkByDate = const {},
    Map<String, List<Map<String, dynamic>>> hintsByDate = const {},
  }) {
    return {
      'week_start': weekStart,
      'week_end': shiftCalendarDate(weekStart, 7),
      'timezone': 'Europe/Amsterdam',
      'window_start': '${weekStart}T00:00:00+02:00',
      'window_end': '${shiftCalendarDate(weekStart, 7)}T00:00:00+02:00',
      'today_date': todayDate,
      'is_current_week': isCurrentWeek,
      'days': [
        for (var i = 0; i < 7; i++)
          {
            'date': shiftCalendarDate(weekStart, i),
            'is_today': shiftCalendarDate(weekStart, i) == todayDate,
            'events': eventsByDate[shiftCalendarDate(weekStart, i)] ?? const [],
            'scheduled_work':
                scheduledWorkByDate[shiftCalendarDate(weekStart, i)] ??
                const [],
            'temporal_hints':
                hintsByDate[shiftCalendarDate(weekStart, i)] ?? const [],
          },
      ],
    };
  }

  Map<String, dynamic> todayPayload() {
    return {
      'date': '2026-09-10',
      'timezone': 'Europe/Amsterdam',
      'day_start': '2026-09-10T00:00:00+02:00',
      'tasks': [
        secretaryObjectJson(
          id: 'task-1',
          title: 'Due today',
          kind: 'task',
          provider: null,
          dueAt: '2026-09-10T14:00:00+02:00',
          includeAllDay: false,
        ),
      ],
      'calendar_events': [
        secretaryObjectJson(
          id: 'today-event-1',
          title: 'Standup',
          startAt: '2026-09-10T09:00:00+02:00',
          dueAt: '2026-09-10T10:00:00+02:00',
          includeAllDay: false,
        ),
      ],
      'notifications': [],
    };
  }

  http.Response jsonOk(Object body) => http.Response(
    jsonEncode(body),
    200,
    headers: {'content-type': 'application/json'},
  );

  Widget harness({
    required Widget child,
    Size size = desktopSize,
    TextScaler textScaler = TextScaler.noScaling,
  }) {
    return MaterialApp(
      home: MediaQuery(
        data: MediaQueryData(size: size, textScaler: textScaler),
        child: Scaffold(body: child),
      ),
    );
  }

  (AuthController, CaptureController) controllers(MockClient mock) {
    final apiClient = testSecretaryApiClient(mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final capture = CaptureController(
      apiClient: apiClient,
      authController: auth,
    );
    return (auth, capture);
  }

  Widget buildWeek(
    MockClient mock, {
    Size size = desktopSize,
    DateTime Function()? now,
    Duration passiveRefreshInterval = const Duration(days: 1),
    bool isActive = true,
  }) {
    final pair = controllers(mock);
    return harness(
      size: size,
      child: WeekScreen(
        apiClient: pair.$1.apiClient,
        authController: pair.$1,
        captureController: pair.$2,
        now: now ?? testNow,
        passiveRefreshInterval: passiveRefreshInterval,
        isActive: isActive,
      ),
    );
  }

  Widget buildTemporal(MockClient mock, {Size size = desktopSize}) {
    final pair = controllers(mock);
    return harness(
      size: size,
      child: TemporalArea(
        apiClient: pair.$1.apiClient,
        authController: pair.$1,
        captureController: pair.$2,
        passiveRefreshInterval: const Duration(days: 1),
        clockTick: const Duration(days: 1),
        now: testNow,
      ),
    );
  }

  MockClient weekClient({
    required Map<String, dynamic> Function(String? weekStart) week,
    Map<String, String> bookmarks = const {},
    void Function(http.Request request)? onRequest,
  }) {
    return MockClient((request) async {
      onRequest?.call(request);
      if (request.url.path == '/week') {
        return jsonOk(week(request.url.queryParameters['week_start']));
      }
      if (request.url.path == '/today') {
        return jsonOk(todayPayload());
      }
      if (request.url.path == '/labels/by-objects') {
        return jsonOk({'objects': {}});
      }
      if (request.url.path == '/object-bookmarks/by-objects') {
        return jsonOk({
          'objects': {
            for (final entry in bookmarks.entries)
              entry.key: {'color': entry.value},
          },
        });
      }
      if (request.url.path.startsWith('/objects/') &&
          request.url.path.endsWith('/neighbors')) {
        final id = request.url.path.split('/')[2];
        return jsonOk({'object_id': id, 'neighbors': []});
      }
      if (request.url.path.startsWith('/objects/') &&
          request.url.path.endsWith('/context')) {
        final id = request.url.path.split('/')[2];
        return jsonOk({
          'object': secretaryObjectJson(
            id: id,
            title: 'Office',
            startAt: '2026-09-07T10:00:00+02:00',
            dueAt: '2026-09-07T11:00:00+02:00',
            includeAllDay: false,
          ),
          'edges': [],
          'neighbors': [],
        });
      }
      if (request.url.path.startsWith('/objects/') &&
          request.url.path.endsWith('/labels')) {
        return jsonOk({'labels': []});
      }
      if (request.url.path.startsWith('/objects/')) {
        final id = request.url.path.split('/').last;
        return jsonOk(
          secretaryObjectJson(
            id: id,
            title: 'Office',
            startAt: '2026-09-07T10:00:00+02:00',
            dueAt: '2026-09-07T11:00:00+02:00',
            includeAllDay: false,
          ),
        );
      }
      return http.Response('{}', 404);
    });
  }

  Future<void> pumpCalendar(WidgetTester tester) async {
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    await tester.pump(const Duration(milliseconds: 50));
    await tester.pump(const Duration(milliseconds: 50));
  }

  bool weekDayHeaderVisible(WidgetTester tester, String iso) {
    final finder = find.byKey(Key('week_day_$iso'));
    if (finder.evaluate().isEmpty) {
      return false;
    }
    final grid = tester.getRect(find.byKey(const Key('week_time_grid')));
    final rect = tester.getRect(finder);
    return rect.overlaps(grid) &&
        rect.left < grid.right - 8 &&
        rect.right > grid.left + 8;
  }

  test('formatWeekRange uses Monday-Sunday local dates', () {
    expect(formatWeekRange('2026-09-07'), '7–13 сентября');
    expect(formatWeekRange('2026-08-31'), '31 августа – 6 сентября');
  });

  test('calendar-date arithmetic is DST-safe around fall-back', () {
    expect(shiftCalendarDate('2026-10-19', 7), '2026-10-26');
    expect(shiftCalendarDate('2026-10-26', -7), '2026-10-19');
    expect(
      addCalendarDays(parseCalendarDate('2026-10-19'), 7),
      DateTime.utc(2026, 10, 26),
    );
    expect(parseCalendarDate('2026-10-19').isUtc, isTrue);
    expect(
      parseCalendarDate('2026-10-19').add(const Duration(days: 7)),
      DateTime.utc(2026, 10, 26),
    );
  });

  test('weekEventTimeLabel is day-local for timed spans', () {
    String iso(int year, int month, int day, int hour, int minute) {
      return DateTime(year, month, day, hour, minute).toIso8601String();
    }

    expect(
      weekEventTimeLabel(
        dayDate: '2026-09-07',
        allDay: false,
        startAt: iso(2026, 9, 7, 9, 0),
        dueAt: iso(2026, 9, 7, 10, 0),
      ),
      '09:00',
    );
    expect(
      weekEventTimeLabel(
        dayDate: '2026-09-07',
        allDay: false,
        startAt: iso(2026, 9, 7, 23, 0),
        dueAt: iso(2026, 9, 8, 1, 0),
      ),
      'с 23:00',
    );
    expect(
      weekEventTimeLabel(
        dayDate: '2026-09-08',
        allDay: false,
        startAt: iso(2026, 9, 7, 23, 0),
        dueAt: iso(2026, 9, 8, 1, 0),
      ),
      'до 01:00',
    );
    expect(
      weekEventTimeLabel(
        dayDate: '2026-09-08',
        allDay: false,
        startAt: iso(2026, 9, 7, 18, 0),
        dueAt: iso(2026, 9, 10, 10, 0),
      ),
      'Продолжается',
    );
    expect(
      weekEventTimeLabel(
        dayDate: '2026-09-09',
        allDay: false,
        startAt: iso(2026, 9, 7, 18, 0),
        dueAt: iso(2026, 9, 10, 10, 0),
      ),
      'Продолжается',
    );
    expect(
      weekEventTimeLabel(
        dayDate: '2026-09-10',
        allDay: false,
        startAt: iso(2026, 9, 7, 18, 0),
        dueAt: iso(2026, 9, 10, 10, 0),
      ),
      'до 10:00',
    );
    expect(
      weekEventTimeLabel(
        dayDate: '2026-09-07',
        allDay: true,
        startAt: iso(2026, 9, 7, 0, 0),
        dueAt: iso(2026, 9, 8, 0, 0),
      ),
      'Весь день',
    );
  });

  test('weekOutToKalenderEvents feeds each Object once with original span', () {
    String iso(int y, int m, int d, int h, int min) =>
        DateTime(y, m, d, h, min).toIso8601String();
    final overnight = secretaryObjectJson(
      id: 'overnight',
      title: 'Night shift',
      startAt: iso(2026, 9, 7, 23, 0),
      dueAt: iso(2026, 9, 8, 1, 0),
    );
    final trip = secretaryObjectJson(
      id: 'trip',
      title: 'Trip',
      startAt: iso(2026, 9, 7, 18, 0),
      dueAt: iso(2026, 9, 10, 10, 0),
    );
    final holiday = secretaryObjectJson(
      id: 'holiday',
      title: 'Holiday',
      allDay: true,
      startAt: iso(2026, 9, 7, 0, 0),
      dueAt: iso(2026, 9, 8, 0, 0),
    );
    final events = weekOutToKalenderEvents(
      WeekOut.fromJson(
        weekPayload(
          eventsByDate: {
            '2026-09-07': [holiday, overnight, trip],
            '2026-09-08': [overnight, trip],
            '2026-09-09': [trip],
            '2026-09-10': [trip],
          },
        ),
      ),
    );
    expect(events.map((e) => e.objectId).toSet(), {
      'holiday',
      'overnight',
      'trip',
    });
    expect(events.singleWhere((e) => e.objectId == 'holiday').isAllDay, isTrue);
    expect(events.map((e) => e.itemType).toSet(), {
      WeekTemporalItemType.calendarCommitment,
    });
    expect(
      events.singleWhere((e) => e.objectId == 'overnight').isAllDay,
      isFalse,
    );
    expect(
      events
          .singleWhere((e) => e.objectId == 'overnight')
          .dateTimeRange
          .duration,
      const Duration(hours: 2),
    );
    expect(
      events.singleWhere((e) => e.objectId == 'trip').dateTimeRange.duration,
      const Duration(hours: 64),
    );
  });

  test('copyWithData preserves isAllDay and identity fields', () {
    final original = SecretaryWeekEvent(
      objectId: 'holiday',
      dateTimeRange: DateTimeRange(
        start: DateTime(2026, 9, 7),
        end: DateTime(2026, 9, 8),
      ),
      title: 'Holiday',
      provider: 'google_calendar',
      isAllDay: true,
    );
    final copy = original.copyWithData(
      dateTimeRange: DateTimeRange(
        start: DateTime(2026, 9, 8),
        end: DateTime(2026, 9, 9),
      ),
    );
    expect(copy, isA<SecretaryWeekEvent>());
    expect(copy.objectId, 'holiday');
    expect(copy.title, 'Holiday');
    expect(copy.provider, 'google_calendar');
    expect(copy.itemType, WeekTemporalItemType.calendarCommitment);
    expect(copy.endUnknown, isFalse);
    expect(copy.isAllDay, isTrue);
    expect(copy.interaction.allowStartResize, isFalse);
    expect(copy.interaction.allowEndResize, isFalse);
    expect(copy.interaction.allowRescheduling, isFalse);
  });

  test('weekTodayColumnIndex is current-week Monday-Sunday', () {
    expect(weekTodayColumnIndex(WeekOut.fromJson(weekPayload())), 3);
    expect(
      weekTodayColumnIndex(WeekOut.fromJson(weekPayload(isCurrentWeek: false))),
      isNull,
    );
    expect(
      weekTodayColumnIndex(
        WeekOut.fromJson(weekPayload(todayDate: '2026-09-20')),
      ),
      isNull,
    );
  });

  test(
    'wide week initial time is morning, compact current week follows now',
    () {
      final lateMorning = DateTime(2026, 9, 11, 11, 8);
      expect(
        weekInitialTimeOfDay(
          compact: false,
          isCurrentWeek: true,
          now: lateMorning,
        ),
        kWeekMorningInitialTime,
      );
      expect(
        weekInitialTimeOfDay(
          compact: false,
          isCurrentWeek: false,
          now: lateMorning,
        ),
        kWeekMorningInitialTime,
      );
      expect(
        weekInitialTimeOfDay(
          compact: true,
          isCurrentWeek: true,
          now: lateMorning,
        ),
        const TimeOfDay(hour: 11, minute: 8),
      );
      expect(
        weekInitialTimeOfDay(
          compact: true,
          isCurrentWeek: false,
          now: lateMorning,
        ),
        kWeekMorningInitialTime,
      );
    },
  );

  test('compact 3-day viewport keeps today on screen', () {
    final monday = DateTime.utc(2026, 9, 7);
    DateTime start({required DateTime today, bool current = true}) {
      return weekCompactViewportStart(
        weekStart: monday,
        isCurrentWeek: current,
        today: today,
      );
    }

    expect(start(today: monday, current: false), monday);
    expect(start(today: monday), monday);
    expect(start(today: DateTime.utc(2026, 9, 8)), monday);
    expect(start(today: DateTime.utc(2026, 9, 9)), DateTime.utc(2026, 9, 8));
    expect(start(today: DateTime.utc(2026, 9, 10)), DateTime.utc(2026, 9, 9));
    expect(start(today: DateTime.utc(2026, 9, 11)), DateTime.utc(2026, 9, 10));
    expect(start(today: DateTime.utc(2026, 9, 12)), DateTime.utc(2026, 9, 11));
    expect(start(today: DateTime.utc(2026, 9, 13)), DateTime.utc(2026, 9, 11));
  });

  test('today header label uses weekday and day-month helpers', () {
    expect(weekDayHeaderLabel(DateTime(2026, 9, 11)), 'Пт 11 сентября');
    expect(weekDayHeaderLabel(DateTime(2026, 9, 7)), 'Пн 7 сентября');
  });

  testWidgets('Сегодня | Неделя switch keeps Today and loads Week', (
    tester,
  ) async {
    var todayCalls = 0;
    var weekCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/today') {
        todayCalls += 1;
        return jsonOk(todayPayload());
      }
      if (request.url.path == '/week') {
        weekCalls += 1;
        return jsonOk(weekPayload());
      }
      if (request.url.path == '/labels/by-objects' ||
          request.url.path == '/object-bookmarks/by-objects') {
        return jsonOk({'objects': {}});
      }
      return http.Response('{}', 404);
    });
    await tester.pumpWidget(buildTemporal(mock));
    await pumpCalendar(tester);

    expect(find.byType(TodayScreen), findsOneWidget);
    expect(find.text('Due today'), findsOneWidget);
    expect(find.text('Standup'), findsOneWidget);
    expect(find.text('Неделя'), findsOneWidget);
    expect(todayCalls, 1);
    expect(weekCalls, 0);

    await tester.tap(find.text('Неделя'));
    await pumpCalendar(tester);
    expect(find.byType(WeekScreen), findsOneWidget);
    expect(find.byKey(const Key('week_time_grid')), findsOneWidget);
    expect(find.text('На этой неделе событий нет'), findsOneWidget);
    expect(weekCalls, 1);
    expect(todayCalls, 1);

    await tester.tap(find.text('Сегодня').last);
    await pumpCalendar(tester);
    expect(find.text('Due today'), findsOneWidget);
    expect(find.text('Standup'), findsOneWidget);
    expect(todayCalls, 1);
  });

  testWidgets('desktop week shows seven columns, overlap, providers, all-day', (
    tester,
  ) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final payload = weekPayload(
      todayDate: '2026-09-07',
      eventsByDate: {
        '2026-09-07': [
          secretaryObjectJson(
            id: 'all-day',
            title: 'Holiday',
            allDay: true,
            startAt: '2026-09-07T00:00:00Z',
            dueAt: '2026-09-08T00:00:00Z',
          ),
          secretaryObjectJson(
            id: 'yandex',
            title: 'Yandex standup',
            provider: 'yandex_calendar',
            startAt: '2026-09-07T09:00:00+02:00',
            dueAt: '2026-09-07T09:30:00+02:00',
          ),
          secretaryObjectJson(
            id: 'google',
            title: 'Google review',
            startAt: '2026-09-07T10:00:00+02:00',
            dueAt: '2026-09-07T11:00:00+02:00',
          ),
          secretaryObjectJson(
            id: 'google-overlap',
            title: 'Google overlap',
            startAt: '2026-09-07T10:30:00+02:00',
            dueAt: '2026-09-07T11:30:00+02:00',
          ),
        ],
      },
    );
    await tester.pumpWidget(
      buildWeek(weekClient(week: (_) => payload), size: desktopSize),
    );
    await pumpCalendar(tester);

    const dates = [
      '2026-09-07',
      '2026-09-08',
      '2026-09-09',
      '2026-09-10',
      '2026-09-11',
      '2026-09-12',
      '2026-09-13',
    ];
    for (var i = 1; i < dates.length; i++) {
      expect(
        tester.getTopLeft(find.byKey(Key('week_day_${dates[i]}'))).dx,
        greaterThan(
          tester.getTopLeft(find.byKey(Key('week_day_${dates[i - 1]}'))).dx,
        ),
      );
    }
    expect(find.text('Пн 7 сентября'), findsOneWidget);
    expect(find.byKey(const Key('week_today_header_badge')), findsOneWidget);
    expect(find.byKey(const Key('week_today_date_badge')), findsNothing);
    expect(find.text('Вс 13 сентября'), findsOneWidget);
    expect(
      tester
          .getTopLeft(find.byKey(const Key('week_event_2026-09-07_all-day')))
          .dy,
      lessThan(
        tester
            .getTopLeft(find.byKey(const Key('week_event_2026-09-07_yandex')))
            .dy,
      ),
    );
    final review = tester.getRect(
      find.byKey(const Key('week_event_2026-09-07_google')),
    );
    final overlap = tester.getRect(
      find.byKey(const Key('week_event_2026-09-07_google-overlap')),
    );
    expect((review.top - overlap.top).abs(), lessThan(80));
    expect((review.left - overlap.left).abs(), greaterThan(4));
    expect((review.left - overlap.left).abs(), lessThan(10));
    expect((review.width - overlap.width).abs(), greaterThan(4));
    final body = tester.widget<CalendarBody>(find.byType(CalendarBody));
    expect(
      body.multiDayBodyConfiguration?.eventLayoutStrategy,
      isA<SecretaryDenseOverlapLayoutStrategy>(),
    );
    expect(
      body.multiDayBodyConfiguration?.eventLayoutStrategy,
      isNot(isA<SideBySideLayoutStrategy>()),
    );
    expect(find.text('Holiday'), findsOneWidget);
    expect(find.text('Весь день'), findsOneWidget);
    expect(find.text('Yandex standup'), findsOneWidget);
    expect(find.text('Google review'), findsOneWidget);
    expect(find.text('Google overlap'), findsOneWidget);
    expect(find.byKey(const Key('source_mark_google')), findsWidgets);
    expect(find.byKey(const Key('source_mark_yandex')), findsOneWidget);
    expect(find.byKey(const Key('week_type_calendar_google')), findsOneWidget);
    expect(find.byKey(const Key('week_type_calendar_yandex')), findsOneWidget);
    expect(find.byKey(const Key('week_day_header_2026-09-07')), findsOneWidget);
    expect(find.text('На этой неделе событий нет'), findsNothing);
  });

  testWidgets('phone week shows three day columns, not one or seven', (
    tester,
  ) async {
    const phone = Size(390, 844);
    tester.view.physicalSize = phone;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      buildWeek(weekClient(week: (_) => weekPayload()), size: phone),
    );
    await pumpCalendar(tester);

    expect(weekDayHeaderVisible(tester, '2026-09-09'), isTrue);
    expect(weekDayHeaderVisible(tester, '2026-09-10'), isTrue);
    expect(weekDayHeaderVisible(tester, '2026-09-11'), isTrue);
    expect(weekDayHeaderVisible(tester, '2026-09-07'), isFalse);
    expect(weekDayHeaderVisible(tester, '2026-09-13'), isFalse);
    final wed = tester.getRect(find.byKey(const Key('week_day_2026-09-09')));
    final thu = tester.getRect(find.byKey(const Key('week_day_2026-09-10')));
    final fri = tester.getRect(find.byKey(const Key('week_day_2026-09-11')));
    expect(thu.left, greaterThan(wed.left));
    expect(fri.left, greaterThan(thu.left));
    expect(thu.width, lessThan(phone.width * 0.5));
    expect(find.byKey(const Key('week_today_header_badge')), findsOneWidget);
  });

  testWidgets('phone non-current week opens Mon/Tue/Wed', (tester) async {
    const phone = Size(390, 844);
    tester.view.physicalSize = phone;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      buildWeek(
        weekClient(
          week: (_) => weekPayload(
            weekStart: '2026-08-31',
            isCurrentWeek: false,
            todayDate: '2026-09-10',
          ),
        ),
        size: phone,
      ),
    );
    await pumpCalendar(tester);
    expect(weekDayHeaderVisible(tester, '2026-08-31'), isTrue);
    expect(weekDayHeaderVisible(tester, '2026-09-01'), isTrue);
    expect(weekDayHeaderVisible(tester, '2026-09-02'), isTrue);
    expect(weekDayHeaderVisible(tester, '2026-09-03'), isFalse);
  });

  testWidgets('wide week keeps seven day columns', (tester) async {
    tester.view.physicalSize = const Size(600, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      buildWeek(
        weekClient(week: (_) => weekPayload()),
        size: const Size(600, 900),
      ),
    );
    await pumpCalendar(tester);
    for (final iso in [
      '2026-09-07',
      '2026-09-08',
      '2026-09-09',
      '2026-09-10',
      '2026-09-11',
      '2026-09-12',
      '2026-09-13',
    ]) {
      expect(weekDayHeaderVisible(tester, iso), isTrue);
    }
  });

  testWidgets('previous and next week query Monday starts', (tester) async {
    final requested = <String?>[];
    await tester.pumpWidget(
      buildWeek(
        weekClient(
          week: (weekStart) {
            requested.add(weekStart);
            if (weekStart == '2026-08-31') {
              return weekPayload(
                weekStart: '2026-08-31',
                isCurrentWeek: false,
                todayDate: '2026-09-10',
              );
            }
            if (weekStart == '2026-09-14') {
              return weekPayload(
                weekStart: '2026-09-14',
                isCurrentWeek: false,
                todayDate: '2026-09-10',
              );
            }
            return weekPayload();
          },
        ),
      ),
    );
    await pumpCalendar(tester);
    expect(requested, [null]);
    expect(find.text('7–13 сентября'), findsOneWidget);

    await tester.tap(find.byKey(const Key('week_nav_prev')));
    await pumpCalendar(tester);
    expect(requested.last, '2026-08-31');
    expect(find.text('31 августа – 6 сентября'), findsOneWidget);
    expect(find.byKey(const Key('week_nav_current')), findsOneWidget);

    await tester.tap(find.byKey(const Key('week_nav_current')));
    await pumpCalendar(tester);
    expect(requested.last, isNull);

    await tester.tap(find.byKey(const Key('week_nav_next')));
    await pumpCalendar(tester);
    expect(requested.last, '2026-09-14');
  });

  testWidgets('tap event opens Object Detail with Object.id', (tester) async {
    String? openedId;
    final mock = MockClient((request) async {
      if (request.url.path == '/week') {
        return jsonOk(
          weekPayload(
            eventsByDate: {
              '2026-09-07': [
                secretaryObjectJson(
                  id: 'evt-42',
                  title: 'Office',
                  startAt: '2026-09-07T10:00:00+02:00',
                  dueAt: '2026-09-07T11:00:00+02:00',
                ),
              ],
            },
          ),
        );
      }
      if (request.url.path == '/labels/by-objects' ||
          request.url.path == '/object-bookmarks/by-objects') {
        return jsonOk({'objects': {}});
      }
      if (request.url.path == '/objects/evt-42') {
        openedId = 'evt-42';
        return jsonOk(
          secretaryObjectJson(
            id: 'evt-42',
            title: 'Office',
            startAt: '2026-09-07T10:00:00+02:00',
            dueAt: '2026-09-07T11:00:00+02:00',
            includeAllDay: false,
          ),
        );
      }
      if (request.url.path == '/objects/evt-42/neighbors') {
        return jsonOk({'object_id': 'evt-42', 'neighbors': []});
      }
      if (request.url.path == '/objects/evt-42/context') {
        return jsonOk({
          'object': secretaryObjectJson(
            id: 'evt-42',
            title: 'Office',
            startAt: '2026-09-07T10:00:00+02:00',
            dueAt: '2026-09-07T11:00:00+02:00',
            includeAllDay: false,
          ),
          'edges': [],
          'neighbors': [],
        });
      }
      return http.Response('{}', 404);
    });
    await tester.pumpWidget(buildWeek(mock));
    await pumpCalendar(tester);
    await tester.ensureVisible(find.text('Office'));
    await tester.tap(find.text('Office'));
    await pumpCalendar(tester);
    expect(openedId, 'evt-42');
    expect(find.byType(ObjectDetailScreen), findsOneWidget);
    expect(find.text('Использовать как контекст задачи'), findsOneWidget);
  });

  testWidgets('Week API error shows retry and Today stays usable', (
    tester,
  ) async {
    var weekShouldFail = true;
    var todayCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/today') {
        todayCalls += 1;
        return jsonOk(todayPayload());
      }
      if (request.url.path == '/week') {
        if (weekShouldFail) {
          return http.Response('{"detail":"boom"}', 500);
        }
        return jsonOk(weekPayload());
      }
      if (request.url.path == '/labels/by-objects' ||
          request.url.path == '/object-bookmarks/by-objects') {
        return jsonOk({'objects': {}});
      }
      return http.Response('{}', 404);
    });
    await tester.pumpWidget(buildTemporal(mock));
    await pumpCalendar(tester);
    await tester.tap(find.text('Неделя'));
    await pumpCalendar(tester);
    expect(find.text('Повторить'), findsOneWidget);

    await tester.tap(find.text('Сегодня').last);
    await pumpCalendar(tester);
    expect(find.text('Due today'), findsOneWidget);
    expect(todayCalls, 1);

    await tester.tap(find.text('Неделя'));
    await pumpCalendar(tester);
    weekShouldFail = false;
    await tester.tap(find.text('Повторить'));
    await pumpCalendar(tester);
    expect(find.text('На этой неделе событий нет'), findsOneWidget);
  });

  testWidgets(
    'cross-midnight continues on the next day; multi-day is in header',
    (tester) async {
      tester.view.physicalSize = desktopSize;
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      String iso(int y, int m, int d, int h, int min) =>
          DateTime(y, m, d, h, min).toIso8601String();
      final overnight = secretaryObjectJson(
        id: 'overnight',
        title: 'Night shift',
        startAt: iso(2026, 9, 7, 23, 0),
        dueAt: iso(2026, 9, 8, 1, 0),
      );
      final trip = secretaryObjectJson(
        id: 'trip',
        title: 'Trip',
        startAt: iso(2026, 9, 7, 18, 0),
        dueAt: iso(2026, 9, 10, 10, 0),
      );
      final sameDay = secretaryObjectJson(
        id: 'office',
        title: 'Office',
        startAt: iso(2026, 9, 7, 9, 0),
        dueAt: iso(2026, 9, 7, 10, 0),
      );
      final holiday = secretaryObjectJson(
        id: 'holiday',
        title: 'Holiday',
        allDay: true,
        startAt: iso(2026, 9, 7, 0, 0),
        dueAt: iso(2026, 9, 8, 0, 0),
      );
      await tester.pumpWidget(
        buildWeek(
          weekClient(
            week: (_) => weekPayload(
              eventsByDate: {
                '2026-09-07': [holiday, sameDay, overnight, trip],
                '2026-09-08': [overnight, trip],
                '2026-09-09': [trip],
                '2026-09-10': [trip],
              },
            ),
          ),
          size: desktopSize,
          now: () => DateTime(2026, 9, 10, 0, 20),
        ),
      );
      await pumpCalendar(tester);

      expect(
        find.byKey(const Key('week_event_2026-09-07_holiday')),
        findsOneWidget,
      );
      expect(find.text('Trip'), findsOneWidget);

      final bodyScrollable = find.descendant(
        of: find.byKey(const Key('week_time_grid')),
        matching: find.byType(Scrollable),
      );
      await tester.fling(bodyScrollable.first, const Offset(0, 2500), 2000);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      expect(
        find.byKey(const Key('week_event_2026-09-08_overnight')),
        findsOneWidget,
      );

      await tester.fling(bodyScrollable.first, const Offset(0, -4000), 2000);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      expect(
        find.byKey(const Key('week_event_2026-09-07_overnight')),
        findsOneWidget,
      );
      expect(find.text('Night shift'), findsWidgets);
    },
  );

  testWidgets('failed next/previous week retry repeats the same week_start', (
    tester,
  ) async {
    final requested = <String?>[];
    final failFor = <String>{};
    await tester.pumpWidget(
      buildWeek(
        MockClient((request) async {
          if (request.url.path == '/week') {
            final weekStart = request.url.queryParameters['week_start'];
            requested.add(weekStart);
            if (weekStart != null && failFor.contains(weekStart)) {
              return http.Response('{"detail":"boom"}', 500);
            }
            if (weekStart == '2026-08-31') {
              return jsonOk(
                weekPayload(
                  weekStart: '2026-08-31',
                  isCurrentWeek: false,
                  todayDate: '2026-09-10',
                ),
              );
            }
            if (weekStart == '2026-09-14') {
              return jsonOk(
                weekPayload(
                  weekStart: '2026-09-14',
                  isCurrentWeek: false,
                  todayDate: '2026-09-10',
                ),
              );
            }
            return jsonOk(weekPayload());
          }
          if (request.url.path == '/labels/by-objects' ||
              request.url.path == '/object-bookmarks/by-objects') {
            return jsonOk({'objects': {}});
          }
          return http.Response('{}', 404);
        }),
      ),
    );
    await pumpCalendar(tester);
    expect(requested, [null]);
    expect(find.text('7–13 сентября'), findsOneWidget);

    failFor.add('2026-09-14');
    await tester.tap(find.byKey(const Key('week_nav_next')));
    await pumpCalendar(tester);
    expect(requested.last, '2026-09-14');
    expect(find.text('Повторить'), findsOneWidget);

    await tester.tap(find.text('Повторить'));
    await pumpCalendar(tester);
    expect(requested.sublist(requested.length - 2), [
      '2026-09-14',
      '2026-09-14',
    ]);
    expect(find.text('Повторить'), findsOneWidget);

    failFor.remove('2026-09-14');
    await tester.tap(find.text('Повторить'));
    await pumpCalendar(tester);
    expect(requested.last, '2026-09-14');
    expect(find.text('14–20 сентября'), findsOneWidget);

    failFor.add('2026-09-07');
    await tester.tap(find.byKey(const Key('week_nav_prev')));
    await pumpCalendar(tester);
    expect(requested.last, '2026-09-07');
    expect(find.text('Повторить'), findsOneWidget);

    await tester.tap(find.text('Повторить'));
    await pumpCalendar(tester);
    expect(requested.last, '2026-09-07');
  });

  for (final size in const [Size(360, 760), Size(800, 1280), Size(1280, 768)]) {
    testWidgets('week grid does not overflow at ${size.width}x${size.height}', (
      tester,
    ) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final long =
          'Очень длинное название встречи которое должно сокращаться без горизонтального переполнения';
      await tester.pumpWidget(
        buildWeek(
          weekClient(
            week: (_) => weekPayload(
              todayDate: '2026-09-07',
              eventsByDate: {
                '2026-09-07': [
                  secretaryObjectJson(
                    id: 'long-google',
                    title: long,
                    startAt: '2026-09-07T10:00:00+02:00',
                    dueAt: '2026-09-07T11:00:00+02:00',
                  ),
                  secretaryObjectJson(
                    id: 'long-yandex',
                    title: '$long Яндекс',
                    provider: 'yandex_calendar',
                    startAt: '2026-09-07T11:00:00+02:00',
                    dueAt: '2026-09-07T12:00:00+02:00',
                  ),
                ],
              },
            ),
          ),
          size: size,
        ),
      );
      await pumpCalendar(tester);
      expect(tester.takeException(), isNull);
      expect(find.textContaining('Очень длинное'), findsWidgets);
    });
  }

  testWidgets('week grid respects enlarged text scale', (tester) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final pair = controllers(
      weekClient(
        week: (_) => weekPayload(
          eventsByDate: {
            '2026-09-07': [
              secretaryObjectJson(
                id: 'scaled',
                title: 'Масштабируемая встреча',
                startAt: '2026-09-07T10:00:00+02:00',
                dueAt: '2026-09-07T11:00:00+02:00',
              ),
            ],
          },
        ),
      ),
    );
    await tester.pumpWidget(
      harness(
        size: desktopSize,
        textScaler: const TextScaler.linear(1.3),
        child: WeekScreen(
          apiClient: pair.$1.apiClient,
          authController: pair.$1,
          captureController: pair.$2,
          now: testNow,
          passiveRefreshInterval: const Duration(days: 1),
        ),
      ),
    );
    await pumpCalendar(tester);
    expect(tester.takeException(), isNull);
    expect(find.text('Масштабируемая встреча'), findsOneWidget);
  });

  testWidgets('three overlapping events cascade and stay tappable', (
    tester,
  ) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    String? openedId;
    final mock = weekClient(
      week: (_) => weekPayload(
        eventsByDate: {
          '2026-09-07': [
            secretaryObjectJson(
              id: 'evt-a',
              title: 'Block A',
              startAt: '2026-09-07T10:00:00+02:00',
              dueAt: '2026-09-07T14:00:00+02:00',
            ),
            secretaryObjectJson(
              id: 'evt-b',
              title: 'Block B',
              startAt: '2026-09-07T11:00:00+02:00',
              dueAt: '2026-09-07T13:00:00+02:00',
            ),
            secretaryObjectJson(
              id: 'evt-c',
              title: 'Block C',
              startAt: '2026-09-07T11:30:00+02:00',
              dueAt: '2026-09-07T12:30:00+02:00',
            ),
          ],
        },
      ),
      onRequest: (request) {
        if (request.url.path == '/objects/evt-a' ||
            request.url.path == '/objects/evt-b' ||
            request.url.path == '/objects/evt-c') {
          openedId = request.url.path.split('/').last;
        }
      },
    );
    await tester.pumpWidget(buildWeek(mock, size: desktopSize));
    await pumpCalendar(tester);

    final body = tester.widget<CalendarBody>(find.byType(CalendarBody));
    expect(
      body.multiDayBodyConfiguration?.eventLayoutStrategy,
      isA<SecretaryDenseOverlapLayoutStrategy>(),
    );
    expect(
      body.multiDayBodyConfiguration?.eventLayoutStrategy,
      isNot(isA<SideBySideLayoutStrategy>()),
    );
    expect(find.text('Block A'), findsOneWidget);
    expect(find.text('Block B'), findsOneWidget);
    expect(find.text('Block C'), findsOneWidget);
    expect(
      find.byKey(const Key('week_event_2026-09-07_evt-a')),
      findsOneWidget,
    );
    expect(
      find.byKey(const Key('week_event_2026-09-07_evt-b')),
      findsOneWidget,
    );
    expect(
      find.byKey(const Key('week_event_2026-09-07_evt-c')),
      findsOneWidget,
    );

    final widths = [
      tester
          .getSize(find.byKey(const Key('week_event_2026-09-07_evt-a')))
          .width,
      tester
          .getSize(find.byKey(const Key('week_event_2026-09-07_evt-b')))
          .width,
      tester
          .getSize(find.byKey(const Key('week_event_2026-09-07_evt-c')))
          .width,
    ];
    expect(widths.toSet().length, greaterThan(1));
    expect(tester.takeException(), isNull);

    await tester.tap(find.text('Block C'));
    await pumpCalendar(tester);
    expect(openedId, 'evt-c');
    expect(find.byType(ObjectDetailScreen), findsOneWidget);
    await tester.pageBack();
    await pumpCalendar(tester);

    await tester.tap(find.text('Block A'));
    await pumpCalendar(tester);
    expect(openedId, 'evt-a');
    await tester.pageBack();
    await pumpCalendar(tester);

    await tester.tap(find.text('Block B'));
    await pumpCalendar(tester);
    expect(openedId, 'evt-b');
  });

  testWidgets('bookmarked week event shows token marker without writes', (
    tester,
  ) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final mutationPaths = <String>[];
    String? openedId;
    await tester.pumpWidget(
      buildWeek(
        weekClient(
          week: (_) => weekPayload(
            eventsByDate: {
              '2026-09-07': [
                secretaryObjectJson(
                  id: 'marked',
                  title: 'Marked',
                  startAt: '2026-09-07T10:00:00+02:00',
                  dueAt: '2026-09-07T11:00:00+02:00',
                ),
                secretaryObjectJson(
                  id: 'plain',
                  title: 'Plain',
                  startAt: '2026-09-07T12:00:00+02:00',
                  dueAt: '2026-09-07T13:00:00+02:00',
                ),
                secretaryObjectJson(
                  id: 'overlap-marked',
                  title: 'Overlap marked',
                  startAt: '2026-09-07T10:30:00+02:00',
                  dueAt: '2026-09-07T11:30:00+02:00',
                ),
              ],
            },
          ),
          bookmarks: {'marked': 'blue', 'overlap-marked': 'green'},
          onRequest: (request) {
            if (request.method == 'PUT' || request.method == 'DELETE') {
              mutationPaths.add('${request.method} ${request.url.path}');
            }
            if (request.url.path == '/objects/marked') {
              openedId = 'marked';
            }
          },
        ),
        size: desktopSize,
      ),
    );
    await pumpCalendar(tester);

    expect(find.byKey(const Key('week_bookmark_marked')), findsOneWidget);
    expect(find.byKey(const Key('week_bookmark_plain')), findsNothing);
    expect(
      find.byKey(const Key('week_bookmark_overlap-marked')),
      findsOneWidget,
    );
    expect(find.byKey(const Key('source_mark_google')), findsWidgets);
    expect(find.byKey(const Key('week_type_calendar_marked')), findsOneWidget);
    expect(find.byKey(const Key('week_type_calendar_plain')), findsOneWidget);
    expect(
      find.byKey(const Key('week_type_calendar_overlap-marked')),
      findsOneWidget,
    );
    final markedGlyph = tester.widget<ObjectBookmarkGlyph>(
      find.byKey(const Key('week_bookmark_marked')),
    );
    expect(
      markedGlyph.fillColor,
      bookmarkTokenColor('blue', ThemeData.light().colorScheme),
    );
    expect(find.byType(ObjectBookmarkPaletteButton), findsNothing);
    expect(mutationPaths, isEmpty);

    await tester.tap(find.text('Marked'));
    await pumpCalendar(tester);
    expect(openedId, 'marked');
    expect(find.byType(ObjectDetailScreen), findsOneWidget);
    expect(mutationPaths, isEmpty);
  });

  testWidgets('nested shorter event stays near-full column width', (
    tester,
  ) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      buildWeek(
        weekClient(
          week: (_) => weekPayload(
            eventsByDate: {
              '2026-09-07': [
                secretaryObjectJson(
                  id: 'long',
                  title: 'Long block',
                  startAt: '2026-09-07T10:00:00+02:00',
                  dueAt: '2026-09-07T18:00:00+02:00',
                ),
                secretaryObjectJson(
                  id: 'short',
                  title: 'Nested hour',
                  startAt: '2026-09-07T13:00:00+02:00',
                  dueAt: '2026-09-07T14:00:00+02:00',
                ),
              ],
            },
          ),
        ),
        size: desktopSize,
      ),
    );
    await pumpCalendar(tester);

    final long = tester.getRect(
      find.byKey(const Key('week_event_2026-09-07_long')),
    );
    final nested = tester.getRect(
      find.byKey(const Key('week_event_2026-09-07_short')),
    );
    final ratio = nested.width / long.width;
    expect(ratio, greaterThanOrEqualTo(0.95));
    expect(ratio, inInclusiveRange(0.95, 0.98));
    expect(nested.left, greaterThan(long.left));
    expect(nested.left - long.left, greaterThan(0));
    expect(nested.left - long.left, closeTo(long.width * 0.04, 2));
    expect(nested.right, closeTo(long.right, 1.5));
    expect(tester.takeException(), isNull);
  });

  testWidgets('four nested events keep dense width and stay tappable', (
    tester,
  ) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    String? openedId;
    await tester.pumpWidget(
      buildWeek(
        weekClient(
          week: (_) => weekPayload(
            eventsByDate: {
              '2026-09-07': [
                secretaryObjectJson(
                  id: 'nest-a',
                  title: 'Nest A',
                  startAt: '2026-09-07T10:00:00+02:00',
                  dueAt: '2026-09-07T18:00:00+02:00',
                ),
                secretaryObjectJson(
                  id: 'nest-b',
                  title: 'Nest B',
                  startAt: '2026-09-07T11:00:00+02:00',
                  dueAt: '2026-09-07T16:00:00+02:00',
                ),
                secretaryObjectJson(
                  id: 'nest-c',
                  title: 'Nest C',
                  startAt: '2026-09-07T12:00:00+02:00',
                  dueAt: '2026-09-07T14:00:00+02:00',
                ),
                secretaryObjectJson(
                  id: 'nest-d',
                  title: 'Nest D',
                  startAt: '2026-09-07T12:30:00+02:00',
                  dueAt: '2026-09-07T13:30:00+02:00',
                ),
              ],
            },
          ),
          onRequest: (request) {
            final path = request.url.path;
            if (path == '/objects/nest-a' ||
                path == '/objects/nest-b' ||
                path == '/objects/nest-c' ||
                path == '/objects/nest-d') {
              openedId = path.split('/').last;
            }
          },
        ),
        size: desktopSize,
      ),
    );
    await pumpCalendar(tester);

    final a = tester.getRect(
      find.byKey(const Key('week_event_2026-09-07_nest-a')),
    );
    final b = tester.getRect(
      find.byKey(const Key('week_event_2026-09-07_nest-b')),
    );
    final c = tester.getRect(
      find.byKey(const Key('week_event_2026-09-07_nest-c')),
    );
    final d = tester.getRect(
      find.byKey(const Key('week_event_2026-09-07_nest-d')),
    );
    expect(find.text('Nest A'), findsOneWidget);
    expect(find.text('Nest B'), findsOneWidget);
    expect(find.text('Nest C'), findsOneWidget);
    expect(find.text('Nest D'), findsOneWidget);
    expect({a.width, b.width, c.width, d.width}.length, greaterThan(1));
    expect(b.width / a.width, inInclusiveRange(0.94, 0.98));
    expect(c.width / a.width, inInclusiveRange(0.91, 0.95));
    expect(d.width / a.width, greaterThanOrEqualTo(0.89));
    expect(d.width / a.width, lessThan(0.96));
    expect(d.left - a.left, lessThan(a.width * 0.12));
    expect(tester.takeException(), isNull);

    Future<void> tapExposed(Rect tile) async {
      await tester.tapAt(Offset(tile.left + 2, tile.top + 6));
      await pumpCalendar(tester);
    }

    await tapExposed(d);
    expect(openedId, 'nest-d');
    expect(find.byType(ObjectDetailScreen), findsOneWidget);
    await tester.pageBack();
    await pumpCalendar(tester);

    await tapExposed(c);
    expect(openedId, 'nest-c');
    expect(find.byType(ObjectDetailScreen), findsOneWidget);
    await tester.pageBack();
    await pumpCalendar(tester);

    await tapExposed(b);
    expect(openedId, 'nest-b');
    expect(find.byType(ObjectDetailScreen), findsOneWidget);
    await tester.pageBack();
    await pumpCalendar(tester);

    await tapExposed(a);
    expect(openedId, 'nest-a');
    expect(find.byType(ObjectDetailScreen), findsOneWidget);
  });

  testWidgets('wide and tablet event titles are denser than phone', (
    tester,
  ) async {
    TextStyle titleStyle(Key key) {
      return tester
          .widget<Text>(
            find.descendant(
              of: find.byKey(key),
              matching: find.text('Dense title'),
            ),
          )
          .style!;
    }

    Future<void> pumpAt(Size size) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1.0;
      await tester.pumpWidget(
        buildWeek(
          weekClient(
            week: (_) => weekPayload(
              todayDate: '2026-09-07',
              eventsByDate: {
                '2026-09-07': [
                  secretaryObjectJson(
                    id: 'dense',
                    title: 'Dense title',
                    startAt: '2026-09-07T10:00:00+02:00',
                    dueAt: '2026-09-07T11:00:00+02:00',
                  ),
                ],
              },
            ),
          ),
          size: size,
        ),
      );
      await pumpCalendar(tester);
    }

    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await pumpAt(desktopSize);
    final desktop = titleStyle(const Key('week_event_2026-09-07_dense'));
    expect(desktop.fontSize, kWeekWideEventTitleSize);
    expect(desktop.height, kWeekWideEventTitleHeight);
    expect(tester.takeException(), isNull);

    await pumpAt(const Size(800, 768));
    final tablet = titleStyle(const Key('week_event_2026-09-07_dense'));
    expect(tablet.fontSize, kWeekWideEventTitleSize);
    expect(tester.takeException(), isNull);

    await pumpAt(const Size(360, 760));
    final phone = titleStyle(const Key('week_event_2026-09-07_dense'));
    expect(phone.fontSize, greaterThan(kWeekWideEventTitleSize));
    expect(tester.takeException(), isNull);
  });

  testWidgets('provider glyph and calendar type glyph are distinct', (
    tester,
  ) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    String? openedId;
    await tester.pumpWidget(
      buildWeek(
        weekClient(
          week: (_) => weekPayload(
            eventsByDate: {
              '2026-09-07': [
                secretaryObjectJson(
                  id: 'google-evt',
                  title: 'Google type',
                  provider: 'google_calendar',
                  startAt: '2026-09-07T10:00:00+02:00',
                  dueAt: '2026-09-07T11:00:00+02:00',
                ),
                secretaryObjectJson(
                  id: 'yandex-evt',
                  title: 'Yandex type',
                  provider: 'yandex_calendar',
                  startAt: '2026-09-07T12:00:00+02:00',
                  dueAt: '2026-09-07T13:00:00+02:00',
                ),
                secretaryObjectJson(
                  id: 'half-hour',
                  title: 'Thirty minutes',
                  startAt: '2026-09-07T14:00:00+02:00',
                  dueAt: '2026-09-07T14:30:00+02:00',
                ),
              ],
            },
          ),
          onRequest: (request) {
            if (request.url.path == '/objects/google-evt' ||
                request.url.path == '/objects/yandex-evt') {
              openedId = request.url.path.split('/').last;
            }
          },
        ),
        size: desktopSize,
      ),
    );
    await pumpCalendar(tester);

    expect(find.byKey(const Key('source_mark_google')), findsNWidgets(2));
    expect(find.byKey(const Key('source_mark_yandex')), findsOneWidget);
    expect(
      find.byKey(const Key('week_identity_rail_half-hour')),
      findsOneWidget,
    );
    expect(
      find.byKey(const Key('week_type_calendar_half-hour')),
      findsOneWidget,
    );
    expect(
      find.byKey(const Key('week_type_calendar_google-evt')),
      findsOneWidget,
    );
    expect(
      find.byKey(const Key('week_type_calendar_yandex-evt')),
      findsOneWidget,
    );
    expect(
      tester
          .widget<Icon>(find.byKey(const Key('week_type_calendar_google-evt')))
          .icon,
      weekTemporalItemTypeIcon(WeekTemporalItemType.calendarCommitment),
    );
    expect(
      tester
          .widget<Icon>(find.byKey(const Key('week_type_calendar_yandex-evt')))
          .icon,
      weekTemporalItemTypeIcon(WeekTemporalItemType.calendarCommitment),
    );
    expect(
      tester
          .widget<Icon>(find.byKey(const Key('week_type_calendar_google-evt')))
          .size,
      kWeekWideTypeGlyphSize,
    );
    final googleTypeIcon = tester.widget<Icon>(
      find.byKey(const Key('week_type_calendar_google-evt')),
    );
    final googleScheme = Theme.of(
      tester.element(find.byKey(const Key('week_event_2026-09-07_google-evt'))),
    ).colorScheme;
    expect(googleTypeIcon.color, weekOverlapTone(googleScheme, 0).foreground);
    expect(
      googleTypeIcon.color,
      isNot(googleScheme.onSurfaceVariant.withValues(alpha: 0.82)),
    );
    expect(
      tester
          .getSize(find.byKey(const Key('week_type_calendar_google-evt')))
          .shortestSide,
      closeTo(kWeekWideTypeGlyphSize, 0.6),
    );
    expect(
      tester
          .getSize(find.byKey(const Key('week_type_calendar_google-evt')))
          .shortestSide,
      greaterThan(kWeekWideProviderGlyphSize),
    );
    final googleTile = find.byKey(
      const Key('week_event_2026-09-07_google-evt'),
    );
    final providerRect = tester.getRect(
      find.descendant(
        of: googleTile,
        matching: find.byKey(const Key('source_mark_google')),
      ),
    );
    final typeRect = tester.getRect(
      find.byKey(const Key('week_type_calendar_google-evt')),
    );
    expect(
      typeRect.top - providerRect.bottom,
      closeTo(kWeekIdentityRailGap, 1),
    );
    expect(
      find.ancestor(
        of: find.byKey(const Key('week_identity_rail_half-hour')),
        matching: find.byWidgetPredicate(
          (widget) => widget is FittedBox && widget.fit == BoxFit.scaleDown,
        ),
      ),
      findsNothing,
    );
    expect(
      tester
          .widget<Icon>(find.byKey(const Key('week_type_calendar_half-hour')))
          .size,
      kWeekWideTypeGlyphSize,
    );
    expect(
      tester
          .getSize(find.byKey(const Key('week_type_calendar_half-hour')))
          .shortestSide,
      closeTo(kWeekWideTypeGlyphSize, 0.6),
    );
    expect(tester.takeException(), isNull);

    await tester.tap(find.text('Google type'));
    await pumpCalendar(tester);
    expect(openedId, 'google-evt');
    expect(find.byType(ObjectDetailScreen), findsOneWidget);
    await tester.pageBack();
    await pumpCalendar(tester);
    await tester.tap(find.text('Yandex type'));
    await pumpCalendar(tester);
    expect(openedId, 'yandex-evt');
  });

  testWidgets('tiny event tile clips identity rail without overflow', (
    tester,
  ) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Center(
          child: SizedBox(
            width: 140,
            height: 12,
            child: WeekKalenderEventTile(
              objectId: 'tiny',
              title: 'Tiny',
              provider: 'google_calendar',
              allDay: false,
            ),
          ),
        ),
      ),
    );
    expect(find.byKey(const Key('week_identity_rail_tiny')), findsOneWidget);
    expect(find.byKey(const Key('week_type_calendar_tiny')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('wide current week tints exactly today column', (tester) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      buildWeek(weekClient(week: (_) => weekPayload()), size: desktopSize),
    );
    await pumpCalendar(tester);

    expect(
      find.byKey(const Key('week_today_column_highlight')),
      findsOneWidget,
    );
    expect(find.byKey(const Key('week_today_header_highlight')), findsNothing);
    expect(find.byKey(const Key('week_today_header_badge')), findsOneWidget);
    expect(find.byKey(const Key('week_today_date_badge')), findsNothing);
    final highlightBox = tester.widget<ColoredBox>(
      find.byKey(const Key('week_today_column_highlight')),
    );
    final badge = tester.widget<DecoratedBox>(
      find.byKey(const Key('week_today_header_badge')),
    );
    final scheme = Theme.of(
      tester.element(find.byKey(const Key('week_today_column_highlight'))),
    ).colorScheme;
    final expectedTint = weekTodayColumnColor(scheme);
    expect(highlightBox.color, expectedTint);
    expect(highlightBox.color, isNot(scheme.surface));
    expect(badge.decoration, isA<BoxDecoration>());
    final decoration = badge.decoration as BoxDecoration;
    expect(decoration.shape, BoxShape.rectangle);
    expect(
      decoration.borderRadius,
      BorderRadius.circular(kWeekTodayHeaderBadgeRadius),
    );
    expect(decoration.color, weekTodayBadgeFill(scheme));
    expect(decoration.color, isNot(expectedTint));
    expect(
      find.descendant(
        of: find.byKey(const Key('week_today_header_badge')),
        matching: find.text('Чт 10 сентября'),
      ),
      findsOneWidget,
    );
    final label = tester.widget<Text>(
      find.byKey(const Key('week_day_header_2026-09-10')),
    );
    expect(label.data, 'Чт 10 сентября');
    expect(label.style?.color, weekTodayBadgeForeground(scheme));
    expect(label.style?.color, const Color(0xFFFFFFFF));
    final highlight = tester.getRect(
      find.byKey(const Key('week_today_column_highlight')),
    );
    final todayHeader = tester.getRect(
      find.byKey(const Key('week_day_2026-09-10')),
    );
    expect(highlight.center.dx, closeTo(todayHeader.center.dx, 28));
    expect(find.byKey(const Key('week_day_2026-09-10')), findsOneWidget);
  });

  testWidgets('non-current and phone weeks have no seven-column today tint', (
    tester,
  ) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      buildWeek(
        weekClient(
          week: (_) =>
              weekPayload(weekStart: '2026-08-31', isCurrentWeek: false),
        ),
        size: desktopSize,
      ),
    );
    await pumpCalendar(tester);
    expect(find.byKey(const Key('week_today_column_highlight')), findsNothing);
    expect(find.byKey(const Key('week_today_header_highlight')), findsNothing);
    expect(find.byKey(const Key('week_today_date_badge')), findsNothing);
    expect(find.byKey(const Key('week_today_header_badge')), findsNothing);
  });

  testWidgets('phone current week has no seven-column today tint', (
    tester,
  ) async {
    const phone = Size(360, 760);
    tester.view.physicalSize = phone;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      buildWeek(
        weekClient(week: (_) => weekPayload()),
        size: phone,
      ),
    );
    await pumpCalendar(tester);
    expect(find.byKey(const Key('week_today_column_highlight')), findsNothing);
    expect(find.byKey(const Key('week_today_header_highlight')), findsNothing);
    expect(find.byKey(const Key('week_today_date_badge')), findsNothing);
    expect(weekDayHeaderVisible(tester, '2026-09-10'), isTrue);
    expect(find.byKey(const Key('week_today_header_badge')), findsOneWidget);
  });

  testWidgets('phone today header uses the full blue date label', (
    tester,
  ) async {
    const phone = Size(360, 760);
    tester.view.physicalSize = phone;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      buildWeek(
        weekClient(week: (_) => weekPayload(todayDate: '2026-09-07')),
        size: phone,
      ),
    );
    await pumpCalendar(tester);
    expect(find.byKey(const Key('week_today_column_highlight')), findsNothing);
    expect(find.byKey(const Key('week_today_header_highlight')), findsNothing);
    expect(find.byKey(const Key('week_today_date_badge')), findsNothing);
    expect(find.byKey(const Key('week_today_header_badge')), findsOneWidget);
    expect(
      find.descendant(
        of: find.byKey(const Key('week_today_header_badge')),
        matching: find.text('Пн 7 сентября'),
      ),
      findsOneWidget,
    );
  });

  testWidgets('today header shows Friday 11 September in the blue label', (
    tester,
  ) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      buildWeek(
        weekClient(week: (_) => weekPayload(todayDate: '2026-09-11')),
        size: desktopSize,
        now: () => DateTime(2026, 9, 11, 11, 8),
      ),
    );
    await pumpCalendar(tester);
    expect(find.byKey(const Key('week_today_header_badge')), findsOneWidget);
    expect(find.byKey(const Key('week_today_date_badge')), findsNothing);
    expect(
      find.descendant(
        of: find.byKey(const Key('week_today_header_badge')),
        matching: find.text('Пт 11 сентября'),
      ),
      findsOneWidget,
    );
    final badge = tester.widget<DecoratedBox>(
      find.byKey(const Key('week_today_header_badge')),
    );
    final decoration = badge.decoration as BoxDecoration;
    expect(decoration.shape, isNot(BoxShape.circle));
    expect(
      decoration.borderRadius,
      BorderRadius.circular(kWeekTodayHeaderBadgeRadius),
    );
    expect(decoration.color, kWeekTodayBadgeBlue);
    final label = tester.widget<Text>(
      find.byKey(const Key('week_day_header_2026-09-11')),
    );
    expect(label.data, 'Пт 11 сентября');
    expect(label.style?.color, kWeekTodayBadgeOnFill);
    expect(
      find.byKey(const Key('week_today_column_highlight')),
      findsOneWidget,
    );
  });

  testWidgets('today column highlight follows current-week navigation', (
    tester,
  ) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      buildWeek(
        weekClient(
          week: (weekStart) {
            if (weekStart == '2026-08-31') {
              return weekPayload(
                weekStart: '2026-08-31',
                isCurrentWeek: false,
                todayDate: '2026-09-10',
              );
            }
            return weekPayload();
          },
        ),
      ),
    );
    await pumpCalendar(tester);
    expect(
      find.byKey(const Key('week_today_column_highlight')),
      findsOneWidget,
    );

    await tester.tap(find.byKey(const Key('week_nav_prev')));
    await pumpCalendar(tester);
    expect(find.byKey(const Key('week_today_column_highlight')), findsNothing);
    expect(find.byKey(const Key('week_today_header_highlight')), findsNothing);
    expect(find.byKey(const Key('week_today_date_badge')), findsNothing);
    expect(find.byKey(const Key('week_today_header_badge')), findsNothing);

    await tester.tap(find.byKey(const Key('week_nav_current')));
    await pumpCalendar(tester);
    expect(
      find.byKey(const Key('week_today_column_highlight')),
      findsOneWidget,
    );
    expect(find.byKey(const Key('week_today_header_highlight')), findsNothing);
    expect(find.byKey(const Key('week_today_header_badge')), findsOneWidget);
    expect(find.byKey(const Key('week_today_date_badge')), findsNothing);
    final highlight = tester.getRect(
      find.byKey(const Key('week_today_column_highlight')),
    );
    final todayHeader = tester.getRect(
      find.byKey(const Key('week_day_2026-09-10')),
    );
    expect(highlight.center.dx, closeTo(todayHeader.center.dx, 28));
  });

  testWidgets('calendar type glyph uses tile foreground in light and dark', (
    tester,
  ) async {
    Future<void> pumpTheme(ThemeData theme) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Theme(
            data: theme,
            child: const Center(
              child: SizedBox(
                width: 160,
                height: 48,
                child: WeekKalenderEventTile(
                  objectId: 'contrast',
                  title: 'Contrast',
                  provider: 'google_calendar',
                  allDay: false,
                ),
              ),
            ),
          ),
        ),
      );
    }

    await pumpTheme(
      ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF1565C0)),
      ),
    );
    final lightIcon = tester.widget<Icon>(
      find.byKey(const Key('week_type_calendar_contrast')),
    );
    final lightScheme = Theme.of(
      tester.element(find.byKey(const Key('week_type_calendar_contrast'))),
    ).colorScheme;
    expect(lightIcon.size, kWeekWideTypeGlyphSize);
    expect(lightIcon.color, weekOverlapTone(lightScheme, 0).foreground);
    expect(lightIcon.color!.computeLuminance(), lessThan(0.25));
    expect(
      lightIcon.color,
      isNot(lightScheme.onSurfaceVariant.withValues(alpha: 0.82)),
    );

    await pumpTheme(
      ThemeData.dark().copyWith(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF1565C0),
          brightness: Brightness.dark,
        ),
      ),
    );
    final darkIcon = tester.widget<Icon>(
      find.byKey(const Key('week_type_calendar_contrast')),
    );
    final darkScheme = Theme.of(
      tester.element(find.byKey(const Key('week_type_calendar_contrast'))),
    ).colorScheme;
    expect(darkScheme.brightness, Brightness.dark);
    expect(darkIcon.size, kWeekWideTypeGlyphSize);
    expect(darkIcon.color, weekOverlapTone(darkScheme, 0).foreground);
    expect(darkIcon.color, isNot(Colors.black));
    expect(
      darkIcon.color,
      isNot(darkScheme.onSurfaceVariant.withValues(alpha: 0.82)),
    );
  });

  testWidgets('active Week passively replaces snapshot without full loader', (
    tester,
  ) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var weekCalls = 0;
    final methods = <String>[];
    final mock = weekClient(
      week: (_) {
        weekCalls += 1;
        return weekPayload(
          eventsByDate: {
            '2026-09-07': [
              secretaryObjectJson(
                id: 'evt-a',
                title: 'Snapshot A',
                startAt: '2026-09-07T10:00:00+02:00',
                dueAt: '2026-09-07T11:00:00+02:00',
              ),
              if (weekCalls > 1)
                secretaryObjectJson(
                  id: 'evt-b',
                  title: 'Snapshot B',
                  startAt: '2026-09-07T14:00:00+02:00',
                  dueAt: '2026-09-07T15:00:00+02:00',
                ),
            ],
          },
        );
      },
      onRequest: (request) =>
          methods.add('${request.method} ${request.url.path}'),
    );
    await tester.pumpWidget(
      buildWeek(
        mock,
        size: desktopSize,
        passiveRefreshInterval: const Duration(milliseconds: 500),
      ),
    );
    await pumpCalendar(tester);
    expect(find.text('Snapshot A'), findsOneWidget);
    expect(find.text('Snapshot B'), findsNothing);
    expect(weekCalls, 1);
    expect(find.byType(CircularProgressIndicator), findsNothing);

    await tester.pump(const Duration(milliseconds: 550));
    await tester.pump();
    expect(weekCalls, greaterThan(1));
    expect(find.text('Snapshot B'), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsNothing);
    expect(methods.where((item) => item.contains('/sources/sync')), isEmpty);
    expect(
      methods.where(
        (item) => item.startsWith('PUT ') || item.startsWith('DELETE '),
      ),
      isEmpty,
    );
  });

  testWidgets('hidden Week does not poll /week', (tester) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var weekCalls = 0;
    final pair = controllers(
      weekClient(
        week: (_) {
          weekCalls += 1;
          return weekPayload(
            eventsByDate: {
              '2026-09-07': [
                secretaryObjectJson(
                  id: 'hidden-evt',
                  title: 'Hidden event',
                  startAt: '2026-09-07T10:00:00+02:00',
                  dueAt: '2026-09-07T11:00:00+02:00',
                ),
              ],
            },
          );
        },
      ),
    );
    await tester.pumpWidget(
      harness(
        size: desktopSize,
        child: TemporalArea(
          apiClient: pair.$1.apiClient,
          authController: pair.$1,
          captureController: pair.$2,
          passiveRefreshInterval: const Duration(milliseconds: 500),
          clockTick: const Duration(days: 1),
          now: testNow,
        ),
      ),
    );
    await pumpCalendar(tester);
    await tester.tap(find.text('Неделя'));
    await pumpCalendar(tester);
    expect(find.text('Hidden event'), findsOneWidget);
    expect(weekCalls, 1);

    await tester.tap(find.text('Сегодня').last);
    await pumpCalendar(tester);
    await tester.pump(const Duration(milliseconds: 400));
    await tester.pump();
    expect(weekCalls, 1);
  });

  testWidgets('returning to Week quietly refreshes immediately', (
    tester,
  ) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var weekCalls = 0;
    var serveB = false;
    final pair = controllers(
      weekClient(
        week: (_) {
          weekCalls += 1;
          return weekPayload(
            eventsByDate: {
              '2026-09-07': [
                secretaryObjectJson(
                  id: serveB ? 'evt-b' : 'evt-a',
                  title: serveB ? 'Snapshot B' : 'Snapshot A',
                  startAt: '2026-09-07T10:00:00+02:00',
                  dueAt: '2026-09-07T11:00:00+02:00',
                ),
              ],
            },
          );
        },
      ),
    );
    await tester.pumpWidget(
      harness(
        size: desktopSize,
        child: TemporalArea(
          apiClient: pair.$1.apiClient,
          authController: pair.$1,
          captureController: pair.$2,
          passiveRefreshInterval: const Duration(days: 1),
          clockTick: const Duration(days: 1),
          now: testNow,
        ),
      ),
    );
    await pumpCalendar(tester);
    await tester.tap(find.text('Неделя'));
    await pumpCalendar(tester);
    expect(find.text('Snapshot A'), findsOneWidget);
    expect(weekCalls, 1);

    await tester.tap(find.text('Сегодня').last);
    await pumpCalendar(tester);
    serveB = true;
    await tester.tap(find.text('Неделя'));
    await pumpCalendar(tester);
    expect(weekCalls, 2);
    expect(find.text('Snapshot B'), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsNothing);
  });

  testWidgets('passive refresh keeps the requested non-current week', (
    tester,
  ) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final weekStarts = <String?>[];
    final mock = weekClient(
      week: (weekStart) {
        weekStarts.add(weekStart);
        if (weekStart == '2026-09-14') {
          return weekPayload(
            weekStart: '2026-09-14',
            isCurrentWeek: false,
            todayDate: '2026-09-10',
            eventsByDate: {
              '2026-09-14': [
                secretaryObjectJson(
                  id: 'next-evt',
                  title: 'Next week event',
                  startAt: '2026-09-14T10:00:00+02:00',
                  dueAt: '2026-09-14T11:00:00+02:00',
                ),
              ],
            },
          );
        }
        if (weekStart == '2026-08-31') {
          return weekPayload(
            weekStart: '2026-08-31',
            isCurrentWeek: false,
            todayDate: '2026-09-10',
            eventsByDate: {
              '2026-08-31': [
                secretaryObjectJson(
                  id: 'prev-evt',
                  title: 'Previous week event',
                  startAt: '2026-08-31T10:00:00+02:00',
                  dueAt: '2026-08-31T11:00:00+02:00',
                ),
              ],
            },
          );
        }
        return weekPayload();
      },
    );
    await tester.pumpWidget(
      buildWeek(
        mock,
        size: desktopSize,
        passiveRefreshInterval: const Duration(milliseconds: 500),
      ),
    );
    await pumpCalendar(tester);
    await tester.tap(find.byKey(const Key('week_nav_next')));
    await pumpCalendar(tester);
    expect(find.text('Next week event'), findsOneWidget);
    expect(find.text('14–20 сентября'), findsOneWidget);
    final afterNext = weekStarts.length;

    await tester.pump(const Duration(milliseconds: 550));
    await tester.pump();
    expect(weekStarts.length, greaterThan(afterNext));
    expect(weekStarts.sublist(afterNext), everyElement('2026-09-14'));
    expect(find.text('Next week event'), findsOneWidget);
    expect(find.text('14–20 сентября'), findsOneWidget);

    await tester.tap(find.byKey(const Key('week_nav_prev')));
    await pumpCalendar(tester);
    await tester.tap(find.byKey(const Key('week_nav_prev')));
    await pumpCalendar(tester);
    expect(find.text('Previous week event'), findsOneWidget);
    final afterPrev = weekStarts.length;
    await tester.pump(const Duration(milliseconds: 550));
    await tester.pump();
    expect(weekStarts.sublist(afterPrev), everyElement('2026-08-31'));
    expect(find.text('31 августа – 6 сентября'), findsOneWidget);
  });

  testWidgets('passive Week error keeps last good snapshot', (tester) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var weekCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/week') {
        weekCalls += 1;
        if (weekCalls == 2) {
          return http.Response(
            jsonEncode({'detail': 'week unavailable'}),
            500,
            headers: {'content-type': 'application/json'},
          );
        }
        return jsonOk(
          weekPayload(
            eventsByDate: {
              '2026-09-07': [
                secretaryObjectJson(
                  id: weekCalls == 1 ? 'evt-a' : 'evt-b',
                  title: weekCalls == 1 ? 'Snapshot A' : 'Snapshot B',
                  startAt: '2026-09-07T10:00:00+02:00',
                  dueAt: '2026-09-07T11:00:00+02:00',
                ),
              ],
            },
          ),
        );
      }
      if (request.url.path == '/object-bookmarks/by-objects') {
        return jsonOk({'objects': {}});
      }
      return http.Response('{}', 404);
    });
    await tester.pumpWidget(
      buildWeek(
        mock,
        size: desktopSize,
        passiveRefreshInterval: const Duration(milliseconds: 500),
      ),
    );
    await pumpCalendar(tester);
    expect(find.text('Snapshot A'), findsOneWidget);

    await tester.pump(const Duration(milliseconds: 550));
    await tester.pump();
    expect(find.text('Snapshot A'), findsOneWidget);
    expect(find.text('Повторить'), findsNothing);
    expect(find.byType(SnackBar), findsNothing);

    await tester.pump(const Duration(milliseconds: 550));
    await tester.pump();
    expect(find.text('Snapshot B'), findsOneWidget);
    expect(find.text('Повторить'), findsNothing);
  });

  testWidgets('stale Week response cannot clobber newer navigation', (
    tester,
  ) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var weekCalls = 0;
    final holdPassive = Completer<void>();
    final mock = MockClient((request) async {
      if (request.url.path == '/week') {
        weekCalls += 1;
        final weekStart = request.url.queryParameters['week_start'];
        if (weekCalls == 2) {
          await holdPassive.future;
          return jsonOk(
            weekPayload(
              eventsByDate: {
                '2026-09-07': [
                  secretaryObjectJson(
                    id: 'stale-current',
                    title: 'Stale current',
                    startAt: '2026-09-07T10:00:00+02:00',
                    dueAt: '2026-09-07T11:00:00+02:00',
                  ),
                ],
              },
            ),
          );
        }
        if (weekStart == '2026-09-14') {
          return jsonOk(
            weekPayload(
              weekStart: '2026-09-14',
              isCurrentWeek: false,
              todayDate: '2026-09-10',
              eventsByDate: {
                '2026-09-14': [
                  secretaryObjectJson(
                    id: 'next-evt',
                    title: 'Next week event',
                    startAt: '2026-09-14T10:00:00+02:00',
                    dueAt: '2026-09-14T11:00:00+02:00',
                  ),
                ],
              },
            ),
          );
        }
        return jsonOk(weekPayload());
      }
      if (request.url.path == '/object-bookmarks/by-objects') {
        return jsonOk({'objects': {}});
      }
      return http.Response('{}', 404);
    });
    await tester.pumpWidget(
      buildWeek(
        mock,
        size: desktopSize,
        passiveRefreshInterval: const Duration(milliseconds: 500),
      ),
    );
    await pumpCalendar(tester);
    await tester.pump(const Duration(milliseconds: 550));
    expect(weekCalls, 2);

    await tester.tap(find.byKey(const Key('week_nav_next')));
    await pumpCalendar(tester);
    expect(find.text('Next week event'), findsOneWidget);
    expect(find.text('14–20 сентября'), findsOneWidget);

    holdPassive.complete();
    await pumpCalendar(tester);
    expect(find.text('Next week event'), findsOneWidget);
    expect(find.text('Stale current'), findsNothing);
    expect(find.text('14–20 сентября'), findsOneWidget);
  });

  testWidgets('stale Week error cannot replace newer content', (tester) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var weekCalls = 0;
    final holdPassive = Completer<void>();
    final mock = MockClient((request) async {
      if (request.url.path == '/week') {
        weekCalls += 1;
        final weekStart = request.url.queryParameters['week_start'];
        if (weekCalls == 2) {
          await holdPassive.future;
          return http.Response(
            jsonEncode({'detail': 'stale failure'}),
            500,
            headers: {'content-type': 'application/json'},
          );
        }
        if (weekStart == '2026-09-14') {
          return jsonOk(
            weekPayload(
              weekStart: '2026-09-14',
              isCurrentWeek: false,
              todayDate: '2026-09-10',
              eventsByDate: {
                '2026-09-14': [
                  secretaryObjectJson(
                    id: 'next-evt',
                    title: 'Next week event',
                    startAt: '2026-09-14T10:00:00+02:00',
                    dueAt: '2026-09-14T11:00:00+02:00',
                  ),
                ],
              },
            ),
          );
        }
        return jsonOk(weekPayload());
      }
      if (request.url.path == '/object-bookmarks/by-objects') {
        return jsonOk({'objects': {}});
      }
      return http.Response('{}', 404);
    });
    await tester.pumpWidget(
      buildWeek(
        mock,
        size: desktopSize,
        passiveRefreshInterval: const Duration(milliseconds: 500),
      ),
    );
    await pumpCalendar(tester);
    await tester.pump(const Duration(milliseconds: 550));
    await tester.tap(find.byKey(const Key('week_nav_next')));
    await pumpCalendar(tester);
    expect(find.text('Next week event'), findsOneWidget);

    holdPassive.complete();
    await pumpCalendar(tester);
    expect(find.text('Next week event'), findsOneWidget);
    expect(find.text('Повторить'), findsNothing);
  });

  testWidgets('app resume refreshes active Week and skips hidden Week', (
    tester,
  ) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var weekCalls = 0;
    final pair = controllers(
      weekClient(
        week: (_) {
          weekCalls += 1;
          return weekPayload(
            eventsByDate: {
              '2026-09-07': [
                secretaryObjectJson(
                  id: 'live-evt',
                  title: 'Live event',
                  startAt: '2026-09-07T10:00:00+02:00',
                  dueAt: '2026-09-07T11:00:00+02:00',
                ),
              ],
            },
          );
        },
      ),
    );
    await tester.pumpWidget(
      harness(
        size: desktopSize,
        child: TemporalArea(
          apiClient: pair.$1.apiClient,
          authController: pair.$1,
          captureController: pair.$2,
          passiveRefreshInterval: const Duration(days: 1),
          clockTick: const Duration(days: 1),
          now: testNow,
        ),
      ),
    );
    await pumpCalendar(tester);
    await tester.tap(find.text('Неделя'));
    await pumpCalendar(tester);
    expect(weekCalls, 1);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await tester.pump();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await pumpCalendar(tester);
    expect(weekCalls, 2);

    await tester.tap(find.text('Сегодня').last);
    await pumpCalendar(tester);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await tester.pump();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await pumpCalendar(tester);
    expect(weekCalls, 2);
  });

  testWidgets('identical passive refresh keeps event vertical position', (
    tester,
  ) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var weekCalls = 0;
    final mock = weekClient(
      week: (_) {
        weekCalls += 1;
        return weekPayload(
          eventsByDate: {
            '2026-09-07': [
              secretaryObjectJson(
                id: 'stable',
                title: 'Stable meeting',
                startAt: '2026-09-07T10:00:00+02:00',
                dueAt: '2026-09-07T11:00:00+02:00',
              ),
            ],
          },
        );
      },
    );
    await tester.pumpWidget(
      buildWeek(
        mock,
        size: desktopSize,
        passiveRefreshInterval: const Duration(milliseconds: 500),
      ),
    );
    await pumpCalendar(tester);
    final before = tester.getRect(
      find.byKey(const Key('week_event_2026-09-07_stable')),
    );
    expect(find.byType(CircularProgressIndicator), findsNothing);

    await tester.pump(const Duration(milliseconds: 550));
    await pumpCalendar(tester);
    expect(weekCalls, greaterThan(1));
    expect(find.text('Stable meeting'), findsOneWidget);
    expect(find.text('7–13 сентября'), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsNothing);
    final after = tester.getRect(
      find.byKey(const Key('week_event_2026-09-07_stable')),
    );
    expect(after.top, closeTo(before.top, 0.5));
    expect(after.left, closeTo(before.left, 0.5));
  });

  testWidgets('advancing now does not move the event viewport', (tester) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var clock = DateTime(2026, 9, 10, 10, 0);
    final mock = weekClient(
      week: (_) => weekPayload(
        eventsByDate: {
          '2026-09-07': [
            secretaryObjectJson(
              id: 'stable',
              title: 'Stable meeting',
              startAt: '2026-09-07T10:00:00+02:00',
              dueAt: '2026-09-07T11:00:00+02:00',
            ),
          ],
        },
      ),
    );
    await tester.pumpWidget(
      buildWeek(
        mock,
        size: desktopSize,
        now: () => clock,
        passiveRefreshInterval: const Duration(days: 1),
      ),
    );
    await pumpCalendar(tester);
    final before = tester.getRect(
      find.byKey(const Key('week_event_2026-09-07_stable')),
    );

    clock = clock.add(const Duration(minutes: 1));
    await tester.pump(const Duration(minutes: 1));
    await pumpCalendar(tester);
    final after = tester.getRect(
      find.byKey(const Key('week_event_2026-09-07_stable')),
    );
    expect(after.top, closeTo(before.top, 0.5));
    expect(find.text('Stable meeting'), findsOneWidget);
  });

  testWidgets('changed passive snapshot adds events without recentering', (
    tester,
  ) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var weekCalls = 0;
    final mock = weekClient(
      week: (_) {
        weekCalls += 1;
        return weekPayload(
          eventsByDate: {
            '2026-09-07': [
              secretaryObjectJson(
                id: 'stable',
                title: 'Stable meeting',
                startAt: '2026-09-07T10:00:00+02:00',
                dueAt: '2026-09-07T11:00:00+02:00',
              ),
              if (weekCalls > 1)
                secretaryObjectJson(
                  id: 'later',
                  title: 'Later meeting',
                  startAt: '2026-09-07T16:00:00+02:00',
                  dueAt: '2026-09-07T17:00:00+02:00',
                ),
            ],
          },
        );
      },
    );
    await tester.pumpWidget(
      buildWeek(
        mock,
        size: desktopSize,
        passiveRefreshInterval: const Duration(milliseconds: 500),
      ),
    );
    await pumpCalendar(tester);
    final before = tester.getRect(
      find.byKey(const Key('week_event_2026-09-07_stable')),
    );
    expect(find.text('Later meeting'), findsNothing);

    await tester.pump(const Duration(milliseconds: 550));
    await pumpCalendar(tester);
    expect(find.text('Later meeting'), findsOneWidget);
    expect(find.text('7–13 сентября'), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsNothing);
    final after = tester.getRect(
      find.byKey(const Key('week_event_2026-09-07_stable')),
    );
    expect(after.top, closeTo(before.top, 0.5));
  });

  test(
    'weekOutToKalenderEvents projects hints without inventing factual end',
    () {
      final week = WeekOut.fromJson(
        weekPayload(
          eventsByDate: {
            '2026-09-07': [
              secretaryObjectJson(
                id: 'google',
                title: 'Google review',
                startAt: '2026-09-07T10:00:00+02:00',
                dueAt: '2026-09-07T11:00:00+02:00',
              ),
              secretaryObjectJson(
                id: 'yandex',
                title: 'Yandex standup',
                provider: 'yandex_calendar',
                startAt: '2026-09-07T09:00:00+02:00',
                dueAt: '2026-09-07T09:30:00+02:00',
              ),
            ],
          },
          hintsByDate: {
            '2026-09-07': [
              weekTemporalHintJson(
                id: 'hint-known',
                title: 'Known duration call',
                startAt: '2026-09-07T14:00:00+02:00',
                dueAt: '2026-09-07T15:00:00+02:00',
              ),
              weekTemporalHintJson(
                id: 'hint-unknown',
                title: 'Unknown duration call',
                startAt: '2026-09-07T16:00:00+02:00',
                endPrecision: 'unknown',
              ),
            ],
          },
        ),
      );
      final events = weekOutToKalenderEvents(week);
      expect(
        week.days.first.temporalHints
            .singleWhere((h) => h.id == 'hint-unknown')
            .dueAt,
        isNull,
      );
      expect(events.map((e) => e.objectId).toSet(), {
        'google',
        'yandex',
        'hint-known',
        'hint-unknown',
      });
      expect(events.where((e) => e.isAllDay), isEmpty);
      final known = events.singleWhere((e) => e.objectId == 'hint-known');
      final unknown = events.singleWhere((e) => e.objectId == 'hint-unknown');
      expect(known.itemType, WeekTemporalItemType.temporalHint);
      expect(known.endUnknown, isFalse);
      expect(known.dateTimeRange.duration, const Duration(hours: 1));
      expect(known.provider, 'gmail');
      expect(unknown.itemType, WeekTemporalItemType.temporalHint);
      expect(unknown.endUnknown, isTrue);
      expect(unknown.dateTimeRange.duration, kWeekUnknownEndVisualDuration);
      expect(
        events
            .where((e) => e.itemType == WeekTemporalItemType.calendarCommitment)
            .length,
        2,
      );
      final signatureWithout = weekPresentationSignature(
        WeekOut.fromJson(weekPayload()),
      );
      expect(weekPresentationSignature(week), isNot(signatureWithout));
    },
  );

  testWidgets('week renders mixed calendar and temporal hints', (tester) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var openedId = '';
    final mock = MockClient((request) async {
      if (request.url.path == '/week') {
        return jsonOk(
          weekPayload(
            eventsByDate: {
              '2026-09-07': [
                secretaryObjectJson(
                  id: 'google-evt',
                  title: 'Google review',
                  startAt: '2026-09-07T10:00:00+02:00',
                  dueAt: '2026-09-07T11:00:00+02:00',
                ),
                secretaryObjectJson(
                  id: 'yandex-evt',
                  title: 'Yandex standup',
                  provider: 'yandex_calendar',
                  startAt: '2026-09-07T09:00:00+02:00',
                  dueAt: '2026-09-07T09:30:00+02:00',
                ),
              ],
            },
            hintsByDate: {
              '2026-09-07': [
                weekTemporalHintJson(
                  id: 'hint-known',
                  title: 'Known duration call',
                  startAt: '2026-09-07T14:00:00+02:00',
                  dueAt: '2026-09-07T15:00:00+02:00',
                  primaryProvider: 'yandex_mail',
                ),
                weekTemporalHintJson(
                  id: 'hint-unknown',
                  title: 'Unknown duration call',
                  startAt: '2026-09-07T16:00:00+02:00',
                  endPrecision: 'unknown',
                  primaryProvider: 'mattermost',
                  primaryKind: 'chat_message',
                ),
              ],
            },
          ),
        );
      }
      if (request.url.path == '/labels/by-objects' ||
          request.url.path == '/object-bookmarks/by-objects') {
        return jsonOk({'objects': {}});
      }
      if (request.url.path == '/objects/hint-unknown') {
        openedId = 'hint-unknown';
        return jsonOk(
          secretaryObjectJson(
            id: 'hint-unknown',
            title: 'Unknown duration call',
            kind: 'temporal_hint',
            provider: null,
            startAt: '2026-09-07T16:00:00+02:00',
            dueAt: null,
            includeAllDay: false,
          ),
        );
      }
      if (request.url.path == '/objects/hint-unknown/neighbors') {
        return jsonOk({'object_id': 'hint-unknown', 'neighbors': []});
      }
      if (request.url.path == '/objects/hint-unknown/context') {
        return jsonOk({
          'object': secretaryObjectJson(
            id: 'hint-unknown',
            title: 'Unknown duration call',
            kind: 'temporal_hint',
            provider: null,
            startAt: '2026-09-07T16:00:00+02:00',
            dueAt: null,
            includeAllDay: false,
          ),
          'edges': [],
          'neighbors': [],
        });
      }
      if (request.url.path.endsWith('/labels')) {
        return jsonOk({'labels': []});
      }
      return http.Response('{}', 404);
    });
    await tester.pumpWidget(buildWeek(mock, size: desktopSize));
    await pumpCalendar(tester);

    expect(find.text('Google review'), findsOneWidget);
    expect(find.text('Yandex standup'), findsOneWidget);
    expect(find.text('Known duration call'), findsOneWidget);
    expect(find.text('Unknown duration call'), findsOneWidget);
    expect(
      find.byKey(const Key('week_type_calendar_google-evt')),
      findsOneWidget,
    );
    expect(
      find.byKey(const Key('week_type_calendar_yandex-evt')),
      findsOneWidget,
    );
    expect(find.byKey(const Key('week_type_hint_hint-known')), findsOneWidget);
    expect(
      find.byKey(const Key('week_type_hint_hint-unknown')),
      findsOneWidget,
    );
    expect(
      tester
          .widget<Icon>(find.byKey(const Key('week_type_hint_hint-known')))
          .icon,
      weekTemporalItemTypeIcon(WeekTemporalItemType.temporalHint),
    );
    expect(
      tester
          .widget<Icon>(find.byKey(const Key('week_type_calendar_google-evt')))
          .icon,
      weekTemporalItemTypeIcon(WeekTemporalItemType.calendarCommitment),
    );
    expect(find.byKey(const Key('week_hint_style_hint-known')), findsOneWidget);
    expect(
      find.byKey(const Key('week_hint_style_hint-unknown')),
      findsOneWidget,
    );
    expect(
      find.byKey(const Key('week_hint_unknown_end_hint-unknown')),
      findsOneWidget,
    );
    expect(
      find.byKey(const Key('week_hint_unknown_end_hint-known')),
      findsNothing,
    );
    expect(find.byKey(const Key('source_mark_google')), findsOneWidget);
    expect(find.byKey(const Key('source_mark_yandex')), findsNWidgets(2));
    expect(find.byKey(const Key('source_mark_mattermost')), findsOneWidget);

    final unknownTile = tester.getRect(
      find.byKey(const Key('week_event_2026-09-07_hint-unknown')),
    );
    final knownTile = tester.getRect(
      find.byKey(const Key('week_event_2026-09-07_hint-known')),
    );
    expect(unknownTile.height, closeTo(knownTile.height / 2, 8));

    await tester.ensureVisible(find.text('Unknown duration call'));
    await tester.tap(find.text('Unknown duration call'));
    await pumpCalendar(tester);
    expect(openedId, 'hint-unknown');
    expect(find.byType(ObjectDetailScreen), findsOneWidget);
    expect(find.text('Возможное время'), findsWidgets);
  });

  testWidgets('week with temporal hints and no events is not empty', (
    tester,
  ) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      buildWeek(
        weekClient(
          week: (_) => weekPayload(
            hintsByDate: {
              '2026-09-07': [
                weekTemporalHintJson(
                  id: 'hint-only',
                  title: 'Hint only call',
                  startAt: '2026-09-07T16:00:00+02:00',
                  endPrecision: 'unknown',
                ),
              ],
            },
          ),
        ),
        size: desktopSize,
      ),
    );
    await pumpCalendar(tester);
    expect(find.text('На этой неделе событий нет'), findsNothing);
    expect(find.text('Hint only call'), findsOneWidget);
  });

  testWidgets(
    'passive refresh shows a new hint without moving calendar tiles',
    (tester) async {
      tester.view.physicalSize = desktopSize;
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      var weekCalls = 0;
      final mock = weekClient(
        week: (_) {
          weekCalls += 1;
          return weekPayload(
            eventsByDate: {
              '2026-09-07': [
                secretaryObjectJson(
                  id: 'stable',
                  title: 'Stable meeting',
                  startAt: '2026-09-07T10:00:00+02:00',
                  dueAt: '2026-09-07T11:00:00+02:00',
                ),
              ],
            },
            hintsByDate: weekCalls == 1
                ? const {}
                : {
                    '2026-09-07': [
                      weekTemporalHintJson(
                        id: 'hint-new',
                        title: 'New temporal hint',
                        startAt: '2026-09-07T16:00:00+02:00',
                        endPrecision: 'unknown',
                      ),
                    ],
                  },
          );
        },
      );
      await tester.pumpWidget(
        buildWeek(
          mock,
          size: desktopSize,
          passiveRefreshInterval: const Duration(milliseconds: 500),
        ),
      );
      await pumpCalendar(tester);
      final before = tester.getRect(
        find.byKey(const Key('week_event_2026-09-07_stable')),
      );
      expect(find.text('New temporal hint'), findsNothing);

      await tester.pump(const Duration(milliseconds: 550));
      await pumpCalendar(tester);
      expect(find.text('New temporal hint'), findsOneWidget);
      expect(find.byKey(const Key('week_type_hint_hint-new')), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsNothing);
      final after = tester.getRect(
        find.byKey(const Key('week_event_2026-09-07_stable')),
      );
      expect(after.top, closeTo(before.top, 0.5));
      expect(after.left, closeTo(before.left, 0.5));
    },
  );

  test('scheduled work is a separate Week layer', () {
    final week = WeekOut.fromJson(
      weekPayload(
        eventsByDate: {
          '2026-09-07': [
            secretaryObjectJson(
              id: 'google',
              title: 'Google review',
              startAt: '2026-09-07T10:00:00+02:00',
              dueAt: '2026-09-07T11:00:00+02:00',
            ),
          ],
        },
        scheduledWorkByDate: {
          '2026-09-07': [
            weekScheduledWorkJson(
              id: 'task-1',
              title: 'Desk work',
              plannedStartAt: '2026-09-07T10:00:00+02:00',
              plannedEndAt: '2026-09-07T11:00:00+02:00',
            ),
          ],
        },
        hintsByDate: {
          '2026-09-07': [
            weekTemporalHintJson(
              id: 'hint-1',
              title: 'Possible call',
              startAt: '2026-09-07T10:00:00+02:00',
            ),
          ],
        },
      ),
    );
    expect(week.days.first.events.single.object.id, 'google');
    expect(week.days.first.scheduledWork.single.id, 'task-1');
    expect(week.days.first.temporalHints.single.id, 'hint-1');
    final events = weekOutToKalenderEvents(week);
    expect(events.map((e) => e.objectId).toSet(), {
      'google',
      'task-1',
      'hint-1',
    });
    expect(
      events.singleWhere((e) => e.objectId == 'task-1').itemType,
      WeekTemporalItemType.scheduledWork,
    );
    expect(events.singleWhere((e) => e.objectId == 'task-1').provider, isNull);
    expect(
      events.singleWhere((e) => e.objectId == 'google').itemType,
      WeekTemporalItemType.calendarCommitment,
    );
    expect(
      events.singleWhere((e) => e.objectId == 'hint-1').itemType,
      WeekTemporalItemType.temporalHint,
    );
    expect(
      weekPresentationSignature(week),
      isNot(weekPresentationSignature(WeekOut.fromJson(weekPayload()))),
    );
  });

  test('deadline-only task is not scheduled work', () {
    final week = WeekOut.fromJson(
      weekPayload(
        eventsByDate: {
          '2026-09-07': [
            secretaryObjectJson(
              id: 'task-due',
              title: 'Deadline only',
              kind: 'task',
              provider: null,
              dueAt: '2026-09-07T10:00:00+02:00',
              includeAllDay: false,
            ),
          ],
        },
      ),
    );
    expect(week.days.first.scheduledWork, isEmpty);
    expect(
      weekOutToKalenderEvents(
        week,
      ).where((e) => e.itemType == WeekTemporalItemType.scheduledWork),
      isEmpty,
    );
  });

  test('week has no second passive-refresh timer', () {
    final root = Directory.current.path.endsWith('client')
        ? Directory.current
        : Directory('client');
    final timeGrid = File(
      '${root.path}/lib/today/week_time_grid.dart',
    ).readAsStringSync();
    final screen = File(
      '${root.path}/lib/today/week_screen.dart',
    ).readAsStringSync();
    final availability = File(
      '${root.path}/lib/today/availability_sheet.dart',
    ).readAsStringSync();
    expect(timeGrid.contains('Timer'), isFalse);
    expect(screen.contains('Timer.periodic'), isFalse);
    expect(screen.contains('PassiveSnapshotRefresh'), isTrue);
    expect(availability.contains('Timer.periodic'), isFalse);
    expect(availability.contains('PassiveSnapshotRefresh'), isFalse);
  });

  testWidgets('week renders scheduled work distinct from events and hints', (
    tester,
  ) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var openedId = '';
    final mock = MockClient((request) async {
      if (request.url.path == '/week') {
        return jsonOk(
          weekPayload(
            eventsByDate: {
              '2026-09-07': [
                secretaryObjectJson(
                  id: 'google-evt',
                  title: 'Google review',
                  startAt: '2026-09-07T10:00:00+02:00',
                  dueAt: '2026-09-07T11:00:00+02:00',
                ),
              ],
            },
            scheduledWorkByDate: {
              '2026-09-07': [
                weekScheduledWorkJson(
                  id: 'task-desk',
                  title: 'Desk work',
                  plannedStartAt: '2026-09-07T10:00:00+02:00',
                  plannedEndAt: '2026-09-07T11:00:00+02:00',
                ),
                weekScheduledWorkJson(
                  id: 'task-done',
                  title: 'Finished memo',
                  plannedStartAt: '2026-09-07T12:00:00+02:00',
                  plannedEndAt: '2026-09-07T13:00:00+02:00',
                  status: 'done',
                ),
              ],
            },
            hintsByDate: {
              '2026-09-07': [
                weekTemporalHintJson(
                  id: 'hint-known',
                  title: 'Possible call',
                  startAt: '2026-09-07T10:30:00+02:00',
                  dueAt: '2026-09-07T11:00:00+02:00',
                ),
              ],
            },
          ),
        );
      }
      if (request.url.path == '/labels/by-objects' ||
          request.url.path == '/object-bookmarks/by-objects') {
        return jsonOk({'objects': {}});
      }
      if (request.url.path.endsWith('/neighbors')) {
        return jsonOk({'object_id': 'task-desk', 'neighbors': []});
      }
      if (request.url.path.endsWith('/context')) {
        return jsonOk({
          'object': secretaryObjectJson(
            id: 'task-desk',
            title: 'Desk work',
            kind: 'task',
            provider: null,
            includeAllDay: false,
          ),
          'edges': [],
          'neighbors': [],
        });
      }
      if (request.url.path.endsWith('/labels')) {
        return jsonOk({'labels': []});
      }
      if (request.url.path == '/objects/task-desk') {
        openedId = 'task-desk';
        return jsonOk(
          secretaryObjectJson(
            id: 'task-desk',
            title: 'Desk work',
            kind: 'task',
            provider: null,
            includeAllDay: false,
          ),
        );
      }
      return http.Response('{}', 404);
    });
    await tester.pumpWidget(buildWeek(mock, size: desktopSize));
    await pumpCalendar(tester);
    expect(find.text('Google review'), findsOneWidget);
    expect(find.text('Desk work'), findsOneWidget);
    expect(find.text('Finished memo'), findsOneWidget);
    expect(find.text('Possible call'), findsOneWidget);
    expect(find.byKey(const Key('week_type_task_task-desk')), findsOneWidget);
    expect(
      find.byKey(const Key('week_scheduled_style_task-desk')),
      findsOneWidget,
    );
    expect(
      find.byKey(const Key('week_scheduled_done_task-done')),
      findsOneWidget,
    );
    expect(find.byKey(const Key('week_hint_style_hint-known')), findsOneWidget);
    expect(
      weekTemporalItemTypeIcon(WeekTemporalItemType.scheduledWork),
      Icons.check_box_outlined,
    );
    expect(
      weekTemporalItemTypeIcon(WeekTemporalItemType.temporalHint),
      isNot(weekTemporalItemTypeIcon(WeekTemporalItemType.scheduledWork)),
    );
    expect(
      weekTemporalItemTypeIcon(WeekTemporalItemType.calendarCommitment),
      isNot(weekTemporalItemTypeIcon(WeekTemporalItemType.scheduledWork)),
    );
    await tester.ensureVisible(find.text('Desk work'));
    await tester.tap(find.text('Desk work'));
    await pumpCalendar(tester);
    expect(openedId, 'task-desk');
    expect(find.byType(ObjectDetailScreen), findsOneWidget);
  });

  testWidgets('task-only day still renders the grid', (tester) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final mock = weekClient(
      week: (_) => weekPayload(
        scheduledWorkByDate: {
          '2026-09-07': [
            weekScheduledWorkJson(
              id: 'solo-task',
              title: 'Only planned work',
              plannedStartAt: '2026-09-07T09:00:00+02:00',
              plannedEndAt: '2026-09-07T10:00:00+02:00',
            ),
          ],
        },
      ),
    );
    await tester.pumpWidget(buildWeek(mock, size: desktopSize));
    await pumpCalendar(tester);
    expect(find.text('Only planned work'), findsOneWidget);
    expect(find.text('На этой неделе событий нет'), findsNothing);
  });

  testWidgets('hint-only and event-only days stay distinct', (tester) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final mock = weekClient(
      week: (_) => weekPayload(
        eventsByDate: {
          '2026-09-08': [
            secretaryObjectJson(
              id: 'tue-event',
              title: 'Tuesday event',
              startAt: '2026-09-08T10:00:00+02:00',
              dueAt: '2026-09-08T11:00:00+02:00',
            ),
          ],
        },
        hintsByDate: {
          '2026-09-09': [
            weekTemporalHintJson(
              id: 'wed-hint',
              title: 'Wednesday hint',
              startAt: '2026-09-09T10:00:00+02:00',
            ),
          ],
        },
      ),
    );
    await tester.pumpWidget(buildWeek(mock, size: desktopSize));
    await pumpCalendar(tester);
    expect(find.text('Tuesday event'), findsOneWidget);
    expect(find.text('Wednesday hint'), findsOneWidget);
    expect(find.byKey(const Key('week_hint_style_wed-hint')), findsOneWidget);
    expect(
      find.byKey(const Key('week_scheduled_style_tue-event')),
      findsNothing,
    );
  });
}
