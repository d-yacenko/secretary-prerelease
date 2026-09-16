import 'dart:convert';

import 'package:flutter/foundation.dart';
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
import 'package:personal_secretary/inbox/inbox_conversation_groups.dart';
import 'package:personal_secretary/inbox/inbox_screen.dart';
import 'package:personal_secretary/inbox/inbox_swipe_to_remove.dart';
import 'package:personal_secretary/ui/date_format.dart';
import 'package:personal_secretary/ui/inbox_date_groups.dart';
import 'package:personal_secretary/ui/object_bookmark.dart';
import 'package:shared_preferences/shared_preferences.dart';

InboxSourceObjectOut source({
  required String id,
  required String title,
  String kind = 'chat_message',
  String provider = 'telegram',
  required String feedAt,
}) {
  return InboxSourceObjectOut(
    id: id,
    title: title,
    kind: kind,
    provider: provider,
    origin: 'source',
    state: 'observed',
    status: null,
    primaryAt: feedAt,
    feedAt: feedAt,
    excerpt: title,
  );
}

Map<String, dynamic> sourceJson({
  required String id,
  required String title,
  String kind = 'chat_message',
  String provider = 'telegram',
  required String feedAt,
}) {
  return {
    'id': id,
    'title': title,
    'kind': kind,
    'provider': provider,
    'origin': 'source',
    'state': 'observed',
    'status': null,
    'primary_at': feedAt,
    'feed_at': feedAt,
    'excerpt': title,
  };
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  test('overlay builds a stack and keeps singleton layout', () {
    final objects = [
      source(id: 't2', title: 'two', feedAt: '2026-09-15T16:07:00Z'),
      source(id: 't1', title: 'one', feedAt: '2026-09-15T16:06:00Z'),
      source(
        id: 'ev',
        title: 'Meet',
        kind: 'event',
        provider: 'google_calendar',
        feedAt: '2026-09-15T16:05:00Z',
      ),
    ];
    final overlay = [
      InboxConversationGroup.fromJson({
        'type': 'stack',
        'stack': {
          'stack_id': 'stack-1',
          'fingerprint': 'stack-1',
          'object_ids': ['t1', 't2'],
          'display_object_ids': ['t2', 't1'],
          'provider': 'telegram',
          'conversation_key': 'telegram:_:chat:1',
          'conversation_label': 'BrainTor',
          'participants': ['BrainTor'],
          'message_count': 2,
          'start_at': '2026-09-15T16:06:00Z',
          'end_at': '2026-09-15T16:07:00Z',
          'summary': 'Обсуждали новую модель Fable.',
          'fallback_summary': 'Telegram, BrainTor, 2 сообщений, 16:06–16:07.',
          'summary_status': 'current',
        },
      }),
      InboxConversationGroup.fromJson({'type': 'singleton', 'object_id': 'ev'}),
    ];
    final entries = overlayInboxConversationEntries(objects, overlay);
    final stacks = entries.whereType<InboxConversationStackEntry>().toList();
    final singles = entries.whereType<InboxSourceObjectEntry>().toList();
    expect(stacks, hasLength(1));
    expect(stacks.first.stack.messageCount, 2);
    expect(stacks.first.children.map((e) => e.id).toList(), ['t1', 't2']);
    expect(singles.single.sourceObject.id, 'ev');
  });

  test('marker insert is outside collapsed stack coverage', () {
    final objects = [
      source(id: 'n2', title: 'new2', feedAt: '2026-09-15T16:07:00Z'),
      source(id: 'n1', title: 'new1', feedAt: '2026-09-15T16:06:00Z'),
      source(id: 'old', title: 'old', feedAt: '2026-09-15T15:00:00Z'),
    ];
    final overlay = [
      InboxConversationGroup.fromJson({
        'type': 'stack',
        'stack': {
          'stack_id': 'new-stack',
          'fingerprint': 'new-stack',
          'object_ids': ['n1', 'n2'],
          'display_object_ids': ['n2', 'n1'],
          'provider': 'telegram',
          'conversation_key': 'k',
          'conversation_label': 'BrainTor',
          'participants': ['BrainTor'],
          'message_count': 2,
          'start_at': '2026-09-15T16:06:00Z',
          'end_at': '2026-09-15T16:07:00Z',
          'fallback_summary': 'Telegram, BrainTor, 2 сообщений, 16:06–16:07.',
          'summary_status': 'fallback',
        },
      }),
      InboxConversationGroup.fromJson({
        'type': 'singleton',
        'object_id': 'old',
      }),
    ];
    final grouped = overlayInboxConversationEntries(objects, overlay);
    final withMarker = insertReviewMarkerAcrossStacks(
      entries: grouped,
      insertBeforeObjectIndex: 2,
    );
    expect(withMarker.whereType<InboxReviewMarkerEntry>(), hasLength(1));
    final markerAt = withMarker.indexWhere((e) => e is InboxReviewMarkerEntry);
    expect(withMarker[markerAt - 1], isA<InboxConversationStackEntry>());
    expect(withMarker[markerAt + 1], isA<InboxSourceObjectEntry>());
  });

  test(
    'stack header title reuses ordinary subject/prefix without provider suffix',
    () {
      final telegram = InboxConversationStack.fromJson({
        'stack_id': 's',
        'fingerprint': 's',
        'object_ids': ['t1', 't2'],
        'display_object_ids': ['t2', 't1'],
        'provider': 'telegram',
        'conversation_label': 'BrainTor',
        'message_count': 2,
        'start_at': '2026-09-15T16:06:00Z',
        'end_at': '2026-09-15T16:07:00Z',
        'summary': 'Обсуждали новую модель Fable.',
        'fallback_summary': 'Telegram, BrainTor, 2 сообщений, 16:06–16:07.',
        'summary_status': 'current',
      });
      expect(
        inboxStackHeaderTitle(telegram),
        'BrainTor: Обсуждали новую модель Fable.',
      );
      expect(inboxStackCardKind('telegram'), 'chat_message');
      expect(inboxStackHeaderTitle(telegram).contains('· Telegram'), isFalse);

      final pending = InboxConversationStack.fromJson({
        'stack_id': 'p',
        'fingerprint': 'p',
        'object_ids': ['t1', 't2'],
        'display_object_ids': ['t2', 't1'],
        'provider': 'telegram',
        'conversation_label': 'BrainTor',
        'message_count': 2,
        'start_at': '2026-09-15T16:06:00Z',
        'end_at': '2026-09-15T16:07:00Z',
        'fallback_summary': 'Telegram, BrainTor, 2 сообщений, 16:06–16:07.',
        'summary_status': 'pending',
      });
      expect(inboxStackHeaderTitle(pending), 'BrainTor: 2 сообщений');

      final mail = InboxConversationStack.fromJson({
        'stack_id': 'm',
        'fingerprint': 'm',
        'object_ids': ['e1', 'e2'],
        'display_object_ids': ['e2', 'e1'],
        'provider': 'gmail',
        'conversation_label': 'Support thread',
        'message_count': 2,
        'start_at': '2026-09-15T16:06:00Z',
        'end_at': '2026-09-15T16:07:00Z',
        'summary': 'Нужен admin consent.',
        'fallback_summary': 'Gmail, Support thread, 2 сообщений, 16:06–16:07.',
        'summary_status': 'current',
      });
      expect(inboxStackHeaderTitle(mail), 'Нужен admin consent.');
      expect(inboxStackCardKind('gmail'), 'email');
    },
  );

  testWidgets(
    'collapsed stack expands original rows and does not swipe-delete the stack',
    (tester) async {
      debugDefaultTargetPlatformOverride = TargetPlatform.android;
      tester.view.physicalSize = const Size(360, 760);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() {
        debugDefaultTargetPlatformOverride = null;
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });

      final inbox = {
        'unresolved_notifications': <Object>[],
        'recent_source_objects': [
          sourceJson(id: 't2', title: 'two', feedAt: '2026-09-15T16:07:00Z'),
          sourceJson(id: 't1', title: 'one', feedAt: '2026-09-15T16:06:00Z'),
          sourceJson(
            id: 'solo',
            title: 'singleton mail',
            kind: 'email',
            provider: 'gmail',
            feedAt: '2026-09-15T15:00:00Z',
          ),
        ],
        'source_sync_status': <Object>[],
        'review_marker': {
          'anchor_object_id': 't1',
          'anchor_feed_at': '2026-09-15T16:06:00Z',
          'updated_at': '2026-09-15T18:00:00Z',
        },
        'conversation_groups': [
          {
            'type': 'stack',
            'stack': {
              'stack_id': 'stack-ui',
              'fingerprint': 'stack-ui',
              'object_ids': ['t1', 't2'],
              'display_object_ids': ['t2', 't1'],
              'provider': 'telegram',
              'conversation_key': 'k',
              'conversation_label': 'BrainTor',
              'participants': ['BrainTor'],
              'message_count': 2,
              'start_at': '2026-09-15T16:06:00Z',
              'end_at': '2026-09-15T16:07:00Z',
              'summary': 'Обсуждали новую модель Fable.',
              'fallback_summary':
                  'Telegram, BrainTor, 2 сообщений, 16:06–16:07.',
              'summary_status': 'current',
            },
          },
          {'type': 'singleton', 'object_id': 'solo'},
        ],
      };

      final apiClient = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.url.path == '/inbox') {
            return http.Response.bytes(
              utf8.encode(jsonEncode(inbox)),
              200,
              headers: {'content-type': 'application/json; charset=utf-8'},
            );
          }
          if (request.url.path.endsWith('/labels/by-objects') ||
              request.url.path.endsWith('/object-bookmarks/by-objects')) {
            return http.Response.bytes(
              utf8.encode(jsonEncode({'objects': <String, Object>{}})),
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
      final capture = CaptureController(
        apiClient: apiClient,
        authController: auth,
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: InboxScreen(
              apiClient: apiClient,
              authController: auth,
              captureController: capture,
              passiveRefreshInterval: const Duration(days: 1),
            ),
          ),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      expect(
        find.byKey(const Key('inbox_conversation_stack_stack-ui')),
        findsOneWidget,
      );
      expect(
        find.text('BrainTor: Обсуждали новую модель Fable.'),
        findsOneWidget,
      );
      expect(find.textContaining('2 сообщений'), findsOneWidget);
      expect(find.text(formatUserTime('2026-09-15T16:06:00Z')), findsWidgets);
      expect(
        find.byTooltip(formatUserDateTime('2026-09-15T16:06:00Z')),
        findsWidgets,
      );
      expect(find.text('BrainTor · Telegram'), findsNothing);
      expect(find.textContaining('· Telegram'), findsNothing);
      expect(find.text('Развернуть'), findsNothing);
      expect(find.text('Свернуть'), findsNothing);
      expect(
        find.byKey(const Key('inbox_conversation_stack_chevron_down_stack-ui')),
        findsOneWidget,
      );
      expect(find.text('two'), findsNothing);
      expect(find.text('singleton mail'), findsWidgets);
      expect(find.byKey(const Key('inbox_review_marker')), findsOneWidget);

      final stackSwipes = find.descendant(
        of: find.byKey(const Key('inbox_conversation_stack_stack-ui')),
        matching: find.byType(InboxSwipeToRemove),
      );
      expect(stackSwipes, findsNothing);

      final gutterPaddings = tester.widgetList<Padding>(
        find.descendant(
          of: find.byKey(const Key('inbox_touch_stack_stack-ui')),
          matching: find.byType(Padding),
        ),
      );
      expect(
        gutterPaddings.any((padding) {
          final resolved = padding.padding.resolve(TextDirection.ltr);
          return resolved.left == kInboxReviewRailHitWidth &&
              resolved.bottom == kInboxSourceCardGap;
        }),
        isTrue,
      );

      await tester.tap(
        find.byKey(const Key('inbox_conversation_stack_stack-ui')),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      expect(find.text('one'), findsWidgets);
      expect(find.text('two'), findsWidgets);
      expect(
        find.byKey(const Key('inbox_conversation_stack_stack-ui')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('inbox_conversation_stack_chevron_up_stack-ui')),
        findsOneWidget,
      );
      expect(find.text('Развернуть'), findsNothing);
      expect(find.text('Свернуть'), findsNothing);
      expect(find.byType(InboxSwipeToRemove), findsWidgets);
      expect(
        find.descendant(
          of: find.byKey(const Key('inbox_conversation_stack_stack-ui')),
          matching: find.byType(InboxSwipeToRemove),
        ),
        findsNothing,
      );
      final nestedCard = tester.getRect(
        find.descendant(
          of: find.byKey(const Key('inbox_stack_nested_t1')),
          matching: find.byType(Card),
        ),
      );
      final parentAfter = tester.getRect(
        find.byKey(const Key('inbox_conversation_stack_stack-ui')),
      );
      final nestedIndent = nestedCard.left - parentAfter.left;
      expect(nestedIndent, greaterThanOrEqualTo(12));
      expect(nestedIndent, lessThanOrEqualTo(24));
      final parentRail = tester.getTopLeft(
        find.byKey(const Key('inbox_review_rail_stack_stack-ui')),
      );
      final childRail = tester.getTopLeft(
        find.byKey(const Key('inbox_review_rail_t1')),
      );
      expect(childRail.dx, parentRail.dx);
      expect(find.byType(ObjectBookmarkControl), findsWidgets);
      debugDefaultTargetPlatformOverride = null;
    },
  );

  testWidgets('desktop stacks keep the same vertical gap and nested children', (
    tester,
  ) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.linux;
    tester.view.physicalSize = const Size(1024, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      debugDefaultTargetPlatformOverride = null;
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    Map<String, dynamic> stackJson({
      required String id,
      required List<String> objectIds,
      required String startAt,
      required String endAt,
    }) {
      return {
        'type': 'stack',
        'stack': {
          'stack_id': id,
          'fingerprint': id,
          'object_ids': objectIds,
          'display_object_ids': objectIds.reversed.toList(),
          'provider': 'telegram',
          'conversation_key': id,
          'conversation_label': 'BrainTor',
          'participants': ['BrainTor'],
          'message_count': objectIds.length,
          'start_at': startAt,
          'end_at': endAt,
          'summary': 'Тема $id',
          'fallback_summary': 'Telegram, BrainTor, 2 сообщений.',
          'summary_status': 'current',
        },
      };
    }

    final inbox = {
      'unresolved_notifications': <Object>[],
      'recent_source_objects': [
        sourceJson(id: 'a2', title: 'a2', feedAt: '2026-09-15T16:11:00Z'),
        sourceJson(id: 'a1', title: 'a1', feedAt: '2026-09-15T16:10:00Z'),
        sourceJson(id: 'b2', title: 'b2', feedAt: '2026-09-15T16:01:00Z'),
        sourceJson(id: 'b1', title: 'b1', feedAt: '2026-09-15T16:00:00Z'),
      ],
      'source_sync_status': <Object>[],
      'conversation_groups': [
        stackJson(
          id: 'stack-a',
          objectIds: ['a1', 'a2'],
          startAt: '2026-09-15T16:10:00Z',
          endAt: '2026-09-15T16:11:00Z',
        ),
        stackJson(
          id: 'stack-b',
          objectIds: ['b1', 'b2'],
          startAt: '2026-09-15T16:00:00Z',
          endAt: '2026-09-15T16:01:00Z',
        ),
      ],
    };

    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response.bytes(
            utf8.encode(jsonEncode(inbox)),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        if (request.url.path.endsWith('/labels/by-objects') ||
            request.url.path.endsWith('/object-bookmarks/by-objects')) {
          return http.Response.bytes(
            utf8.encode(jsonEncode({'objects': <String, Object>{}})),
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
    final capture = CaptureController(
      apiClient: apiClient,
      authController: auth,
    );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: InboxScreen(
            apiClient: apiClient,
            authController: auth,
            captureController: capture,
            passiveRefreshInterval: const Duration(days: 1),
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    final first = tester.getRect(
      find.byKey(const Key('inbox_conversation_stack_stack-a')),
    );
    final second = tester.getRect(
      find.byKey(const Key('inbox_conversation_stack_stack-b')),
    );
    final gap = second.top - first.bottom;
    expect(gap, greaterThanOrEqualTo(kInboxSourceCardGap));
    expect(gap, lessThanOrEqualTo(8));
    expect(find.text('Развернуть'), findsNothing);
    expect(find.byType(InboxSwipeToRemove), findsNothing);

    await tester.tap(find.byKey(const Key('inbox_conversation_stack_stack-a')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.text('a1'), findsWidgets);
    expect(find.byType(InboxSwipeToRemove), findsNothing);
    final nestedCard = tester.getRect(
      find.descendant(
        of: find.byKey(const Key('inbox_stack_nested_a1')),
        matching: find.byType(Card),
      ),
    );
    final parent = tester.getRect(
      find.byKey(const Key('inbox_conversation_stack_stack-a')),
    );
    final nestedIndent = nestedCard.left - parent.left;
    expect(nestedIndent, greaterThanOrEqualTo(12));
    expect(nestedIndent, lessThanOrEqualTo(24));
    expect(
      tester.getTopLeft(find.byKey(const Key('inbox_review_rail_a1'))).dx,
      tester
          .getTopLeft(find.byKey(const Key('inbox_review_rail_stack_stack-a')))
          .dx,
    );
    debugDefaultTargetPlatformOverride = null;
  });
}
