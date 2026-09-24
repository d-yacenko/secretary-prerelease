import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/capture/capture_controller.dart';
import 'package:personal_secretary/inbox/inbox_screen.dart';
import 'package:personal_secretary/ui/object_bookmark.dart';
import 'package:personal_secretary/ui/object_bookmark_controller.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('collapsed stack with no child bookmarks has no aggregate', (
    tester,
  ) async {
    final harness = await _pumpStack(tester, bookmarks: const {});
    expect(find.byKey(const Key('inbox_stack_bookmarks_stack-ui')), findsNothing);
    expect(harness.stackBookmarkWrites, isEmpty);
  });

  testWidgets('one red child shows one red filled stack indicator', (
    tester,
  ) async {
    await _pumpStack(tester, bookmarks: const {'m1': 'red'});
    final glyph = tester.widget<ObjectBookmarkGlyph>(
      find.byKey(const Key('inbox_stack_bookmark_stack-ui_red')),
    );
    expect(glyph.fillColor, bookmarkTokenColor('red', _scheme(tester)));
    expect(
      find.byKey(const Key('inbox_stack_bookmark_overflow_stack-ui')),
      findsNothing,
    );
    expect(
      find.byTooltip('Закладки сообщений в переписке: Красный ×1'),
      findsOneWidget,
    );
  });

  testWidgets('the same aggregate stays visible when the stack is expanded', (
    tester,
  ) async {
    await _pumpStack(tester, bookmarks: const {'m1': 'red'});
    await tester.tap(find.byKey(const Key('inbox_conversation_stack_stack-ui')));
    await tester.pump();
    expect(
      find.byKey(const Key('inbox_conversation_stack_chevron_up_stack-ui')),
      findsOneWidget,
    );
    expect(
      find.byKey(const Key('inbox_stack_bookmark_stack-ui_red')),
      findsOneWidget,
    );
  });

  testWidgets('distinct colors keep first-seen child order', (tester) async {
    await _pumpStack(
      tester,
      bookmarks: const {'m1': 'red', 'm2': 'blue', 'm3': 'green'},
      count: 3,
    );
    final green = tester.getTopLeft(
      find.byKey(const Key('inbox_stack_bookmark_stack-ui_green')),
    );
    final blue = tester.getTopLeft(
      find.byKey(const Key('inbox_stack_bookmark_stack-ui_blue')),
    );
    final red = tester.getTopLeft(
      find.byKey(const Key('inbox_stack_bookmark_stack-ui_red')),
    );
    expect(green.dx, lessThan(blue.dx));
    expect(blue.dx, lessThan(red.dx));
  });

  testWidgets('more than three colors show three glyphs and +N', (tester) async {
    await _pumpStack(
      tester,
      bookmarks: const {
        'm1': 'red',
        'm2': 'orange',
        'm3': 'yellow',
        'm4': 'green',
        'm5': 'blue',
      },
      count: 5,
    );
    expect(find.byKey(const Key('inbox_stack_bookmark_stack-ui_blue')), findsOneWidget);
    expect(
      find.byKey(const Key('inbox_stack_bookmark_stack-ui_green')),
      findsOneWidget,
    );
    expect(
      find.byKey(const Key('inbox_stack_bookmark_stack-ui_yellow')),
      findsOneWidget,
    );
    expect(find.byKey(const Key('inbox_stack_bookmark_stack-ui_red')), findsNothing);
    expect(find.text('+2'), findsOneWidget);
  });

  testWidgets('duplicate colors collapse to one glyph', (tester) async {
    await _pumpStack(
      tester,
      bookmarks: const {'m1': 'red', 'm2': 'red', 'm3': 'blue'},
      count: 3,
    );
    expect(find.byKey(const Key('inbox_stack_bookmark_stack-ui_red')), findsOneWidget);
    expect(find.byKey(const Key('inbox_stack_bookmark_stack-ui_blue')), findsOneWidget);
    expect(
      find.byTooltip('Закладки сообщений в переписке: Синий ×1, Красный ×2'),
      findsOneWidget,
    );
  });

  testWidgets('clearing a child bookmark updates the aggregate without reload', (
    tester,
  ) async {
    final harness = await _pumpStack(tester, bookmarks: const {'m1': 'red'});
    expect(harness.inboxGets(), 1);
    expect(find.byKey(const Key('inbox_stack_bookmark_stack-ui_red')), findsOneWidget);

    await harness.bookmarks.setColor('m1', 'blue');
    await tester.pump();
    expect(find.byKey(const Key('inbox_stack_bookmark_stack-ui_blue')), findsOneWidget);
    expect(find.byKey(const Key('inbox_stack_bookmark_stack-ui_red')), findsNothing);
    expect(harness.inboxGets(), 1);

    await harness.bookmarks.clear('m1');
    await tester.pump();
    expect(find.byKey(const Key('inbox_stack_bookmarks_stack-ui')), findsNothing);
    expect(harness.inboxGets(), 1);
  });

  testWidgets('narrow and desktop widths do not overflow', (tester) async {
    for (final width in [360.0, 900.0]) {
      await _pumpStack(
        tester,
        bookmarks: const {
          'm1': 'red',
          'm2': 'orange',
          'm3': 'yellow',
          'm4': 'green',
        },
        count: 4,
        width: width,
        longTitle: true,
      );
      expect(tester.takeException(), isNull);
      expect(find.text('+1'), findsOneWidget);
      expect(
        find.byKey(const Key('inbox_conversation_stack_chevron_down_stack-ui')),
        findsOneWidget,
      );
    }
  });

  testWidgets('the aggregate does not write a stack bookmark or replace toggle', (
    tester,
  ) async {
    final harness = await _pumpStack(tester, bookmarks: const {'m1': 'red'});
    expect(
      find.descendant(
        of: find.byKey(const Key('inbox_conversation_stack_stack-ui')),
        matching: find.byType(PopupMenuButton<String>),
      ),
      findsNothing,
    );

    await tester.tap(find.byKey(const Key('inbox_stack_bookmark_stack-ui_red')));
    await tester.pump();

    expect(
      find.byKey(const Key('inbox_conversation_stack_chevron_up_stack-ui')),
      findsOneWidget,
    );
    expect(harness.stackBookmarkWrites, isEmpty);
    expect(
      find.descendant(
        of: find.byKey(const Key('inbox_conversation_stack_stack-ui')),
        matching: find.byType(PopupMenuButton<String>),
      ),
      findsNothing,
    );
  });
}

class _Harness {
  _Harness({
    required this.bookmarks,
    required this.inboxGets,
    required this.stackBookmarkWrites,
  });

  final ObjectBookmarkController bookmarks;
  final int Function() inboxGets;
  final List<String> stackBookmarkWrites;
}

Future<_Harness> _pumpStack(
  WidgetTester tester, {
  required Map<String, String> bookmarks,
  int count = 2,
  double width = 800,
  bool longTitle = false,
}) async {
  tester.view.physicalSize = Size(width, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  });

  final ids = [for (var i = 1; i <= count; i++) 'm$i'];
  final objects = [
    for (var i = 0; i < ids.length; i++)
      {
        'id': ids[i],
        'title': longTitle ? 'Очень длинный заголовок переписки ' * 4 : ids[i],
        'kind': 'chat_message',
        'provider': 'telegram',
        'origin': 'source',
        'state': 'observed',
        'status': null,
        'primary_at': '2026-09-15T16:${(59 - i).toString().padLeft(2, '0')}:00Z',
        'feed_at': '2026-09-15T16:${(59 - i).toString().padLeft(2, '0')}:00Z',
        'excerpt': ids[i],
      },
  ];
  final label = longTitle ? 'Очень длинное имя переписки ' * 3 : 'BrainTor';
  final inbox = {
    'unresolved_notifications': <Object>[],
    'recent_source_objects': objects,
    'source_sync_status': <Object>[],
    'review_marker': null,
    'conversation_groups': [
      {
        'type': 'stack',
        'stack': {
          'stack_id': 'stack-ui',
          'fingerprint': 'stack-ui',
          'object_ids': ids,
          'display_object_ids': ids,
          'provider': 'telegram',
          'conversation_key': 'k',
          'conversation_label': label,
          'participants': [label],
          'message_count': ids.length,
          'start_at': objects.first['feed_at'],
          'end_at': objects.last['feed_at'],
          'summary': 'Короткое содержание.',
          'fallback_summary': 'Telegram, 2 сообщений.',
          'summary_status': 'current',
        },
      },
    ],
  };

  var inboxGets = 0;
  final writes = <String>[];
  final apiClient = SecretaryApiClient(
    httpClient: MockClient((request) async {
      if (request.url.path == '/inbox') {
        inboxGets += 1;
        return http.Response.bytes(
          utf8.encode(jsonEncode(inbox)),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }
      if (request.url.path.endsWith('/labels/by-objects')) {
        return http.Response.bytes(
          utf8.encode(jsonEncode({'objects': <String, Object>{}})),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }
      if (request.url.path.endsWith('/object-bookmarks/by-objects')) {
        return http.Response.bytes(
          utf8.encode(
            jsonEncode({
              'objects': {
                for (final entry in bookmarks.entries)
                  entry.key: {'color': entry.value},
              },
            }),
          ),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }
      if (request.method == 'PUT' || request.method == 'DELETE') {
        writes.add('${request.method} ${request.url.path}');
        if (request.method == 'DELETE') {
          return http.Response.bytes(
            utf8.encode('{}'),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        return http.Response.bytes(
          utf8.encode(request.body),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }
      return http.Response('{}', 404);
    }),
  );
  apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
  final auth = AuthController(
    apiClient: apiClient,
    tokenStore: FakeTokenStore(),
    serverUrlStore: FakeServerUrlStore(),
  );
  auth.status = AuthStatus.authenticated;
  final controller = ObjectBookmarkController(
    apiClient: apiClient,
    authController: auth,
  );
  addTearDown(controller.dispose);

  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: InboxScreen(
          apiClient: apiClient,
          authController: auth,
          captureController: CaptureController(
            apiClient: apiClient,
            authController: auth,
          ),
          bookmarkController: controller,
          passiveRefreshInterval: const Duration(days: 1),
        ),
      ),
    ),
  );
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));

  return _Harness(
    bookmarks: controller,
    inboxGets: () => inboxGets,
    stackBookmarkWrites: writes
        .where((call) => call.contains('/object-bookmarks/stack-ui'))
        .toList(),
  );
}

ColorScheme _scheme(WidgetTester tester) {
  return Theme.of(
    tester.element(find.byType(InboxScreen)),
  ).colorScheme;
}
