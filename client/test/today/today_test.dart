import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/capture/capture_controller.dart';
import 'package:personal_secretary/objects/object_detail_screen.dart';
import 'package:personal_secretary/today/today_screen.dart';

Map<String, dynamic> _todayTask({
  required String id,
  required String title,
  required String dueAt,
  required String operationalState,
  bool overdue = false,
}) {
  return {
    'id': id,
    'kind': 'task',
    'title': title,
    'body': null,
    'provider': null,
    'external_id': null,
    'canonical_uri': null,
    'status': 'open',
    'start_at': null,
    'due_at': dueAt,
    'metadata': {},
    'origin': 'user',
    'state': 'confirmed',
    'confidence': null,
    'created_at': '2026-08-28T08:00:00Z',
    'updated_at': '2026-08-28T08:00:00Z',
    'operational': {
      'operational_state': operationalState,
      'is_overdue': overdue,
      'is_scheduled_later': false,
      'is_planned_now': false,
      'due_at': dueAt,
      'planned_start_at': null,
      'planned_end_at': null,
      'blocking_dependencies': const [],
      'waiting_on': const [],
      'delegated_to': const [],
      'reason_codes': const ['no_external_blocker'],
    },
  };
}

void main() {
  const baseUrl = 'https://secretary.example';
  const token = 'today-token';

  Map<String, dynamic> todayPayload({
    List<Map<String, dynamic>>? tasks,
    List<Map<String, dynamic>>? calendarEvents,
    List<Map<String, dynamic>>? notifications,
  }) {
    return {
      'date': '2026-08-28',
      'timezone': 'Europe/Amsterdam',
      'day_start': '2026-08-28T00:00:00+02:00',
      'tasks': tasks ??
          [
            {
              'id': 'task-1',
              'kind': 'task',
              'title': 'Due today',
              'body': null,
              'provider': null,
              'external_id': null,
              'canonical_uri': null,
              'status': null,
              'start_at': null,
              'due_at': '2026-08-28T14:00:00+02:00',
              'metadata': {},
              'origin': 'user',
              'state': 'confirmed',
              'confidence': null,
              'created_at': '2026-08-28T08:00:00Z',
              'updated_at': '2026-08-28T08:00:00Z',
            },
          ],
      'calendar_events': calendarEvents ??
          [
            {
              'id': 'event-1',
              'kind': 'event',
              'title': 'Standup',
              'body': null,
              'provider': 'google',
              'external_id': null,
              'canonical_uri': null,
              'status': null,
              'start_at': '2026-08-28T09:00:00+02:00',
              'due_at': '2026-08-28T10:00:00+02:00',
              'metadata': {},
              'origin': 'source',
              'state': 'observed',
              'confidence': null,
              'created_at': '2026-08-28T08:00:00Z',
              'updated_at': '2026-08-28T08:00:00Z',
            },
          ],
      'notifications': notifications ??
          [
            {
              'id': 'n-urgent',
              'title': 'Urgent follow-up',
              'body': null,
              'priority': 'urgent',
              'status': 'new',
              'source_object_id': 'email-1',
              'related_object_id': null,
              'result_object_id': null,
              'proposal': {
                'type': 'task',
                'confidence': 0.9,
                'evidence': [],
              },
              'read_at': null,
              'created_at': '2026-08-28T08:00:00Z',
              'updated_at': '2026-08-28T08:00:00Z',
            },
          ],
    };
  }

  Widget buildToday(
    MockClient mock, {
    Duration passiveRefreshInterval = const Duration(seconds: 30),
  }) {
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final capture =
        CaptureController(apiClient: apiClient, authController: auth);
    return MaterialApp(
      home: Scaffold(
        body: TodayScreen(
          apiClient: apiClient,
          authController: auth,
          captureController: capture,
          passiveRefreshInterval: passiveRefreshInterval,
        ),
      ),
    );
  }

  testWidgets('tasks calendar and notifications render', (tester) async {
    await tester.pumpWidget(
      buildToday(MockClient((request) async {
        if (request.url.path == '/today') {
          return http.Response(jsonEncode(todayPayload()), 200);
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    expect(find.text('Due today'), findsOneWidget);
    expect(find.text('Standup'), findsOneWidget);
    expect(find.text('Urgent follow-up'), findsOneWidget);
  });

  testWidgets('empty sections work', (tester) async {
    await tester.pumpWidget(
      buildToday(MockClient((request) async {
        if (request.url.path == '/today') {
          return http.Response(
            jsonEncode({
              'date': '2026-08-28',
              'timezone': 'Europe/Amsterdam',
              'day_start': '2026-08-28T00:00:00+02:00',
              'tasks': [],
              'calendar_events': [],
              'notifications': [],
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    expect(find.text('Нет задач на сегодня'), findsOneWidget);
    expect(find.text('Нет событий в календаре'), findsOneWidget);
    expect(find.text('Нет важных уведомлений'), findsOneWidget);
  });

  testWidgets('refresh works', (tester) async {
    var todayCalls = 0;
    await tester.pumpWidget(
      buildToday(MockClient((request) async {
        if (request.method == 'POST' &&
            request.url.path.endsWith('/sources/sync')) {
          return http.Response(jsonEncode({'triggered': [], 'count': 0}), 200);
        }
        if (request.url.path.endsWith('/sources/status')) {
          return http.Response(jsonEncode({'sources': []}), 200);
        }
        if (request.url.path == '/today') {
          todayCalls += 1;
          return http.Response(jsonEncode(todayPayload()), 200);
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();
    expect(todayCalls, 1);

    await tester.tap(find.byTooltip('Обновить'));
    await tester.pumpAndSettle();
    expect(todayCalls, 2);
  });

  testWidgets('tapping task opens Object Detail', (tester) async {
    await tester.pumpWidget(
      buildToday(MockClient((request) async {
        if (request.url.path == '/today') {
          return http.Response(jsonEncode(todayPayload()), 200);
        }
        if (request.url.path == '/objects/task-1') {
          return http.Response(
            jsonEncode({
              'id': 'task-1',
              'kind': 'task',
              'title': 'Due today',
              'body': null,
              'provider': null,
              'external_id': null,
              'canonical_uri': null,
              'status': null,
              'start_at': null,
              'due_at': '2026-08-28T14:00:00+02:00',
              'metadata': {},
              'origin': 'user',
              'state': 'confirmed',
              'confidence': null,
              'created_at': '2026-08-28T08:00:00Z',
              'updated_at': '2026-08-28T08:00:00Z',
            }),
            200,
          );
        }
        if (request.url.path == '/objects/task-1/neighbors') {
          return http.Response(
            jsonEncode({'object_id': 'task-1', 'neighbors': []}),
            200,
          );
        }
        if (request.url.path == '/objects/task-1/context') {
          return http.Response(
            jsonEncode({
              'object': {
                'id': 'task-1',
                'kind': 'task',
                'title': 'Due today',
                'body': null,
                'provider': null,
                'external_id': null,
                'canonical_uri': null,
                'status': null,
                'start_at': null,
                'due_at': '2026-08-28T14:00:00+02:00',
                'metadata': {},
                'origin': 'user',
                'state': 'confirmed',
                'confidence': null,
                'created_at': '2026-08-28T08:00:00Z',
                'updated_at': '2026-08-28T08:00:00Z',
              },
              'edges': [],
              'neighbors': [],
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('Due today'));
    await tester.pumpAndSettle();

    expect(find.byType(ObjectDetailScreen), findsOneWidget);
    expect(find.text('Использовать как контекст задачи'), findsOneWidget);
  });

  test('Today parses the shared operational projection and does not infer overdue', () {
    final today = TodayOut.fromJson({
      'date': '2026-08-29',
      'timezone': 'Europe/Amsterdam',
      'day_start': '2026-08-29T00:00:00+02:00',
      'tasks': [
        _todayTask(
          id: 'task-early',
          title: 'Early today',
          dueAt: '2026-08-29T00:30:00+02:00',
          operationalState: 'actionable',
          overdue: true,
        ),
      ],
      'calendar_events': [],
      'notifications': [],
    });

    expect(today.tasks.single.operational?.operationalState, 'actionable');
    expect(today.tasks.single.operational?.isOverdue, isTrue);
    expect(today.tasks.single.id, 'task-early');
  });

  testWidgets('overdue cue follows operational.is_overdue', (tester) async {
    await tester.pumpWidget(
      buildToday(MockClient((request) async {
        if (request.url.path == '/today') {
          return http.Response(
            jsonEncode({
              'date': '2026-08-29',
              'timezone': 'Europe/Amsterdam',
              'day_start': '2026-08-29T00:00:00+02:00',
              'tasks': [
                _todayTask(
                  id: 'task-early',
                  title: 'Early today',
                  dueAt: '2026-08-29T00:30:00+02:00',
                  operationalState: 'blocked',
                  overdue: true,
                ),
                _todayTask(
                  id: 'task-before-midnight',
                  title: 'Before midnight',
                  dueAt: '2026-08-28T23:30:00+02:00',
                  operationalState: 'actionable',
                  overdue: false,
                ),
              ],
              'calendar_events': [],
              'notifications': [],
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    expect(find.text('Заблокировано'), findsOneWidget);
    expect(find.text('Просрочено'), findsOneWidget);
    expect(find.text('Можно действовать'), findsOneWidget);
    expect(find.text('Before midnight'), findsOneWidget);
  });

  testWidgets('server actionable cue ignores client-side relation hints', (
    tester,
  ) async {
    await tester.pumpWidget(
      buildToday(MockClient((request) async {
        if (request.url.path == '/today') {
          return http.Response(
            jsonEncode({
              'date': '2026-08-29',
              'timezone': 'Europe/Amsterdam',
              'day_start': '2026-08-29T00:00:00+02:00',
              'tasks': [
                {
                  ..._todayTask(
                    id: 'task-proposed',
                    title: 'Still actionable',
                    dueAt: '2026-08-29T18:00:00+02:00',
                    operationalState: 'actionable',
                  ),
                  'proposed_waiting_on': 'Olga',
                },
              ],
              'calendar_events': [],
              'notifications': [],
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    expect(find.text('Можно действовать'), findsOneWidget);
    expect(find.text('Ждём'), findsNothing);
    expect(find.text('Просрочено'), findsNothing);
  });

  testWidgets('proposed task shows marker', (tester) async {
    await tester.pumpWidget(
      buildToday(MockClient((request) async {
        if (request.url.path == '/today') {
          return http.Response(
            jsonEncode(todayPayload(
              tasks: [
                {
                  'id': 'task-proposed',
                  'kind': 'task',
                  'title': 'Proposed today',
                  'body': null,
                  'provider': null,
                  'external_id': null,
                  'canonical_uri': null,
                  'status': 'open',
                  'start_at': null,
                  'due_at': '2026-08-28T14:00:00+02:00',
                  'metadata': {},
                  'origin': 'agent',
                  'state': 'proposed',
                  'confidence': 0.9,
                  'created_at': '2026-08-28T08:00:00Z',
                  'updated_at': '2026-08-28T08:00:00Z',
                },
              ],
            )),
            200,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    expect(find.text('Proposed today'), findsOneWidget);
    expect(find.text('Предложено'), findsOneWidget);
  });

  testWidgets('calendar events use compact metadata without raw provider names',
      (tester) async {
    await tester.pumpWidget(
      buildToday(MockClient((request) async {
        if (request.url.path == '/today') {
          return http.Response(
            jsonEncode({
              'date': '2026-08-31',
              'timezone': 'Europe/Moscow',
              'day_start': '2026-08-31T00:00:00+03:00',
              'tasks': [
                {
                  'id': 'task-proposed',
                  'kind': 'task',
                  'title': 'Proposed today',
                  'body': null,
                  'provider': null,
                  'external_id': null,
                  'canonical_uri': null,
                  'status': 'open',
                  'start_at': null,
                  'due_at': '2026-08-31T14:00:00+03:00',
                  'metadata': {},
                  'origin': 'agent',
                  'state': 'proposed',
                  'confidence': 0.9,
                  'created_at': '2026-08-31T08:00:00Z',
                  'updated_at': '2026-08-31T08:00:00Z',
                },
              ],
              'calendar_events': [
                {
                  'id': 'event-yandex',
                  'kind': 'event',
                  'title': 'Yandex standup',
                  'body': null,
                  'provider': 'yandex_calendar',
                  'external_id': 'ycal-1',
                  'canonical_uri': null,
                  'status': null,
                  'start_at': '2026-08-31T18:00:00+03:00',
                  'due_at': '2026-08-31T19:00:00+03:00',
                  'metadata': {},
                  'origin': 'source',
                  'state': 'observed',
                  'confidence': null,
                  'created_at': '2026-08-31T08:00:00Z',
                  'updated_at': '2026-08-31T08:00:00Z',
                },
                {
                  'id': 'event-google',
                  'kind': 'event',
                  'title': 'Weekly sync',
                  'body': null,
                  'provider': 'google_calendar',
                  'external_id': 'primary:evt-g',
                  'canonical_uri': null,
                  'status': null,
                  'start_at': '2026-08-31T15:30:00+03:00',
                  'due_at': '2026-08-31T16:30:00+03:00',
                  'metadata': {},
                  'origin': 'source',
                  'state': 'observed',
                  'confidence': null,
                  'created_at': '2026-08-31T08:00:00Z',
                  'updated_at': '2026-08-31T08:00:00Z',
                },
              ],
              'notifications': [],
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    expect(find.text('Yandex standup'), findsOneWidget);
    expect(find.text('Weekly sync'), findsOneWidget);
    expect(find.text('Предложено'), findsOneWidget);
    expect(find.textContaining('yandex_calendar'), findsNothing);
    expect(find.textContaining('google_calendar'), findsNothing);
    expect(find.textContaining('Яндекс Календарь'), findsNothing);
    expect(find.textContaining('Google Календарь'), findsNothing);
    expect(find.byKey(const Key('source_mark_yandex')), findsOneWidget);
    expect(find.byKey(const Key('source_mark_google')), findsOneWidget);
    expect(find.byIcon(Icons.calendar_month), findsNothing);
    expect(find.byIcon(Icons.forum), findsNothing);
  });

  testWidgets('passive refresh loads newer today snapshot without navigation',
      (tester) async {
    int todayCalls = 0;
    await tester.pumpWidget(
      buildToday(
        MockClient((request) async {
          if (request.url.path == '/today') {
            todayCalls++;
            final events = todayCalls == 1
                ? [
                    {
                      'id': 'event-a',
                      'kind': 'event',
                      'title': 'Morning standup',
                      'body': null,
                      'provider': 'google_calendar',
                      'external_id': null,
                      'canonical_uri': null,
                      'status': null,
                      'start_at': '2026-08-28T09:00:00+02:00',
                      'due_at': '2026-08-28T09:30:00+02:00',
                      'metadata': {},
                      'origin': 'source',
                      'state': 'observed',
                      'confidence': null,
                      'created_at': '2026-08-28T08:00:00Z',
                      'updated_at': '2026-08-28T08:00:00Z',
                    },
                  ]
                : [
                    {
                      'id': 'event-a',
                      'kind': 'event',
                      'title': 'Morning standup',
                      'body': null,
                      'provider': 'google_calendar',
                      'external_id': null,
                      'canonical_uri': null,
                      'status': null,
                      'start_at': '2026-08-28T09:00:00+02:00',
                      'due_at': '2026-08-28T09:30:00+02:00',
                      'metadata': {},
                      'origin': 'source',
                      'state': 'observed',
                      'confidence': null,
                      'created_at': '2026-08-28T08:00:00Z',
                      'updated_at': '2026-08-28T08:00:00Z',
                    },
                    {
                      'id': 'event-b',
                      'kind': 'event',
                      'title': 'Afternoon review',
                      'body': null,
                      'provider': 'yandex_calendar',
                      'external_id': null,
                      'canonical_uri': null,
                      'status': null,
                      'start_at': '2026-08-28T15:00:00+02:00',
                      'due_at': '2026-08-28T16:00:00+02:00',
                      'metadata': {},
                      'origin': 'source',
                      'state': 'observed',
                      'confidence': null,
                      'created_at': '2026-08-28T08:00:00Z',
                      'updated_at': '2026-08-28T08:00:00Z',
                    },
                  ];
            return http.Response(
              jsonEncode(
                  todayPayload(calendarEvents: events, notifications: [])),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
        passiveRefreshInterval: const Duration(seconds: 5),
      ),
    );
    for (var i = 0; i < 50; i++) {
      await tester.pump(const Duration(milliseconds: 10));
      if (find.text('Morning standup').evaluate().isNotEmpty) {
        break;
      }
    }

    expect(todayCalls, 1);
    expect(find.text('Morning standup'), findsOneWidget);
    expect(find.text('Afternoon review'), findsNothing);

    await tester.pump(const Duration(seconds: 5));
    await tester.pump();

    expect(todayCalls, 2);
    expect(find.text('Afternoon review'), findsOneWidget);
  });

  testWidgets('manual source refresh failure resets refreshing state',
      (tester) async {
    await tester.pumpWidget(
      buildToday(MockClient((request) async {
        if (request.url.path == '/today') {
          return http.Response(jsonEncode(todayPayload()), 200);
        }
        if (request.method == 'POST' &&
            request.url.path.endsWith('/sources/sync')) {
          return http.Response(jsonEncode({'detail': 'sync failed'}), 500);
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();
    expect(find.text('Due today'), findsOneWidget);

    await tester.tap(find.byTooltip('Обновить'));
    await tester.pumpAndSettle();

    expect(find.text('Due today'), findsOneWidget);
    expect(find.byTooltip('Обновить'), findsOneWidget);
  });

  testWidgets('later passive refresh still occurs after manual refresh failure',
      (tester) async {
    int todayCalls = 0;
    var syncFails = true;
    await tester.pumpWidget(
      buildToday(
        MockClient((request) async {
          if (request.url.path == '/today') {
            todayCalls++;
            return http.Response(
              jsonEncode(todayPayload(
                tasks: [
                  {
                    'id': 'task-1',
                    'kind': 'task',
                    'title':
                        todayCalls == 1 ? 'Due today' : 'Updated today task',
                    'body': null,
                    'provider': null,
                    'external_id': null,
                    'canonical_uri': null,
                    'status': null,
                    'start_at': null,
                    'due_at': '2026-08-28T14:00:00+02:00',
                    'metadata': {},
                    'origin': 'user',
                    'state': 'confirmed',
                    'confidence': null,
                    'created_at': '2026-08-28T08:00:00Z',
                    'updated_at': '2026-08-28T08:00:00Z',
                  },
                ],
                notifications: [],
              )),
              200,
            );
          }
          if (request.method == 'POST' &&
              request.url.path.endsWith('/sources/sync')) {
            if (syncFails) {
              return http.Response(jsonEncode({'detail': 'sync failed'}), 500);
            }
            return http.Response(
                jsonEncode({'triggered': [], 'count': 0}), 200);
          }
          if (request.url.path.endsWith('/sources/status')) {
            return http.Response(jsonEncode({'sources': []}), 200);
          }
          return http.Response('{}', 404);
        }),
        passiveRefreshInterval: const Duration(seconds: 5),
      ),
    );
    await tester.pumpAndSettle();
    expect(todayCalls, 1);

    await tester.tap(find.byTooltip('Обновить'));
    await tester.pumpAndSettle();
    syncFails = false;
    expect(find.text('Due today'), findsOneWidget);

    await tester.pump(const Duration(seconds: 5));
    await tester.pump();

    expect(todayCalls, greaterThan(1));
    expect(find.text('Updated today task'), findsOneWidget);
  });

  testWidgets('overlap with manual source refresh does not kill polling',
      (tester) async {
    int todayCalls = 0;
    await tester.pumpWidget(
      buildToday(
        MockClient((request) async {
          if (request.url.path == '/today') {
            todayCalls++;
            return http.Response(
              jsonEncode(todayPayload(
                tasks: [
                  {
                    'id': 'task-1',
                    'kind': 'task',
                    'title':
                        todayCalls <= 2 ? 'Due today' : 'Passive updated task',
                    'body': null,
                    'provider': null,
                    'external_id': null,
                    'canonical_uri': null,
                    'status': null,
                    'start_at': null,
                    'due_at': '2026-08-28T14:00:00+02:00',
                    'metadata': {},
                    'origin': 'user',
                    'state': 'confirmed',
                    'confidence': null,
                    'created_at': '2026-08-28T08:00:00Z',
                    'updated_at': '2026-08-28T08:00:00Z',
                  },
                ],
                notifications: [],
              )),
              200,
            );
          }
          if (request.method == 'POST' &&
              request.url.path.endsWith('/sources/sync')) {
            await Future<void>.delayed(const Duration(milliseconds: 200));
            return http.Response(
                jsonEncode({'triggered': [], 'count': 0}), 200);
          }
          if (request.url.path.endsWith('/sources/status')) {
            await Future<void>.delayed(const Duration(milliseconds: 200));
            return http.Response(jsonEncode({'sources': []}), 200);
          }
          return http.Response('{}', 404);
        }),
        passiveRefreshInterval: const Duration(seconds: 5),
      ),
    );
    await tester.pumpAndSettle();
    expect(todayCalls, 1);

    await tester.tap(find.byTooltip('Обновить'));
    await tester.pump(const Duration(seconds: 5));
    await tester.pump();

    expect(todayCalls, greaterThan(2));
    expect(find.text('Passive updated task'), findsOneWidget);
  });

  testWidgets('passive refresh continues after inactive without changing tabs',
      (tester) async {
    int todayCalls = 0;
    await tester.pumpWidget(
      buildToday(
        MockClient((request) async {
          if (request.url.path == '/today') {
            todayCalls++;
            return http.Response(
              jsonEncode(todayPayload(
                tasks: [
                  {
                    'id': 'task-1',
                    'kind': 'task',
                    'title':
                        todayCalls <= 1 ? 'Due today' : 'Updated today task',
                    'body': null,
                    'provider': null,
                    'external_id': null,
                    'canonical_uri': null,
                    'status': null,
                    'start_at': null,
                    'due_at': '2026-08-28T14:00:00+02:00',
                    'metadata': {},
                    'origin': 'user',
                    'state': 'confirmed',
                    'confidence': null,
                    'created_at': '2026-08-28T08:00:00Z',
                    'updated_at': '2026-08-28T08:00:00Z',
                  },
                ],
                notifications: [],
              )),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
        passiveRefreshInterval: const Duration(seconds: 5),
      ),
    );
    await tester.pumpAndSettle();
    expect(todayCalls, 1);
    expect(find.text('Due today'), findsOneWidget);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    await tester.pump(const Duration(seconds: 5));
    await tester.pump();

    expect(todayCalls, greaterThan(1));
    expect(find.text('Updated today task'), findsOneWidget);
  });

  testWidgets('hidden pauses passive refresh until resumed', (tester) async {
    int todayCalls = 0;
    await tester.pumpWidget(
      buildToday(
        MockClient((request) async {
          if (request.url.path == '/today') {
            todayCalls++;
            return http.Response(
              jsonEncode(todayPayload(
                tasks: [
                  {
                    'id': 'task-1',
                    'kind': 'task',
                    'title': todayCalls <= 1
                        ? 'Hidden pause task'
                        : 'Hidden resume task',
                    'body': null,
                    'provider': null,
                    'external_id': null,
                    'canonical_uri': null,
                    'status': null,
                    'start_at': null,
                    'due_at': '2026-08-28T14:00:00+02:00',
                    'metadata': {},
                    'origin': 'user',
                    'state': 'confirmed',
                    'confidence': null,
                    'created_at': '2026-08-28T08:00:00Z',
                    'updated_at': '2026-08-28T08:00:00Z',
                  },
                ],
                notifications: [],
              )),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
        passiveRefreshInterval: const Duration(seconds: 5),
      ),
    );
    await tester.pumpAndSettle();
    expect(todayCalls, 1);
    expect(find.text('Hidden pause task'), findsOneWidget);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
    await tester.pump(const Duration(seconds: 5));
    await tester.pump();
    expect(todayCalls, 1);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    for (var i = 0; i < 50; i++) {
      await tester.pump(const Duration(milliseconds: 10));
      if (find.text('Hidden resume task').evaluate().isNotEmpty) {
        break;
      }
    }
    expect(todayCalls, greaterThan(1));
    expect(find.text('Hidden resume task'), findsOneWidget);
  });
}
