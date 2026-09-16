import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:kalender/kalender.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/capture/capture_controller.dart';
import 'package:personal_secretary/objects/object_detail_screen.dart';
import 'package:personal_secretary/today/week_hour_grid.dart';
import 'package:personal_secretary/today/week_item_type.dart';
import 'package:personal_secretary/today/week_screen.dart';
import 'package:personal_secretary/today/week_time_grid.dart';
import 'package:personal_secretary/ui/date_format.dart';

import '../test_secretary_api_client.dart';

void main() {
  const baseUrl = 'https://secretary.example';
  const token = 'pass-d-token';
  const desktopSize = Size(1280, 768);
  const phoneSize = Size(360, 760);
  DateTime testNow() => DateTime(2026, 9, 10, 10, 0);

  Map<String, dynamic> secretaryObjectJson({
    required String id,
    required String title,
    String kind = 'event',
    String? provider = 'google_calendar',
    String? startAt,
    String? dueAt,
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
      'all_day': false,
    };
  }

  Map<String, dynamic> weekPayload({
    Map<String, List<Map<String, dynamic>>> eventsByDate = const {},
    Map<String, List<Map<String, dynamic>>> scheduledWorkByDate = const {},
    Map<String, List<Map<String, dynamic>>> hintsByDate = const {},
    String todayDate = '2026-09-10',
    bool isCurrentWeek = true,
  }) {
    const weekStart = '2026-09-07';
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

  http.Response jsonOk(Object body) => http.Response(
    jsonEncode(body),
    200,
    headers: {'content-type': 'application/json'},
  );

  MockClient weekClient({
    required Map<String, dynamic> payload,
    Map<String, String> bookmarks = const {},
    void Function(String path)? onObjectGet,
  }) {
    return MockClient((request) async {
      if (request.url.path == '/week') {
        return jsonOk(payload);
      }
      if (request.url.path == '/today') {
        return jsonOk({
          'date': '2026-09-10',
          'timezone': 'Europe/Amsterdam',
          'day_start': '2026-09-10T00:00:00+02:00',
          'tasks': [],
          'calendar_events': [],
          'notifications': [],
        });
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
            title: id,
            startAt: '2026-09-07T13:30:00+02:00',
            dueAt: '2026-09-07T14:45:00+02:00',
          ),
          'edges': [],
          'neighbors': [],
        });
      }
      if (request.url.path.startsWith('/objects/') &&
          request.url.path.endsWith('/labels')) {
        return jsonOk({'labels': []});
      }
      if (RegExp(r'^/objects/[^/]+$').hasMatch(request.url.path)) {
        final id = request.url.path.split('/').last;
        onObjectGet?.call(request.url.path);
        return jsonOk(
          secretaryObjectJson(
            id: id,
            title: id,
            kind: id.startsWith('hint') ? 'temporal_hint' : 'event',
            startAt: '2026-09-07T13:30:00+02:00',
            dueAt: '2026-09-07T14:45:00+02:00',
          ),
        );
      }
      return http.Response('{}', 404);
    });
  }

  Widget buildWeek(MockClient mock, {required Size size}) {
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
    return MaterialApp(
      home: MediaQuery(
        data: MediaQueryData(size: size),
        child: Scaffold(
          body: WeekScreen(
            apiClient: apiClient,
            authController: auth,
            captureController: capture,
            now: testNow,
            passiveRefreshInterval: const Duration(days: 1),
          ),
        ),
      ),
    );
  }

  Future<void> pumpCalendar(WidgetTester tester) async {
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    await tester.pump(const Duration(milliseconds: 50));
    await tester.pump(const Duration(milliseconds: 50));
  }

  Map<String, dynamic> layeredMonday() {
    return weekPayload(
      todayDate: '2026-09-07',
      eventsByDate: {
        '2026-09-07': [
          secretaryObjectJson(
            id: 'cal-hour',
            title: 'Hour block',
            startAt: '2026-09-07T13:00:00+02:00',
            dueAt: '2026-09-07T14:00:00+02:00',
          ),
          secretaryObjectJson(
            id: 'cal-hard',
            title: 'Hard meeting',
            startAt: '2026-09-07T13:30:00+02:00',
            dueAt: '2026-09-07T14:45:00+02:00',
          ),
        ],
      },
      scheduledWorkByDate: {
        '2026-09-07': [
          {
            'id': 'soft-work',
            'title': 'Planned task',
            'planned_start_at': '2026-09-07T10:00:00+02:00',
            'planned_end_at': '2026-09-07T11:00:00+02:00',
            'status': 'open',
          },
        ],
      },
      hintsByDate: {
        '2026-09-07': [
          {
            'id': 'hint-known',
            'title': 'Possible call',
            'start_at': '2026-09-07T15:00:00+02:00',
            'due_at': '2026-09-07T16:00:00+02:00',
            'end_precision': 'exact',
            'participation': 'expected',
            'primary_provider': 'gmail',
            'primary_kind': 'email',
            'evidence_count': 1,
            'extraction_confidence': 0.9,
          },
          {
            'id': 'hint-unknown',
            'title': 'Open-ended',
            'start_at': '2026-09-07T16:00:00+02:00',
            'due_at': null,
            'end_precision': 'unknown',
            'participation': 'expected',
            'primary_provider': 'gmail',
            'primary_kind': 'email',
            'evidence_count': 1,
            'extraction_confidence': 0.8,
          },
        ],
      },
    );
  }

  testWidgets('HARD/SOFT keep block geometry; hint is a centered light pill', (
    tester,
  ) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    String? openedPath;
    await tester.pumpWidget(
      buildWeek(
        weekClient(
          payload: layeredMonday(),
          onObjectGet: (path) {
            openedPath = path;
          },
          bookmarks: {'hint-known': 'red'},
        ),
        size: desktopSize,
      ),
    );
    await pumpCalendar(tester);

    final hardMaterial = tester.widget<Material>(
      find
          .descendant(
            of: find.byKey(const Key('week_event_2026-09-07_cal-hard')),
            matching: find.byType(Material),
          )
          .first,
    );
    expect(hardMaterial.shape, isA<RoundedRectangleBorder>());
    expect(hardMaterial.shape, isNot(isA<StadiumBorder>()));

    expect(
      find.byKey(const Key('week_scheduled_style_soft-work')),
      findsOneWidget,
    );
    final softMaterial = tester.widget<Material>(
      find
          .descendant(
            of: find.byKey(const Key('week_scheduled_style_soft-work')),
            matching: find.byType(Material),
          )
          .first,
    );
    expect(softMaterial.shape, isA<RoundedRectangleBorder>());

    final hintMaterial = tester.widget<Material>(
      find.byKey(const Key('week_hint_style_hint-known')),
    );
    expect(hintMaterial.shape, isA<StadiumBorder>());
    final scheme = Theme.of(
      tester.element(find.byKey(const Key('week_hint_style_hint-known'))),
    ).colorScheme;
    expect(hintMaterial.color, weekTemporalHintFill(scheme));
    expect(hintMaterial.color, isNot(hardMaterial.color));

    final lane = tester.getRect(
      find.byKey(const Key('week_event_2026-09-07_hint-known')),
    );
    final pill = tester.getRect(
      find.byKey(const Key('week_hint_visual_hint-known')),
    );
    expect(pill.width / lane.width, inInclusiveRange(0.70, 0.75));
    expect((pill.center.dx - lane.center.dx).abs(), lessThan(2));

    expect(find.byKey(const Key('week_type_hint_hint-known')), findsOneWidget);
    expect(
      tester
          .widget<Icon>(find.byKey(const Key('week_type_hint_hint-known')))
          .icon,
      weekTemporalItemTypeIcon(WeekTemporalItemType.temporalHint),
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('week_identity_rail_hint-known')),
        matching: find.byKey(const Key('source_mark_google')),
      ),
      findsOneWidget,
    );
    expect(
      find.byKey(const Key('week_hint_unknown_end_hint-unknown')),
      findsOneWidget,
    );
    expect(find.byKey(const Key('week_bookmark_hint-known')), findsOneWidget);

    await tester.ensureVisible(find.text('Possible call'));
    await tester.tap(find.text('Possible call'));
    await pumpCalendar(tester);
    expect(openedPath, '/objects/hint-known');
    expect(find.byType(ObjectDetailScreen), findsOneWidget);
  });

  testWidgets(
    'compact hint pill is narrower than the lane but still readable',
    (tester) async {
      tester.view.physicalSize = phoneSize;
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(
        buildWeek(weekClient(payload: layeredMonday()), size: phoneSize),
      );
      await pumpCalendar(tester);

      final lane = tester.getRect(
        find.byKey(const Key('week_event_2026-09-07_hint-known')),
      );
      final pill = tester.getRect(
        find.byKey(const Key('week_hint_visual_hint-known')),
      );
      expect(pill.width / lane.width, inInclusiveRange(0.88, 0.92));
      expect((pill.center.dx - lane.center.dx).abs(), lessThan(2));
      expect(
        tester
            .widget<Material>(
              find.byKey(const Key('week_hint_style_hint-known')),
            )
            .shape,
        isA<StadiumBorder>(),
      );
    },
  );

  testWidgets('wide Week uses hourly cadence and exact 13:30 geometry', (
    tester,
  ) async {
    tester.view.physicalSize = desktopSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      buildWeek(weekClient(payload: layeredMonday()), size: desktopSize),
    );
    await pumpCalendar(tester);

    expect(find.byKey(TimeLine.getTimeKey(13, 0)), findsWidgets);
    expect(find.byKey(TimeLine.getTimeKey(14, 0)), findsWidgets);
    expect(find.byKey(TimeLine.getTimeKey(13, 30)), findsNothing);
    expect(find.byKey(weekHourLineKey(13)), findsOneWidget);
    expect(find.byKey(weekHourLineKey(14)), findsOneWidget);
    expect(find.byKey(const Key('week_hour_line_13_30')), findsNothing);
    expect(
      find.byKey(const Key('week_today_column_highlight')),
      findsOneWidget,
    );
    expect(find.byType(TimeIndicator), findsWidgets);

    final thirteen = tester.getRect(find.byKey(weekHourLineKey(13)));
    final fourteen = tester.getRect(find.byKey(weekHourLineKey(14)));
    expect(fourteen.top - thirteen.top, closeTo(60 * 0.9, 1));
    final atHour = tester.getRect(
      find.byKey(const Key('week_event_2026-09-07_cal-hour')),
    );
    final atHalf = tester.getRect(
      find.byKey(const Key('week_event_2026-09-07_cal-hard')),
    );
    expect(atHalf.top - atHour.top, closeTo(30 * 0.9, 2));
    expect(atHalf.bottom - atHour.top, closeTo(105 * 0.9, 3));
  });

  testWidgets('compact Week also uses hourly cadence', (tester) async {
    tester.view.physicalSize = phoneSize;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      buildWeek(weekClient(payload: layeredMonday()), size: phoneSize),
    );
    await pumpCalendar(tester);

    expect(find.byKey(TimeLine.getTimeKey(13, 0)), findsWidgets);
    expect(find.byKey(TimeLine.getTimeKey(13, 30)), findsNothing);
    expect(find.byKey(weekHourLineKey(13)), findsOneWidget);
    expect(find.byKey(weekHourLineKey(14)), findsOneWidget);
  });

  test('dark hint fill is not pure white', () {
    const light = ColorScheme.light();
    const dark = ColorScheme.dark();
    expect(weekTemporalHintFill(light), light.surfaceContainerLowest);
    expect(weekTemporalHintFill(dark), dark.surfaceContainerHigh);
    expect(weekTemporalHintFill(dark), isNot(const Color(0xFFFFFFFF)));
    expect(weekTemporalHintWidthFactor(compact: false), 0.725);
    expect(weekTemporalHintWidthFactor(compact: true), 0.90);
  });
}
