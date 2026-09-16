import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/capture/capture_controller.dart';
import 'package:personal_secretary/today/availability_sheet.dart';
import 'package:personal_secretary/today/week_screen.dart';
import 'package:personal_secretary/ui/date_format.dart';

import '../test_secretary_api_client.dart';

void main() {
  const baseUrl = 'https://secretary.example';
  const token = 'availability-token';
  const desktopSize = Size(1280, 768);
  DateTime testNow() => DateTime(2026, 9, 10, 10, 0);

  Map<String, dynamic> weekPayload({
    String weekStart = '2026-09-07',
    bool isCurrentWeek = true,
    String todayDate = '2026-09-10',
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
            'events': const [],
            'scheduled_work': const [],
            'temporal_hints': const [],
          },
      ],
    };
  }

  Map<String, dynamic> availabilityPayload({
    bool complete = true,
    List<Map<String, dynamic>> free = const [],
    List<Map<String, dynamic>> busy = const [],
    List<String> unknownEnd = const [],
  }) {
    return {
      'timezone': 'Europe/Amsterdam',
      'window_start': '2026-09-10T07:00:00Z',
      'window_end': '2026-09-10T16:00:00Z',
      'min_duration_minutes': 30,
      'availability_complete': complete,
      'busy_intervals': busy,
      'free_intervals': free,
      'unknown_end_event_ids': unknownEnd,
    };
  }

  http.Response jsonOk(Object body) => http.Response(
        jsonEncode(body),
        200,
        headers: {'content-type': 'application/json'},
      );

  Widget harness({required Widget child}) {
    return MaterialApp(
      home: MediaQuery(
        data: const MediaQueryData(size: desktopSize),
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

  Widget buildWeek(MockClient mock) {
    final pair = controllers(mock);
    return harness(
      child: WeekScreen(
        apiClient: pair.$1.apiClient,
        authController: pair.$1,
        captureController: pair.$2,
        now: testNow,
        passiveRefreshInterval: const Duration(days: 1),
      ),
    );
  }

  MockClient weekClient({
    required Map<String, dynamic> Function(String? weekStart) week,
    Map<String, dynamic>? Function(http.Request request)? availability,
    void Function(http.Request request)? onRequest,
  }) {
    return MockClient((request) async {
      onRequest?.call(request);
      if (request.url.path == '/week') {
        return jsonOk(week(request.url.queryParameters['week_start']));
      }
      if (request.url.path == '/availability') {
        final body = availability?.call(request);
        return jsonOk(body ?? availabilityPayload());
      }
      if (request.url.path == '/labels/by-objects' ||
          request.url.path == '/object-bookmarks/by-objects') {
        return jsonOk({'objects': {}});
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

  Future<void> openAvailability(WidgetTester tester) async {
    await tester.tap(find.byKey(const Key('week_availability_action')));
    await tester.pumpAndSettle();
  }

  test('parses availability response', () {
    final parsed = AvailabilityOut.fromJson(
      availabilityPayload(
        free: [
          {
            'start_at': '2026-09-10T08:30:00Z',
            'end_at': '2026-09-10T10:00:00Z',
            'duration_minutes': 90,
          },
        ],
        busy: [
          {
            'start_at': '2026-09-10T07:00:00Z',
            'end_at': '2026-09-10T08:30:00Z',
            'event_ids': ['evt-1', 'evt-2'],
          },
        ],
      ),
    );
    expect(parsed.timezone, 'Europe/Amsterdam');
    expect(parsed.availabilityComplete, isTrue);
    expect(parsed.minDurationMinutes, 30);
    expect(parsed.busyIntervals.single.eventIds, ['evt-1', 'evt-2']);
    expect(parsed.freeIntervals.single.durationMinutes, 90);
    expect(parsed.unknownEndEventIds, isEmpty);
  });

  test('displayed week supplies initial search date', () {
    final current = WeekOut.fromJson(weekPayload());
    expect(
      availabilityInitialSearchDate(current),
      DateTime(2026, 9, 10),
    );
    final previous = WeekOut.fromJson(
      weekPayload(weekStart: '2026-08-31', isCurrentWeek: false),
    );
    expect(
      availabilityInitialSearchDate(previous),
      DateTime(2026, 8, 31),
    );
  });

  test('formatDurationMinutes uses compact Russian units', () {
    expect(formatDurationMinutes(30), '30 мин');
    expect(formatDurationMinutes(60), '1 ч');
    expect(formatDurationMinutes(90), '1 ч 30 мин');
  });

  test('availability sheet has no extra passive timer', () {
    final root = Directory.current.path.endsWith('client')
        ? Directory.current
        : Directory('client');
    final source =
        File('${root.path}/lib/today/availability_sheet.dart').readAsStringSync();
    expect(source.contains('Timer'), isFalse);
    expect(source.contains('PassiveSnapshotRefresh'), isFalse);
    expect(source.contains('Timer.periodic'), isFalse);
  });

  testWidgets('Week header opens Свободное время sheet', (tester) async {
    await tester.pumpWidget(
      buildWeek(weekClient(week: (_) => weekPayload())),
    );
    await pumpCalendar(tester);
    expect(find.byKey(const Key('week_availability_action')), findsOneWidget);
    expect(find.byTooltip('Свободное время'), findsOneWidget);
    await openAvailability(tester);
    expect(find.text('Свободное время'), findsWidgets);
    expect(find.byKey(const Key('availability_date')), findsOneWidget);
    expect(find.byKey(const Key('availability_soft_note')), findsOneWidget);
    expect(
      find.text(
        'Запланированные задачи и возможные времена не блокируют доступность.',
      ),
      findsOneWidget,
    );
  });

  testWidgets('current week seeds today; other week keeps displayed Monday', (
    tester,
  ) async {
    await tester.pumpWidget(
      buildWeek(
        weekClient(
          week: (weekStart) {
            if (weekStart == '2026-08-31') {
              return weekPayload(
                weekStart: '2026-08-31',
                isCurrentWeek: false,
              );
            }
            return weekPayload();
          },
        ),
      ),
    );
    await pumpCalendar(tester);
    await openAvailability(tester);
    expect(find.text('10.09.26'), findsOneWidget);
    Navigator.of(tester.element(find.byKey(const Key('availability_date')))).pop();
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('week_nav_prev')));
    await pumpCalendar(tester);
    await openAvailability(tester);
    expect(find.text('31.08.26'), findsOneWidget);
    expect(find.text('10.09.26'), findsNothing);
  });

  testWidgets('date start end and min duration can be edited', (tester) async {
    tester.binding.platformDispatcher.localeTestValue = const Locale('en', 'US');
    addTearDown(tester.binding.platformDispatcher.clearLocaleTestValue);
    await tester.pumpWidget(
      buildWeek(weekClient(week: (_) => weekPayload())),
    );
    await pumpCalendar(tester);
    await openAvailability(tester);
    expect(find.text('09:00'), findsOneWidget);
    expect(find.text('18:00'), findsOneWidget);
    expect(find.text('30 мин'), findsOneWidget);

    await tester.tap(find.byKey(const Key('availability_date')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('11'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    expect(find.text('11.09.26'), findsOneWidget);

    await tester.tap(find.byKey(const Key('availability_start')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextFormField).first, '10');
    await tester.enterText(find.byType(TextFormField).at(1), '30');
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    expect(find.text('10:30'), findsOneWidget);

    await tester.tap(find.byKey(const Key('availability_end')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextFormField).first, '17');
    await tester.enterText(find.byType(TextFormField).at(1), '00');
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    expect(find.text('17:00'), findsOneWidget);

    await tester.tap(find.byKey(const Key('availability_min_duration')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('1 ч').last);
    await tester.pumpAndSettle();
    expect(find.text('1 ч'), findsOneWidget);
  });

  testWidgets('search sends UTC aware instants and timezone params', (
    tester,
  ) async {
    http.Request? availabilityRequest;
    await tester.pumpWidget(
      buildWeek(
        weekClient(
          week: (_) => weekPayload(),
          onRequest: (request) {
            if (request.url.path == '/availability') {
              availabilityRequest = request;
            }
          },
        ),
      ),
    );
    await pumpCalendar(tester);
    await openAvailability(tester);
    await tester.tap(find.byKey(const Key('availability_search')));
    await tester.pumpAndSettle();
    expect(availabilityRequest, isNotNull);
    final params = availabilityRequest!.url.queryParameters;
    expect(params['client_timezone_id'], 'Europe/Amsterdam');
    expect(params['client_utc_offset_minutes'], '120');
    expect(params['min_duration_minutes'], '30');
    expect(params['start_at']!.contains('Z'), isTrue);
    expect(params['end_at']!.contains('Z'), isTrue);
    final start = DateTime.parse(params['start_at']!);
    final end = DateTime.parse(params['end_at']!);
    expect(start.isUtc, isTrue);
    expect(end.isUtc, isTrue);
    expect(start.toLocal().hour, 9);
    expect(start.toLocal().minute, 0);
    expect(end.toLocal().hour, 18);
    expect(end.toLocal().minute, 0);
    expect(params['start_at']!.contains('T'), isTrue);
  });

  testWidgets('renders free slots without mutation actions', (tester) async {
    await tester.pumpWidget(
      buildWeek(
        weekClient(
          week: (_) => weekPayload(),
          availability: (_) => availabilityPayload(
            free: [
              {
                'start_at': '2026-09-10T08:30:00Z',
                'end_at': '2026-09-10T10:00:00Z',
                'duration_minutes': 90,
              },
              {
                'start_at': '2026-09-10T12:00:00Z',
                'end_at': '2026-09-10T13:00:00Z',
                'duration_minutes': 60,
              },
            ],
          ),
        ),
      ),
    );
    await pumpCalendar(tester);
    await openAvailability(tester);
    await tester.tap(find.byKey(const Key('availability_search')));
    await tester.pumpAndSettle();
    expect(
      find.text(
        '${formatUserTime('2026-09-10T08:30:00Z')}–${formatUserTime('2026-09-10T10:00:00Z')}   1 ч 30 мин',
      ),
      findsOneWidget,
    );
    expect(
      find.text(
        '${formatUserTime('2026-09-10T12:00:00Z')}–${formatUserTime('2026-09-10T13:00:00Z')}   1 ч',
      ),
      findsOneWidget,
    );
    expect(find.text('Создать задачу'), findsNothing);
    expect(find.text('Запланировать'), findsNothing);
    expect(find.text('В календарь'), findsNothing);
    expect(find.textContaining('Assistant'), findsNothing);
    expect(find.textContaining('OpenAI'), findsNothing);
  });

  testWidgets('shows empty free-slot state', (tester) async {
    await tester.pumpWidget(
      buildWeek(
        weekClient(
          week: (_) => weekPayload(),
          availability: (_) => availabilityPayload(),
        ),
      ),
    );
    await pumpCalendar(tester);
    await openAvailability(tester);
    await tester.tap(find.byKey(const Key('availability_search')));
    await tester.pumpAndSettle();
    expect(
      find.byKey(const Key('availability_empty')),
      findsOneWidget,
    );
    expect(
      find.text('Свободных окон заданной длительности нет'),
      findsOneWidget,
    );
  });

  testWidgets('unknown-end warning is not presented as free slots', (
    tester,
  ) async {
    await tester.pumpWidget(
      buildWeek(
        weekClient(
          week: (_) => weekPayload(),
          availability: (_) => availabilityPayload(
            complete: false,
            unknownEnd: ['evt-unknown'],
            free: [
              {
                'start_at': '2026-09-10T08:30:00Z',
                'end_at': '2026-09-10T10:00:00Z',
                'duration_minutes': 90,
              },
            ],
          ),
        ),
      ),
    );
    await pumpCalendar(tester);
    await openAvailability(tester);
    await tester.tap(find.byKey(const Key('availability_search')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('availability_incomplete')), findsOneWidget);
    expect(
      find.text(
        'Не удалось надёжно определить свободное время: у календарного события не указано время окончания.',
      ),
      findsOneWidget,
    );
    expect(find.textContaining('1 ч 30 мин'), findsNothing);
    expect(find.text('evt-unknown'), findsNothing);
  });
}
