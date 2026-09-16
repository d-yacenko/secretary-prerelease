import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/capture/capture_controller.dart';
import 'package:personal_secretary/inbox/inbox_feed_merge.dart';
import 'package:personal_secretary/inbox/inbox_screen.dart';
import 'package:personal_secretary/ui/inbox_date_groups.dart';
import 'package:shared_preferences/shared_preferences.dart';

http.Response jsonRes(Object body, [int status = 200]) {
  return http.Response.bytes(
    utf8.encode(jsonEncode(body)),
    status,
    headers: {'content-type': 'application/json; charset=utf-8'},
  );
}

Map<String, dynamic> sourceRow({
  required String id,
  required String title,
  required String feedAt,
  String? primaryAt,
  String kind = 'email',
  String provider = 'gmail',
}) {
  return {
    'id': id,
    'title': title,
    'kind': kind,
    'provider': provider,
    'state': 'observed',
    'status': null,
    'origin': 'source',
    'primary_at': primaryAt ?? feedAt,
    'feed_at': feedAt,
    'excerpt': 'excerpt',
  };
}

Map<String, dynamic> inboxPayload({
  required List<Map<String, dynamic>> sources,
  String? cursor,
  bool hasMore = false,
}) {
  return {
    'unresolved_notifications': [],
    'recent_source_objects': sources,
    'source_sync_status': [],
    'recent_next_cursor': cursor,
    'recent_has_more': hasMore,
  };
}

Widget pumpInbox(
  SecretaryApiClient apiClient, {
  Duration passiveRefreshInterval = const Duration(days: 1),
  Duration? sourceRefreshTimeout,
  Duration? sourceRefreshPollInterval,
}) {
  final auth = AuthController(
    apiClient: apiClient,
    tokenStore: FakeTokenStore(),
    serverUrlStore: FakeServerUrlStore(),
  );
  auth.status = AuthStatus.authenticated;
  return MaterialApp(
    home: Scaffold(
      body: InboxScreen(
        apiClient: apiClient,
        authController: auth,
        captureController: CaptureController(
          apiClient: apiClient,
          authController: auth,
        ),
        passiveRefreshInterval: passiveRefreshInterval,
        sourceRefreshTimeout: sourceRefreshTimeout,
        sourceRefreshPollInterval: sourceRefreshPollInterval,
      ),
    ),
  );
}

ScrollPosition inboxFeedPosition(WidgetTester tester) {
  return tester
      .state<ScrollableState>(
        find.descendant(
          of: find.byKey(const Key('inbox_feed_list')),
          matching: find.byType(Scrollable),
        ),
      )
      .position;
}

http.Response okSync() => jsonRes({'triggered': <String>[], 'count': 0});

http.Response okStatus() => jsonRes({'sources': <Object>[]});

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  test('merge preserves tail and inserts new head once', () {
    final older = InboxSourceObjectOut(
      id: 'old',
      title: 'Old',
      kind: 'email',
      provider: 'gmail',
      origin: 'source',
      state: 'observed',
      status: null,
      primaryAt: '2026-09-07T10:00:00Z',
      feedAt: '2026-09-07T10:00:00Z',
      excerpt: null,
    );
    final current = InboxSourceObjectOut(
      id: 'now',
      title: 'Now',
      kind: 'email',
      provider: 'gmail',
      origin: 'source',
      state: 'observed',
      status: null,
      primaryAt: '2026-09-08T10:00:00Z',
      feedAt: '2026-09-08T10:00:00Z',
      excerpt: null,
    );
    final fresh = InboxSourceObjectOut(
      id: 'new',
      title: 'New',
      kind: 'email',
      provider: 'gmail',
      origin: 'source',
      state: 'observed',
      status: null,
      primaryAt: '2026-09-08T12:00:00Z',
      feedAt: '2026-09-08T12:00:00Z',
      excerpt: null,
    );
    final merged = mergeInboxFeedHead(
      existing: [current, older],
      firstPage: [fresh, current],
      preserveTail: true,
    );
    expect(merged.map((item) => item.id).toList(), ['new', 'now', 'old']);
  });

  testWidgets('separator uses left and right lines around the date label',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Column(
            children: [
              InboxDateSeparator(
                entry: InboxDateSeparatorEntry(
                  date: DateTime(2026, 9, 8),
                  label: formatInboxDateSeparator(DateTime(2026, 9, 8)),
                ),
              ),
              InboxDateSeparator(
                entry: InboxDateSeparatorEntry(
                  date: DateTime(2026, 9, 5),
                  label: formatInboxDateSeparator(DateTime(2026, 9, 5)),
                ),
              ),
            ],
          ),
        ),
      ),
    );
    expect(find.byType(Divider), findsNWidgets(4));
    expect(find.byKey(const Key('inbox_date_separator_line_start')), findsNWidgets(2));
    expect(find.byKey(const Key('inbox_date_separator_line_end')), findsNWidgets(2));
    final weekday = tester.widget<Text>(find.textContaining('вторник'));
    expect(weekday.style?.color, isNotNull);
    final weekend = tester.widget<Text>(find.textContaining('суббот'));
    expect(weekend.style?.color, isNotNull);
    expect(weekend.style?.color, weekday.style?.color);
    expect(weekday.style?.fontWeight, FontWeight.w500);
    expect(weekend.style?.fontWeight, FontWeight.w600);

    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pump();
    expect(tester.takeException(), isNull);
  });

  testWidgets('infinite scroll loads one continuation and keeps labels',
      (tester) async {
    tester.view.physicalSize = const Size(800, 360);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var inboxCalls = 0;
    var feedCalls = 0;
    final labelBodies = <String>[];
    final firstPage = [
      for (var index = 0; index < 4; index++)
        sourceRow(
          id: 'p1-$index',
          title: 'First page $index',
          feedAt: '2026-09-08T${(12 - index).toString().padLeft(2, '0')}:00:00Z',
        ),
    ];

    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox' &&
            !request.url.path.endsWith('/inbox/feed')) {
          inboxCalls++;
          return jsonRes(
            inboxPayload(
              sources: firstPage,
              cursor: 'cursor-1',
              hasMore: true,
            ),
          );
        }
        if (request.url.path.endsWith('/inbox/feed')) {
          feedCalls++;
          return jsonRes({
            'items': [
              sourceRow(
                id: 'c',
                title: 'Second page C',
                feedAt: '2026-09-07T10:00:00Z',
              ),
            ],
            'next_cursor': null,
            'has_more': false,
          });
        }
        if (request.url.path == '/labels/by-objects') {
          labelBodies.add(request.body);
          final ids = (jsonDecode(request.body) as Map)['object_ids'] as List;
          final objects = <String, List<Map<String, String>>>{};
          for (final id in ids) {
            objects[id as String] = [
              {'id': 'lab-$id', 'title': 'Label $id'},
            ];
          }
          return jsonRes({'objects': objects});
        }
        if (request.url.path == '/object-bookmarks/by-objects') {
          return jsonRes({'objects': {}});
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');

    await tester.pumpWidget(pumpInbox(apiClient));
    await tester.pumpAndSettle();
    expect(find.text('First page 0'), findsOneWidget);
    expect(inboxCalls, 1);

    final position = inboxFeedPosition(tester);
    position.jumpTo(position.maxScrollExtent);
    await tester.pumpAndSettle();
    expect(find.text('Second page C'), findsOneWidget);
    expect(feedCalls, 1);
    expect(jsonDecode(labelBodies.first)['object_ids'],
        [for (var index = 0; index < 4; index++) 'p1-$index']);
    expect(labelBodies.length, 2);
    expect(jsonDecode(labelBodies.last)['object_ids'], ['c']);

    await tester.drag(find.byKey(const Key('inbox_feed_list')), const Offset(0, -400));
    await tester.pumpAndSettle();
    expect(feedCalls, 1);
  });

  testWidgets('load-more error keeps cards and retry works', (tester) async {
    var feedCalls = 0;
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox' &&
            !request.url.path.endsWith('/inbox/feed')) {
          return jsonRes(
            inboxPayload(
              sources: [
                sourceRow(
                  id: 'a',
                  title: 'Visible card',
                  feedAt: '2026-09-08T12:00:00Z',
                ),
              ],
              cursor: 'cursor-1',
              hasMore: true,
            ),
          );
        }
        if (request.url.path.endsWith('/inbox/feed') ||
            request.url.path == '/inbox/feed') {
          feedCalls++;
          if (feedCalls == 1) {
            return jsonRes({'detail': 'boom'}, 500);
          }
          return jsonRes({
            'items': [
              sourceRow(
                id: 'b',
                title: 'Recovered page',
                feedAt: '2026-09-07T10:00:00Z',
              ),
            ],
            'next_cursor': null,
            'has_more': false,
          });
        }
        if (request.url.path == '/labels/by-objects') {
          return jsonRes({'objects': {}});
        }
        if (request.url.path == '/object-bookmarks/by-objects') {
          return jsonRes({'objects': {}});
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    await tester.pumpWidget(pumpInbox(apiClient));
    await tester.pumpAndSettle();
    expect(find.text('Visible card'), findsOneWidget);
    expect(find.byKey(const Key('inbox_load_more_retry')), findsOneWidget);
    await tester.tap(find.byKey(const Key('inbox_load_more_retry')));
    await tester.pumpAndSettle();
    expect(find.text('Recovered page'), findsOneWidget);
  });

  testWidgets('future event grouped by feed_at still shows primary date',
      (tester) async {
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox') {
          return jsonRes(
            inboxPayload(
              sources: [
                sourceRow(
                  id: 'evt',
                  title: 'December meeting',
                  kind: 'event',
                  provider: 'google_calendar',
                  feedAt: '2026-09-08T12:00:00Z',
                  primaryAt: '2026-12-07T06:30:00Z',
                ),
              ],
            ),
          );
        }
        if (request.url.path == '/labels/by-objects') {
          return jsonRes({'objects': {}});
        }
        if (request.url.path == '/object-bookmarks/by-objects') {
          return jsonRes({'objects': {}});
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    await tester.pumpWidget(pumpInbox(apiClient));
    await tester.pumpAndSettle();
    expect(find.textContaining('08 сентября'), findsOneWidget);
    expect(find.textContaining('07.12.2026'), findsOneWidget);
    expect(find.byKey(const Key('inbox_date_separator_line_start')), findsOneWidget);
    expect(find.byKey(const Key('inbox_date_separator_line_end')), findsOneWidget);
  });

  testWidgets('manual source refresh keeps continuation tail and scroll',
      (tester) async {
    tester.view.physicalSize = const Size(800, 360);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var inboxCalls = 0;
    final feedCursors = <String?>[];
    final firstPage = [
      sourceRow(
        id: 'p1-0',
        title: 'First page 0',
        feedAt: '2026-09-08T12:00:00Z',
      ),
    ];
    final refreshedHead = [
      sourceRow(
        id: 'head',
        title: 'New head',
        feedAt: '2026-09-08T13:00:00Z',
      ),
      ...firstPage,
    ];

    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox' &&
            !request.url.path.endsWith('/inbox/feed')) {
          inboxCalls++;
          return jsonRes(
            inboxPayload(
              sources: inboxCalls == 1 ? firstPage : refreshedHead,
              cursor: 'cursor-1',
              hasMore: true,
            ),
          );
        }
        if (request.url.path.endsWith('/inbox/feed')) {
          feedCursors.add(request.url.queryParameters['cursor']);
          return jsonRes({
            'items': [
              sourceRow(
                id: 'c',
                title: 'Second page C',
                feedAt: '2026-09-07T10:00:00Z',
              ),
            ],
            'next_cursor': 'deep-cursor',
            'has_more': false,
          });
        }
        if (request.method == 'POST' &&
            request.url.path.endsWith('/sources/sync')) {
          return okSync();
        }
        if (request.url.path.endsWith('/sources/status')) {
          return okStatus();
        }
        if (request.url.path == '/labels/by-objects') {
          return jsonRes({'objects': {}});
        }
        if (request.url.path == '/object-bookmarks/by-objects') {
          return jsonRes({'objects': {}});
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    await tester.pumpWidget(
      pumpInbox(
        apiClient,
        sourceRefreshTimeout: const Duration(milliseconds: 50),
        sourceRefreshPollInterval: const Duration(milliseconds: 10),
      ),
    );
    await tester.pumpAndSettle();
    inboxFeedPosition(tester).jumpTo(inboxFeedPosition(tester).maxScrollExtent);
    await tester.pumpAndSettle();
    expect(find.text('Second page C'), findsOneWidget);
    expect(feedCursors, ['cursor-1']);
    final pixelsBefore = inboxFeedPosition(tester).pixels;
    expect(pixelsBefore, greaterThan(0));

    await tester.tap(find.byKey(const Key('inbox_refresh_button')));
    await tester.pumpAndSettle();

    expect(find.text('New head'), findsOneWidget);
    expect(inboxFeedPosition(tester).pixels, isNot(0));
    await tester.scrollUntilVisible(
      find.text('Second page C'),
      200,
      scrollable: find.descendant(
        of: find.byKey(const Key('inbox_feed_list')),
        matching: find.byType(Scrollable),
      ),
    );
    expect(find.text('Second page C'), findsOneWidget);
    expect(find.text('First page 0'), findsOneWidget);
    expect(feedCursors, ['cursor-1']);
  });

  testWidgets('note intake refresh keeps continuation tail', (tester) async {
    tester.view.physicalSize = const Size(800, 360);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var inboxCalls = 0;
    var feedCalls = 0;
    final firstPage = [
      sourceRow(
        id: 'p1-0',
        title: 'First page 0',
        feedAt: '2026-09-08T12:00:00Z',
      ),
    ];

    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox' &&
            !request.url.path.endsWith('/inbox/feed')) {
          inboxCalls++;
          return jsonRes(
            inboxPayload(
              sources: inboxCalls == 1
                  ? firstPage
                  : [
                      sourceRow(
                        id: 'note-1',
                        title: 'Intake note',
                        feedAt: '2026-09-08T13:00:00Z',
                        kind: 'note',
                        provider: 'upload',
                      ),
                      ...firstPage,
                    ],
              cursor: 'cursor-1',
              hasMore: true,
            ),
          );
        }
        if (request.url.path.endsWith('/inbox/feed')) {
          feedCalls++;
          return jsonRes({
            'items': [
              sourceRow(
                id: 'c',
                title: 'Second page C',
                feedAt: '2026-09-07T10:00:00Z',
              ),
            ],
            'next_cursor': null,
            'has_more': false,
          });
        }
        if (request.url.path == '/capture/note') {
          return jsonRes({'note_id': 'n1'}, 201);
        }
        if (request.url.path == '/labels/by-objects') {
          return jsonRes({'objects': {}});
        }
        if (request.url.path == '/object-bookmarks/by-objects') {
          return jsonRes({'objects': {}});
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    await tester.pumpWidget(pumpInbox(apiClient));
    await tester.pumpAndSettle();
    inboxFeedPosition(tester).jumpTo(inboxFeedPosition(tester).maxScrollExtent);
    await tester.pumpAndSettle();
    expect(find.text('Second page C'), findsOneWidget);
    expect(feedCalls, 1);

    await tester.enterText(
      find.byKey(const Key('inbox_link_input')),
      'Идея после скролла',
    );
    await tester.tap(find.byKey(const Key('inbox_link_add_button')));
    await tester.pumpAndSettle();

    expect(find.text('Intake note'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.text('Second page C'),
      200,
      scrollable: find.descendant(
        of: find.byKey(const Key('inbox_feed_list')),
        matching: find.byType(Scrollable),
      ),
    );
    expect(find.text('Second page C'), findsOneWidget);
    expect(feedCalls, 1);
  });

  testWidgets('passive refresh keeps continuation tail', (tester) async {
    tester.view.physicalSize = const Size(800, 360);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var inboxCalls = 0;
    var feedCalls = 0;
    final firstPage = [
      sourceRow(
        id: 'p1-0',
        title: 'First page 0',
        feedAt: '2026-09-08T12:00:00Z',
      ),
    ];

    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox' &&
            !request.url.path.endsWith('/inbox/feed')) {
          inboxCalls++;
          return jsonRes(
            inboxPayload(
              sources: inboxCalls == 1
                  ? firstPage
                  : [
                      sourceRow(
                        id: 'head',
                        title: 'Passive head',
                        feedAt: '2026-09-08T13:00:00Z',
                      ),
                      ...firstPage,
                    ],
              cursor: 'cursor-1',
              hasMore: true,
            ),
          );
        }
        if (request.url.path.endsWith('/inbox/feed')) {
          feedCalls++;
          return jsonRes({
            'items': [
              sourceRow(
                id: 'c',
                title: 'Second page C',
                feedAt: '2026-09-07T10:00:00Z',
              ),
            ],
            'next_cursor': null,
            'has_more': false,
          });
        }
        if (request.url.path == '/labels/by-objects') {
          return jsonRes({'objects': {}});
        }
        if (request.url.path == '/object-bookmarks/by-objects') {
          return jsonRes({'objects': {}});
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    await tester.pumpWidget(
      pumpInbox(
        apiClient,
        passiveRefreshInterval: const Duration(milliseconds: 40),
      ),
    );
    await tester.pumpAndSettle();
    inboxFeedPosition(tester).jumpTo(inboxFeedPosition(tester).maxScrollExtent);
    await tester.pumpAndSettle();
    expect(find.text('Second page C'), findsOneWidget);
    await tester.pump(const Duration(milliseconds: 80));
    await tester.pumpAndSettle();
    expect(find.text('Passive head'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.text('Second page C'),
      200,
      scrollable: find.descendant(
        of: find.byKey(const Key('inbox_feed_list')),
        matching: find.byType(Scrollable),
      ),
    );
    expect(find.text('Second page C'), findsOneWidget);
    expect(feedCalls, 1);
  });
}
