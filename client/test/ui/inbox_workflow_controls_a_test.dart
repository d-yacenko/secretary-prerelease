import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/capture/capture_controller.dart';
import 'package:personal_secretary/inbox/inbox_review_marker.dart';
import 'package:personal_secretary/inbox/inbox_screen.dart';
import 'package:personal_secretary/inbox/inbox_swipe_to_remove.dart';
import 'package:personal_secretary/search/search_screen.dart';
import 'package:personal_secretary/today/today_screen.dart';
import 'package:personal_secretary/ui/inbox_date_groups.dart';
import 'package:personal_secretary/ui/object_bookmark.dart';
import 'package:personal_secretary/ui/object_bookmark_controller.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'temporal_correctness_inbox_feed_a_test.dart';

InboxSourceObjectOut obj({
  required String id,
  required String feedAt,
}) {
  return InboxSourceObjectOut(
    id: id,
    title: id,
    kind: 'email',
    provider: 'gmail',
    origin: 'source',
    state: 'observed',
    status: null,
    primaryAt: feedAt,
    excerpt: 'x',
    feedAt: feedAt,
  );
}

List<String> entryTags(List<InboxSourceListEntry> entries) {
  return [
    for (final entry in entries)
      switch (entry) {
        InboxDateSeparatorEntry() => 'sep',
        InboxSourceObjectEntry(:final sourceObject) => 'obj:${sourceObject.id}',
        InboxReviewMarkerEntry() => 'marker',
        InboxConversationStackEntry(:final stack) => 'stack:${stack.stackId}',
      },
  ];
}

Map<String, dynamic> objectDetailJson({
  required String id,
  required String title,
}) {
  return {
    'id': id,
    'kind': 'email',
    'title': title,
    'body': 'body',
    'provider': 'gmail',
    'external_id': 'ext-1',
    'canonical_uri': null,
    'status': null,
    'start_at': null,
    'due_at': null,
    'metadata': {},
    'origin': 'source',
    'state': 'observed',
    'confidence': null,
    'created_at': '2026-09-09T12:00:00Z',
    'updated_at': '2026-09-09T12:00:00Z',
  };
}

Future<void> dragHandleToGap(
  WidgetTester tester, {
  required String gapId,
  bool longPress = false,
}) async {
  final handle = find.byKey(const Key('inbox_review_marker_handle'));
  final gap = find.byKey(Key('inbox_review_marker_gap_$gapId'));
  final gesture = await tester.startGesture(tester.getCenter(handle));
  if (longPress) {
    await tester.pump(kLongPressTimeout + kPressTimeout);
  } else {
    await tester.pump();
  }
  await gesture.moveTo(tester.getCenter(gap));
  await tester.pump();
  await gesture.up();
  await tester.pumpAndSettle();
}

Future<void> dragHandleToCard(
  WidgetTester tester, {
  required String title,
  bool longPress = false,
}) async {
  final handle = find.byKey(const Key('inbox_review_marker_handle'));
  final card = find.text(title);
  final gesture = await tester.startGesture(tester.getCenter(handle));
  if (longPress) {
    await tester.pump(kLongPressTimeout + kPressTimeout);
  } else {
    await tester.pump();
  }
  await gesture.moveTo(tester.getCenter(card));
  await tester.pump();
  await gesture.up();
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  test('marker insertion index from feed tuple', () {
    final items = [
      obj(id: 'c', feedAt: '2026-09-09T12:00:00Z'),
      obj(id: 'b', feedAt: '2026-09-08T12:00:00Z'),
      obj(id: 'a', feedAt: '2026-09-07T12:00:00Z'),
    ];
    final marker = InboxReviewMarker(
      anchorFeedAt: '2026-09-08T12:00:00Z',
      anchorObjectId: 'b',
      updatedAt: '2026-09-09T00:00:00Z',
    );
    expect(
      reviewMarkerInsertIndex(objects: items, marker: marker, hasMore: false),
      2,
    );
  });

  test('new head items leave marker boundary stable', () {
    final marker = InboxReviewMarker(
      anchorFeedAt: '2026-09-08T12:00:00Z',
      anchorObjectId: 'b',
      updatedAt: '2026-09-09T00:00:00Z',
    );
    final withoutHead = [
      obj(id: 'b', feedAt: '2026-09-08T12:00:00Z'),
      obj(id: 'a', feedAt: '2026-09-07T12:00:00Z'),
    ];
    final withHead = [
      obj(id: 'n', feedAt: '2026-09-10T12:00:00Z'),
      ...withoutHead,
    ];
    expect(
      reviewMarkerInsertIndex(
        objects: withoutHead,
        marker: marker,
        hasMore: false,
      ),
      1,
    );
    expect(
      reviewMarkerInsertIndex(
        objects: withHead,
        marker: marker,
        hasMore: false,
      ),
      2,
    );
  });

  test('missing anchor still places by tuple', () {
    final marker = InboxReviewMarker(
      anchorFeedAt: '2026-09-08T12:00:00Z',
      anchorObjectId: 'missing',
      updatedAt: '2026-09-09T00:00:00Z',
    );
    final items = [
      obj(id: 'newer', feedAt: '2026-09-09T12:00:00Z'),
      obj(id: 'older', feedAt: '2026-09-07T12:00:00Z'),
    ];
    expect(
      reviewMarkerInsertIndex(objects: items, marker: marker, hasMore: false),
      1,
    );
  });

  test('same feed_at UUID tie', () {
    const t = '2026-09-08T12:00:00Z';
    final high = obj(id: '00000000-0000-4000-8000-000000000002', feedAt: t);
    final low = obj(id: '00000000-0000-4000-8000-000000000001', feedAt: t);
    final marker = InboxReviewMarker(
      anchorFeedAt: t,
      anchorObjectId: high.id,
      updatedAt: t,
    );
    expect(
      reviewMarkerInsertIndex(
        objects: [high, low],
        marker: marker,
        hasMore: false,
      ),
      1,
    );
    expect(
      reviewMarkerInsertIndex(
        objects: [high, low],
        marker: marker,
        hasMore: true,
      ),
      1,
    );
  });

  test('exact loaded-tail anchor stays visible when hasMore', () {
    final items = [
      obj(id: 'a', feedAt: '2026-09-09T12:00:00Z'),
      obj(id: 'b', feedAt: '2026-09-08T12:00:00Z'),
      obj(id: 'c', feedAt: '2026-09-07T12:00:00Z'),
    ];
    final marker = InboxReviewMarker(
      anchorFeedAt: '2026-09-07T12:00:00Z',
      anchorObjectId: 'c',
      updatedAt: '2026-09-09T00:00:00Z',
    );
    expect(
      reviewMarkerInsertIndex(objects: items, marker: marker, hasMore: true),
      3,
    );
  });

  test('missing anchor between loaded tuples still places by boundary', () {
    final marker = InboxReviewMarker(
      anchorFeedAt: '2026-09-08T12:00:00Z',
      anchorObjectId: 'missing',
      updatedAt: '2026-09-09T00:00:00Z',
    );
    final items = [
      obj(id: 'newer', feedAt: '2026-09-09T12:00:00Z'),
      obj(id: 'older', feedAt: '2026-09-07T12:00:00Z'),
    ];
    expect(
      reviewMarkerInsertIndex(objects: items, marker: marker, hasMore: true),
      1,
    );
  });

  test('load-more eventually reveals older marker', () {
    final marker = InboxReviewMarker(
      anchorFeedAt: '2026-09-01T12:00:00Z',
      anchorObjectId: 'old',
      updatedAt: '2026-09-09T00:00:00Z',
    );
    final head = [obj(id: 'new', feedAt: '2026-09-09T12:00:00Z')];
    expect(
      reviewMarkerInsertIndex(objects: head, marker: marker, hasMore: true),
      isNull,
    );
    final reached = [
      ...head,
      obj(id: 'old', feedAt: '2026-09-01T12:00:00Z'),
      obj(id: 'older', feedAt: '2026-08-31T12:00:00Z'),
    ];
    expect(
      reviewMarkerInsertIndex(objects: reached, marker: marker, hasMore: false),
      2,
    );
  });

  test('bookmark batch maps by object id', () {
    final mapped = {
      'a': 'red',
      'b': 'blue',
    };
    expect(mapped['a'], 'red');
    expect(mapped.containsKey('c'), isFalse);
  });

  test('continuation bookmark ids are appended only', () {
    final seen = <String>{};
    final first = ['a', 'b'];
    final appended = ['c'];
    seen.addAll(first);
    final next = [for (final id in appended) if (seen.add(id)) id];
    expect(next, ['c']);
  });

  testWidgets('desktop drag persists marker at known gap without clearing feed',
      (tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.linux;
    addTearDown(() {
      debugDefaultTargetPlatformOverride = null;
    });
    tester.view.physicalSize = const Size(800, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var inboxCalls = 0;
    var putCalls = 0;
    String? putAfter;
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox' &&
            !request.url.path.endsWith('/inbox/feed')) {
          inboxCalls++;
          return jsonRes(
            inboxPayload(
              sources: [
                sourceRow(
                  id: 'a',
                  title: 'Card A',
                  feedAt: '2026-09-09T12:00:00Z',
                ),
                sourceRow(
                  id: 'b',
                  title: 'Card B',
                  feedAt: '2026-09-08T12:00:00Z',
                ),
              ],
            ),
          );
        }
        if (request.url.path == '/labels/by-objects' ||
            request.url.path == '/object-bookmarks/by-objects') {
          return jsonRes({'objects': {}});
        }
        if (request.method == 'PUT' &&
            request.url.path == '/inbox/review-marker') {
          putCalls++;
          putAfter = (jsonDecode(request.body) as Map)['after_object_id'] as String;
          return jsonRes({
            'anchor_feed_at': '2026-09-09T12:00:00Z',
            'anchor_object_id': 'a',
            'updated_at': '2026-09-09T13:00:00Z',
          });
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    await tester.pumpWidget(pumpInbox(apiClient));
    await tester.pumpAndSettle();
    expect(find.byWidgetPredicate((widget) => widget is LongPressDraggable),
        findsNothing);
    expect(find.byKey(const Key('inbox_review_marker_unplaced')), findsOneWidget);

    await dragHandleToGap(tester, gapId: 'a');
    expect(putCalls, 1);
    expect(putAfter, 'a');
    expect(inboxCalls, 1);
    expect(find.byKey(const Key('inbox_review_marker')), findsOneWidget);
    expect(find.text('Просмотрено досюда'), findsOneWidget);
    expect(find.text('Card A'), findsOneWidget);
    expect(find.text('Card B'), findsOneWidget);
    debugDefaultTargetPlatformOverride = null;
  });

  testWidgets('tail-anchor marker stays visible when inbox hasMore',
      (tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.linux;
    addTearDown(() {
      debugDefaultTargetPlatformOverride = null;
    });
    tester.view.physicalSize = const Size(800, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var putCalls = 0;
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
                  title: 'Card A',
                  feedAt: '2026-09-09T12:00:00Z',
                ),
                sourceRow(
                  id: 'b',
                  title: 'Card B',
                  feedAt: '2026-09-08T12:00:00Z',
                ),
              ],
              hasMore: true,
            ),
          );
        }
        if (request.url.path.endsWith('/inbox/feed')) {
          feedCalls++;
          return jsonRes({}, 404);
        }
        if (request.url.path == '/labels/by-objects' ||
            request.url.path == '/object-bookmarks/by-objects') {
          return jsonRes({'objects': {}});
        }
        if (request.method == 'PUT' &&
            request.url.path == '/inbox/review-marker') {
          putCalls++;
          expect(
            (jsonDecode(request.body) as Map)['after_object_id'],
            'b',
          );
          return jsonRes({
            'anchor_feed_at': '2026-09-08T12:00:00Z',
            'anchor_object_id': 'b',
            'updated_at': '2026-09-09T13:00:00Z',
          });
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    await tester.pumpWidget(pumpInbox(apiClient));
    await tester.pumpAndSettle();
    await dragHandleToGap(tester, gapId: 'b');
    expect(putCalls, 1);
    expect(feedCalls, 0);
    expect(find.byKey(const Key('inbox_review_marker')), findsOneWidget);
    expect(find.text('Просмотрено досюда'), findsOneWidget);
    expect(find.text('Card A'), findsOneWidget);
    expect(find.text('Card B'), findsOneWidget);
    debugDefaultTargetPlatformOverride = null;
  });

  testWidgets('android touch rail places marker after object without dragging',
      (tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    addTearDown(() {
      debugDefaultTargetPlatformOverride = null;
    });
    tester.view.physicalSize = const Size(360, 760);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var putCalls = 0;
    var deleteCalls = 0;
    String? putAfter;
    final haptics = <String>[];
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      SystemChannels.platform,
      (call) async {
        if (call.method == 'HapticFeedback.vibrate') {
          haptics.add('${call.arguments}');
        }
        return null;
      },
    );
    addTearDown(() {
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        null,
      );
    });

    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox' &&
            !request.url.path.endsWith('/inbox/feed')) {
          return jsonRes(
            inboxPayload(
              sources: [
                sourceRow(
                  id: 'a',
                  title: 'Card A',
                  feedAt: '2026-09-09T12:00:00Z',
                ),
                sourceRow(
                  id: 'b',
                  title: 'Card B',
                  feedAt: '2026-09-08T12:00:00Z',
                ),
              ],
            ),
          );
        }
        if (request.url.path == '/labels/by-objects' ||
            request.url.path == '/object-bookmarks/by-objects') {
          return jsonRes({'objects': {}});
        }
        if (request.method == 'PUT' &&
            request.url.path == '/inbox/review-marker') {
          putCalls++;
          putAfter =
              (jsonDecode(request.body) as Map)['after_object_id'] as String;
          return jsonRes({
            'anchor_feed_at':
                putAfter == 'b' ? '2026-09-08T12:00:00Z' : '2026-09-09T12:00:00Z',
            'anchor_object_id': putAfter,
            'updated_at': '2026-09-09T13:00:00Z',
          });
        }
        if (request.method == 'DELETE' &&
            request.url.path == '/inbox/review-marker') {
          deleteCalls++;
          return jsonRes({});
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    await tester.pumpWidget(pumpInbox(apiClient));
    await tester.pumpAndSettle();

    expect(find.byWidgetPredicate((widget) => widget is LongPressDraggable),
        findsNothing);
    expect(find.byWidgetPredicate((widget) => widget is Draggable), findsNothing);
    expect(find.byKey(const Key('inbox_review_marker_card_a')), findsNothing);
    expect(find.byKey(const Key('inbox_review_marker_gap_a')), findsNothing);
    expect(find.byKey(const Key('inbox_review_rail_reset')), findsOneWidget);

    final railB = tester.getSize(find.byKey(const Key('inbox_review_rail_b')));
    expect(railB.width, greaterThanOrEqualTo(36));
    expect(railB.width, lessThanOrEqualTo(44));
    expect(railB.height, greaterThanOrEqualTo(36));

    await tester.tap(find.byKey(const Key('inbox_review_rail_b')));
    await tester.pumpAndSettle();
    expect(putCalls, 1);
    expect(putAfter, 'b');
    expect(find.byKey(const Key('inbox_review_marker')), findsOneWidget);
    expect(find.text('Просмотрено досюда'), findsOneWidget);
    expect(find.byKey(const Key('inbox_review_rail_notch')), findsOneWidget);
    expect(
      tester.getTopLeft(find.byKey(const Key('inbox_review_marker'))).dy,
      greaterThan(tester.getTopLeft(find.text('Card B')).dy),
    );
    expect(haptics, isNotEmpty);
    expect(haptics.length, 1);

    await tester.tap(find.byKey(const Key('inbox_review_rail_reset')));
    await tester.pumpAndSettle();
    expect(deleteCalls, 1);
    expect(putCalls, 1);
    expect(find.byKey(const Key('inbox_review_marker')), findsNothing);
    expect(haptics.length, 2);
    debugDefaultTargetPlatformOverride = null;
  });

  testWidgets('android reset rail is only the left 36px hit target',
      (tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    addTearDown(() {
      debugDefaultTargetPlatformOverride = null;
    });
    tester.view.physicalSize = const Size(360, 760);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var putCalls = 0;
    var deleteCalls = 0;
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox' &&
            !request.url.path.endsWith('/inbox/feed')) {
          return jsonRes(
            inboxPayload(
              sources: [
                sourceRow(
                  id: 'a',
                  title: 'Card A',
                  feedAt: '2026-09-09T12:00:00Z',
                ),
                sourceRow(
                  id: 'b',
                  title: 'Card B',
                  feedAt: '2026-09-08T12:00:00Z',
                ),
              ],
            ),
          );
        }
        if (request.url.path == '/labels/by-objects' ||
            request.url.path == '/object-bookmarks/by-objects') {
          return jsonRes({'objects': {}});
        }
        if (request.method == 'PUT' &&
            request.url.path == '/inbox/review-marker') {
          putCalls++;
          return jsonRes({
            'anchor_feed_at': '2026-09-09T12:00:00Z',
            'anchor_object_id': 'a',
            'updated_at': '2026-09-09T13:00:00Z',
          });
        }
        if (request.method == 'DELETE' &&
            request.url.path == '/inbox/review-marker') {
          deleteCalls++;
          return jsonRes({});
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    await tester.pumpWidget(pumpInbox(apiClient));
    await tester.pumpAndSettle();

    final reset = tester.getRect(find.byKey(const Key('inbox_review_rail_reset')));
    final objectRail = tester.getRect(find.byKey(const Key('inbox_review_rail_a')));
    expect(reset.width, greaterThanOrEqualTo(36));
    expect(reset.width, lessThanOrEqualTo(44));
    expect(reset.left, closeTo(objectRail.left, 0.5));
    expect(reset.left, lessThan(24));
    expect(
      tester.getTopLeft(find.text('Требует внимания')).dx,
      closeTo(16, 1),
    );
    expect(
      reset.left,
      lessThan(tester.getTopLeft(find.text('Требует внимания')).dx),
    );

    await tester.tap(find.byKey(const Key('inbox_review_rail_a')));
    await tester.pumpAndSettle();
    expect(putCalls, 1);
    expect(find.byKey(const Key('inbox_review_marker')), findsOneWidget);

    final resetAfterPlace =
        tester.getRect(find.byKey(const Key('inbox_review_rail_reset')));
    await tester.tapAt(
      Offset(resetAfterPlace.right + 80, resetAfterPlace.center.dy),
    );
    await tester.pumpAndSettle();
    expect(deleteCalls, 0);
    expect(find.byKey(const Key('inbox_review_marker')), findsOneWidget);

    await tester.tapAt(resetAfterPlace.center);
    await tester.pumpAndSettle();
    expect(deleteCalls, 1);
    expect(find.byKey(const Key('inbox_review_marker')), findsNothing);
    debugDefaultTargetPlatformOverride = null;
  });

  testWidgets('android source cards have compact vertical gap', (tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    addTearDown(() {
      debugDefaultTargetPlatformOverride = null;
    });
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var putCalls = 0;
    var deleteCalls = 0;
    final putAfter = <String>[];
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox' &&
            !request.url.path.endsWith('/inbox/feed')) {
          return jsonRes(
            inboxPayload(
              sources: [
                sourceRow(
                  id: 'a',
                  title: 'Card A',
                  feedAt: '2026-09-09T12:00:00Z',
                ),
                sourceRow(
                  id: 'b',
                  title: 'Card B',
                  feedAt: '2026-09-09T11:00:00Z',
                ),
              ],
            ),
          );
        }
        if (request.url.path == '/labels/by-objects' ||
            request.url.path == '/object-bookmarks/by-objects') {
          return jsonRes({'objects': {}});
        }
        if (request.method == 'PUT' &&
            request.url.path == '/inbox/review-marker') {
          putCalls++;
          putAfter.add(
            (jsonDecode(request.body) as Map)['after_object_id'] as String,
          );
          return jsonRes({
            'anchor_feed_at': '2026-09-09T12:00:00Z',
            'anchor_object_id': putAfter.last,
            'updated_at': '2026-09-09T13:00:00Z',
          });
        }
        if (request.method == 'DELETE' &&
            request.url.path == '/inbox/review-marker') {
          deleteCalls++;
          return jsonRes({});
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');

    Finder cardOf(String title) {
      return find.ancestor(
        of: find.text(title),
        matching: find.byType(Card),
      );
    }

    Future<void> assertCompactGap() async {
      expect(find.text('Card A'), findsOneWidget);
      expect(find.text('Card B'), findsOneWidget);
      final first = tester.getRect(cardOf('Card A'));
      final second = tester.getRect(cardOf('Card B'));
      expect(second.top, greaterThan(first.bottom));
      final gap = second.top - first.bottom;
      expect(gap, greaterThanOrEqualTo(4));
      expect(gap, lessThanOrEqualTo(8));
      final railA = tester.getSize(find.byKey(const Key('inbox_review_rail_a')));
      expect(railA.width, greaterThanOrEqualTo(36));
      expect(railA.width, lessThanOrEqualTo(44));
      expect(find.byWidgetPredicate((widget) => widget is LongPressDraggable),
          findsNothing);
      expect(find.byKey(const Key('inbox_review_marker_card_a')), findsNothing);
      expect(find.byKey(const Key('inbox_review_marker_gap_a')), findsNothing);
      expect(find.byWidgetPredicate((widget) => widget is DragTarget),
          findsNothing);
    }

    tester.view.physicalSize = const Size(360, 760);
    await tester.pumpWidget(pumpInbox(apiClient));
    await tester.pumpAndSettle();
    await assertCompactGap();

    final before = inboxFeedPosition(tester).pixels;
    await tester.timedDrag(
      find.byKey(const Key('inbox_review_rail_a')),
      const Offset(0, -80),
      const Duration(milliseconds: 350),
    );
    await tester.pumpAndSettle();
    expect(putCalls, 0);
    expect(deleteCalls, 0);
    expect(inboxFeedPosition(tester).pixels, greaterThanOrEqualTo(before));

    await tester.tap(find.byKey(const Key('inbox_review_rail_a')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('inbox_review_rail_b')));
    await tester.pumpAndSettle();
    expect(putCalls, 2);
    expect(putAfter, ['a', 'b']);
    expect(deleteCalls, 0);

    tester.view.physicalSize = const Size(800, 1280);
    await tester.pumpAndSettle();
    await assertCompactGap();
    debugDefaultTargetPlatformOverride = null;
  });

  testWidgets('android rail vertical swipe scrolls and writes no marker',
      (tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    addTearDown(() {
      debugDefaultTargetPlatformOverride = null;
    });
    tester.view.physicalSize = const Size(360, 420);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var putCalls = 0;
    var deleteCalls = 0;
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox' &&
            !request.url.path.endsWith('/inbox/feed')) {
          return jsonRes(
            inboxPayload(
              sources: [
                for (var i = 0; i < 6; i++)
                  sourceRow(
                    id: 'n$i',
                    title: 'Card $i',
                    feedAt:
                        '2026-09-09T${(12 - i).toString().padLeft(2, '0')}:00:00Z',
                  ),
              ],
            ),
          );
        }
        if (request.url.path == '/labels/by-objects' ||
            request.url.path == '/object-bookmarks/by-objects') {
          return jsonRes({'objects': {}});
        }
        if (request.method == 'PUT' &&
            request.url.path == '/inbox/review-marker') {
          putCalls++;
          return jsonRes({
            'anchor_feed_at': '2026-09-09T12:00:00Z',
            'anchor_object_id': 'n0',
            'updated_at': '2026-09-09T13:00:00Z',
          });
        }
        if (request.method == 'DELETE' &&
            request.url.path == '/inbox/review-marker') {
          deleteCalls++;
          return jsonRes({});
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    await tester.pumpWidget(pumpInbox(apiClient));
    await tester.pumpAndSettle();

    final before = inboxFeedPosition(tester).pixels;
    await tester.timedDrag(
      find.byKey(const Key('inbox_review_rail_n0')),
      const Offset(0, -180),
      const Duration(milliseconds: 350),
    );
    await tester.pumpAndSettle();
    expect(putCalls, 0);
    expect(deleteCalls, 0);
    expect(inboxFeedPosition(tester).pixels, greaterThan(before));
    debugDefaultTargetPlatformOverride = null;
  });

  test('marker between dates sits above the next date separator', () {
    final grouped = groupInboxSourceEntries([
      obj(id: 'a', feedAt: '2026-09-09T12:00:00Z'),
      obj(id: 'b', feedAt: '2026-09-08T12:00:00Z'),
    ]);
    expect(
      entryTags(
        insertReviewMarkerEntry(
          entries: grouped,
          insertBeforeObjectIndex: 1,
        ),
      ),
      ['sep', 'obj:a', 'marker', 'sep', 'obj:b'],
    );
  });

  test('marker within the same date sits between objects', () {
    final grouped = groupInboxSourceEntries([
      obj(id: 'a', feedAt: '2026-09-09T12:00:00Z'),
      obj(id: 'b', feedAt: '2026-09-09T11:00:00Z'),
    ]);
    expect(
      entryTags(
        insertReviewMarkerEntry(
          entries: grouped,
          insertBeforeObjectIndex: 1,
        ),
      ),
      ['sep', 'obj:a', 'marker', 'obj:b'],
    );
  });

  test('marker before the first object precedes its date separator', () {
    final grouped = groupInboxSourceEntries([
      obj(id: 'a', feedAt: '2026-09-09T12:00:00Z'),
    ]);
    expect(
      entryTags(
        insertReviewMarkerEntry(
          entries: grouped,
          insertBeforeObjectIndex: 0,
        ),
      ),
      ['marker', 'sep', 'obj:a'],
    );
  });

  test('marker after the loaded tail follows the final object', () {
    final grouped = groupInboxSourceEntries([
      obj(id: 'a', feedAt: '2026-09-09T12:00:00Z'),
      obj(id: 'b', feedAt: '2026-09-08T12:00:00Z'),
    ]);
    expect(
      entryTags(
        insertReviewMarkerEntry(
          entries: grouped,
          insertBeforeObjectIndex: 2,
        ),
      ),
      ['sep', 'obj:a', 'sep', 'obj:b', 'marker'],
    );
  });

  testWidgets('bookmark tab opens shared palette to recolor and clear',
      (tester) async {
    String? color = 'red';
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: StatefulBuilder(
            builder: (context, setState) {
              return ObjectBookmarkRibbon(
                color: color,
                onSelect: (value) => setState(() => color = value),
                onClear: () => setState(() => color = null),
                child: const SizedBox(
                  width: 240,
                  height: 80,
                  child: Text('card'),
                ),
              );
            },
          ),
        ),
      ),
    );
    await tester.tap(find.byKey(const Key('object_bookmark_tab')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Синий'));
    await tester.pumpAndSettle();
    expect(color, 'blue');
    await tester.tap(find.byKey(const Key('object_bookmark_tab')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Убрать закладку'));
    await tester.pumpAndSettle();
    expect(color, isNull);
    expect(find.byKey(const Key('object_bookmark_tab')), findsNothing);
  });

  testWidgets('bookmark control can change color and clear', (tester) async {
    String? color;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: StatefulBuilder(
            builder: (context, setState) {
              return ObjectBookmarkControl(
                color: color,
                onSelect: (value) => setState(() => color = value),
                onClear: () => setState(() => color = null),
              );
            },
          ),
        ),
      ),
    );
    await tester.tap(find.byKey(const Key('object_bookmark_control')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Красный'));
    await tester.pumpAndSettle();
    expect(color, 'red');
    await tester.tap(find.byKey(const Key('object_bookmark_control')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Убрать закладку'));
    await tester.pumpAndSettle();
    expect(color, isNull);
  });

  testWidgets('detail bookmark edit is reflected on inbox return',
      (tester) async {
    tester.view.physicalSize = const Size(800, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var inboxCalls = 0;
    String? storedColor;
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox' &&
            !request.url.path.endsWith('/inbox/feed')) {
          inboxCalls++;
          return jsonRes(
            inboxPayload(
              sources: [
                sourceRow(
                  id: 'a',
                  title: 'Card A',
                  feedAt: '2026-09-09T12:00:00Z',
                ),
              ],
            ),
          );
        }
        if (request.url.path == '/labels/by-objects') {
          return jsonRes({'objects': {}});
        }
        if (request.url.path == '/object-bookmarks/by-objects') {
          final ids =
              (jsonDecode(request.body) as Map)['object_ids'] as List<dynamic>;
          final objects = <String, Map<String, String>>{};
          if (storedColor != null && ids.contains('a')) {
            objects['a'] = {'color': storedColor!};
          }
          return jsonRes({'objects': objects});
        }
        if (request.method == 'PUT' &&
            request.url.path == '/object-bookmarks/a') {
          storedColor =
              (jsonDecode(request.body) as Map)['color'] as String;
          return jsonRes({
            'object_id': 'a',
            'color': storedColor,
            'updated_at': '2026-09-09T13:00:00Z',
          });
        }
        if (request.url.path == '/objects/a') {
          return jsonRes(objectDetailJson(id: 'a', title: 'Card A'));
        }
        if (request.url.path == '/objects/a/neighbors') {
          return jsonRes({'object_id': 'a', 'neighbors': []});
        }
        if (request.url.path == '/objects/a/context') {
          return jsonRes({
            'object': objectDetailJson(id: 'a', title: 'Card A'),
            'edges': [],
            'neighbors': [],
          });
        }
        if (request.url.path == '/objects/a/labels') {
          return jsonRes({'labels': []});
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    await tester.pumpWidget(pumpInbox(apiClient));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('object_bookmark_tab')), findsNothing);
    await tester.tap(find.text('Card A'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('object_bookmark_control')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Красный'));
    await tester.pumpAndSettle();
    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();
    expect(inboxCalls, 1);
    expect(find.text('Card A'), findsOneWidget);
    expect(find.byKey(const Key('object_bookmark_tab')), findsOneWidget);
  });

  Map<String, dynamic> todaySharedPayload({required String id, required String title}) {
    return {
      'date': '2026-09-09',
      'timezone': 'Europe/Amsterdam',
      'day_start': '2026-09-09T00:00:00+02:00',
      'tasks': [],
      'calendar_events': [
        {
          'id': id,
          'kind': 'event',
          'title': title,
          'body': null,
          'provider': 'google',
          'external_id': null,
          'canonical_uri': null,
          'status': null,
          'start_at': '2026-09-09T09:00:00+02:00',
          'due_at': '2026-09-09T10:00:00+02:00',
          'metadata': {},
          'origin': 'source',
          'state': 'observed',
          'confidence': null,
          'created_at': '2026-09-09T08:00:00Z',
          'updated_at': '2026-09-09T08:00:00Z',
        },
      ],
      'notifications': [],
    };
  }

  testWidgets('shared bookmark state updates mounted Inbox and Today immediately',
      (tester) async {
    tester.view.physicalSize = const Size(800, 1200);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var todayGets = 0;
    var inboxGets = 0;
    String? stored;
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/today') {
          todayGets++;
          return jsonRes(todaySharedPayload(id: 'shared-1', title: 'Shared Event'));
        }
        if (request.url.path == '/inbox' &&
            !request.url.path.endsWith('/inbox/feed')) {
          inboxGets++;
          return jsonRes(
            inboxPayload(
              sources: [
                sourceRow(
                  id: 'shared-1',
                  title: 'Shared Event',
                  feedAt: '2026-09-09T12:00:00Z',
                  kind: 'event',
                  provider: 'google',
                ),
              ],
            ),
          );
        }
        if (request.url.path == '/labels/by-objects' ||
            request.url.path == '/object-bookmarks/by-objects') {
          final objects = <String, Map<String, String>>{};
          if (stored != null) {
            objects['shared-1'] = {'color': stored!};
          }
          if (request.url.path == '/labels/by-objects') {
            return jsonRes({'objects': {}});
          }
          return jsonRes({'objects': objects});
        }
        if (request.method == 'PUT' &&
            request.url.path == '/object-bookmarks/shared-1') {
          stored = (jsonDecode(request.body) as Map)['color'] as String;
          return jsonRes({
            'object_id': 'shared-1',
            'color': stored,
            'updated_at': '2026-09-09T13:00:00Z',
          });
        }
        if (request.method == 'DELETE' &&
            request.url.path == '/object-bookmarks/shared-1') {
          stored = null;
          return jsonRes({}, 200);
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final bookmarks = ObjectBookmarkController(
      apiClient: apiClient,
      authController: auth,
    );
    final capture = CaptureController(apiClient: apiClient, authController: auth);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Column(
            children: [
              Expanded(
                child: InboxScreen(
                  apiClient: apiClient,
                  authController: auth,
                  captureController: capture,
                  bookmarkController: bookmarks,
                  passiveRefreshInterval: const Duration(days: 1),
                ),
              ),
              Expanded(
                child: TodayScreen(
                  apiClient: apiClient,
                  authController: auth,
                  captureController: capture,
                  bookmarkController: bookmarks,
                  passiveRefreshInterval: const Duration(days: 1),
                  now: () => DateTime(2026, 9, 9, 12),
                ),
              ),
            ],
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(todayGets, 1);
    expect(inboxGets, 1);
    expect(find.byKey(const Key('object_bookmark_tab')), findsNothing);

    await tester.tap(
      find.descendant(
        of: find.byType(InboxScreen),
        matching: find.byKey(const Key('object_bookmark_control')),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Красный'));
    await tester.pumpAndSettle();
    expect(todayGets, 1);
    expect(inboxGets, 1);
    expect(bookmarks.colorFor('shared-1'), 'red');
    expect(find.byKey(const Key('object_bookmark_tab')), findsNWidgets(2));
    expect(
      find.descendant(
        of: find.byType(TodayScreen),
        matching: find.byKey(const Key('object_bookmark_control')),
      ),
      findsNothing,
    );

    await tester.tap(
      find
          .descendant(
            of: find.byType(TodayScreen),
            matching: find.byKey(const Key('object_bookmark_tab')),
          )
          .first,
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Синий'));
    await tester.pumpAndSettle();
    expect(todayGets, 1);
    expect(bookmarks.colorFor('shared-1'), 'blue');

    await tester.tap(
      find
          .descendant(
            of: find.byType(InboxScreen),
            matching: find.byKey(const Key('object_bookmark_tab')),
          )
          .first,
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Убрать закладку'));
    await tester.pumpAndSettle();
    expect(bookmarks.colorFor('shared-1'), isNull);
    expect(find.byKey(const Key('object_bookmark_tab')), findsNothing);
    expect(find.byKey(const Key('object_bookmark_control')), findsNWidgets(2));
  });

  testWidgets('search task can create bookmark into shared controller',
      (tester) async {
    tester.view.physicalSize = const Size(800, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/search/facets') {
          return jsonRes({
            'kinds': [
              {'value': 'task', 'count': 1},
            ],
            'providers': [],
          });
        }
        if (request.url.path == '/labels') {
          return jsonRes({'labels': []});
        }
        if (request.url.path == '/search') {
          return jsonRes([
            {
              'id': 'task-1',
              'kind': 'task',
              'title': 'Alpha task',
              'body': 'body',
              'provider': null,
              'external_id': null,
              'canonical_uri': null,
              'status': 'pending',
              'start_at': null,
              'due_at': null,
              'metadata': {},
              'origin': 'user',
              'state': 'confirmed',
              'confidence': null,
              'created_at': '2026-08-28T08:00:00Z',
              'updated_at': '2026-08-28T08:00:00Z',
            },
          ]);
        }
        if (request.url.path == '/labels/by-objects' ||
            request.url.path == '/object-bookmarks/by-objects') {
          return jsonRes({'objects': {}});
        }
        if (request.method == 'PUT' &&
            request.url.path == '/object-bookmarks/task-1') {
          return jsonRes({
            'object_id': 'task-1',
            'color': 'green',
            'updated_at': '2026-09-09T13:00:00Z',
          });
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final bookmarks = ObjectBookmarkController(
      apiClient: apiClient,
      authController: auth,
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Column(
            children: [
              Expanded(
                child: SearchScreen(
                  apiClient: apiClient,
                  authController: auth,
                  captureController: CaptureController(
                    apiClient: apiClient,
                    authController: auth,
                  ),
                  bookmarkController: bookmarks,
                ),
              ),
              ListenableBuilder(
                listenable: bookmarks,
                builder: (context, _) => Text(
                  'mirror:${bookmarks.colorFor('task-1') ?? 'none'}',
                ),
              ),
            ],
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, 'alpha');
    await tester.tap(find.widgetWithText(FilledButton, 'Поиск'));
    await tester.pumpAndSettle();
    expect(find.text('Alpha task'), findsOneWidget);
    expect(find.byKey(const Key('object_bookmark_control')), findsOneWidget);
    expect(find.byKey(const Key('object_bookmark_tab')), findsNothing);
    await tester.tap(find.byKey(const Key('object_bookmark_control')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Зелёный'));
    await tester.pumpAndSettle();
    expect(bookmarks.colorFor('task-1'), 'green');
    expect(find.text('mirror:green'), findsOneWidget);
    expect(find.byKey(const Key('object_bookmark_tab')), findsOneWidget);
    expect(find.byKey(const Key('object_bookmark_control')), findsNothing);
  });

  testWidgets('inbox bookmark visual grammar unbookmarked to remove',
      (tester) async {
    tester.view.physicalSize = const Size(800, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    String? stored;
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox' &&
            !request.url.path.endsWith('/inbox/feed')) {
          return jsonRes(
            inboxPayload(
              sources: [
                sourceRow(
                  id: 'a',
                  title: 'Card A',
                  feedAt: '2026-09-09T12:00:00Z',
                ),
              ],
            ),
          );
        }
        if (request.url.path == '/labels/by-objects') {
          return jsonRes({'objects': {}});
        }
        if (request.url.path == '/object-bookmarks/by-objects') {
          final objects = <String, Map<String, String>>{};
          if (stored != null) {
            objects['a'] = {'color': stored!};
          }
          return jsonRes({'objects': objects});
        }
        if (request.method == 'PUT' &&
            request.url.path == '/object-bookmarks/a') {
          stored = (jsonDecode(request.body) as Map)['color'] as String;
          return jsonRes({
            'object_id': 'a',
            'color': stored,
            'updated_at': '2026-09-09T13:00:00Z',
          });
        }
        if (request.method == 'DELETE' &&
            request.url.path == '/object-bookmarks/a') {
          stored = null;
          return jsonRes({}, 200);
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    await tester.pumpWidget(pumpInbox(apiClient));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('object_bookmark_control')), findsOneWidget);
    expect(find.byKey(const Key('object_bookmark_tab')), findsNothing);
    expect(find.byType(ObjectBookmarkGlyph), findsWidgets);
    await tester.tap(find.byKey(const Key('object_bookmark_control')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Красный'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('object_bookmark_control')), findsNothing);
    expect(find.byKey(const Key('object_bookmark_tab')), findsOneWidget);
    await tester.tap(find.byKey(const Key('object_bookmark_tab')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Синий'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('object_bookmark_tab')), findsOneWidget);
    expect(find.byKey(const Key('object_bookmark_control')), findsNothing);
    await tester.tap(find.byKey(const Key('object_bookmark_tab')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Убрать закладку'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('object_bookmark_tab')), findsNothing);
    expect(find.byKey(const Key('object_bookmark_control')), findsOneWidget);
  });

  testWidgets('today task visual grammar uses the same swallow-tail glyph',
      (tester) async {
    tester.view.physicalSize = const Size(800, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    String? stored;
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/today') {
          return jsonRes({
            'date': '2026-08-28',
            'timezone': 'Europe/Amsterdam',
            'day_start': '2026-08-28T00:00:00+02:00',
            'tasks': [
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
            'calendar_events': [],
            'notifications': [],
          });
        }
        if (request.url.path == '/labels/by-objects') {
          return jsonRes({'objects': {}});
        }
        if (request.url.path == '/object-bookmarks/by-objects') {
          final objects = <String, Map<String, String>>{};
          if (stored != null) {
            objects['task-1'] = {'color': stored!};
          }
          return jsonRes({'objects': objects});
        }
        if (request.method == 'PUT' &&
            request.url.path == '/object-bookmarks/task-1') {
          stored = (jsonDecode(request.body) as Map)['color'] as String;
          return jsonRes({
            'object_id': 'task-1',
            'color': stored,
            'updated_at': '2026-09-09T13:00:00Z',
          });
        }
        if (request.method == 'DELETE' &&
            request.url.path == '/object-bookmarks/task-1') {
          stored = null;
          return jsonRes({}, 200);
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TodayScreen(
            apiClient: apiClient,
            authController: auth,
            captureController: CaptureController(
              apiClient: apiClient,
              authController: auth,
            ),
            passiveRefreshInterval: const Duration(days: 1),
            now: () => DateTime(2026, 8, 28, 12),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('object_bookmark_control')), findsOneWidget);
    expect(find.byKey(const Key('object_bookmark_tab')), findsNothing);
    await tester.tap(find.byKey(const Key('object_bookmark_control')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Красный'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('object_bookmark_control')), findsNothing);
    expect(find.byKey(const Key('object_bookmark_tab')), findsOneWidget);
    expect(find.byType(ObjectBookmarkGlyph), findsWidgets);
    await tester.tap(find.byKey(const Key('object_bookmark_tab')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Убрать закладку'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('object_bookmark_tab')), findsNothing);
    expect(find.byKey(const Key('object_bookmark_control')), findsOneWidget);
  });

  testWidgets(
      'today neutral bookmark shares left lane for task, google, labeled yandex',
      (tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.linux;
    addTearDown(() {
      debugDefaultTargetPlatformOverride = null;
    });

    const titles = (
      task: 'Task without labels',
      google: 'Google event without labels',
      yandex: 'Yandex event with label',
    );

    Map<String, dynamic> objectJson({
      required String id,
      required String kind,
      required String title,
      String? provider,
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
        'metadata': {},
        'origin': provider == null ? 'user' : 'source',
        'state': provider == null ? 'confirmed' : 'observed',
        'confidence': null,
        'created_at': '2026-08-28T08:00:00Z',
        'updated_at': '2026-08-28T08:00:00Z',
      };
    }

    Finder rowRibbon(String title) {
      return find.ancestor(
        of: find.text(title),
        matching: find.byType(ObjectBookmarkRibbon),
      );
    }

    Finder controlOn(String title) {
      return find.descendant(
        of: rowRibbon(title),
        matching: find.byKey(const Key('object_bookmark_control')),
      );
    }

    Finder tabOn(String title) {
      return find.descendant(
        of: rowRibbon(title),
        matching: find.byKey(const Key('object_bookmark_tab')),
      );
    }

    Future<void> pumpToday(Size size) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final stored = <String, String>{};
      final apiClient = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.url.path == '/today') {
            return jsonRes({
              'date': '2026-08-28',
              'timezone': 'Europe/Amsterdam',
              'day_start': '2026-08-28T00:00:00+02:00',
              'tasks': [
                objectJson(
                  id: 'task-plain',
                  kind: 'task',
                  title: titles.task,
                  dueAt: '2026-08-28T14:00:00+02:00',
                ),
              ],
              'calendar_events': [
                objectJson(
                  id: 'google-plain',
                  kind: 'event',
                  title: titles.google,
                  provider: 'google_calendar',
                  startAt: '2026-08-28T09:00:00+02:00',
                ),
                objectJson(
                  id: 'yandex-labeled',
                  kind: 'event',
                  title: titles.yandex,
                  provider: 'yandex_calendar',
                  startAt: '2026-08-28T10:00:00+02:00',
                ),
              ],
              'notifications': [],
            });
          }
          if (request.url.path == '/labels/by-objects') {
            return jsonRes({
              'objects': {
                'yandex-labeled': [
                  {'id': 'lab-1', 'title': 'Work'},
                ],
              },
            });
          }
          if (request.url.path == '/object-bookmarks/by-objects') {
            return jsonRes({
              'objects': {
                for (final entry in stored.entries)
                  entry.key: {'color': entry.value},
              },
            });
          }
          if (request.method == 'PUT' &&
              request.url.path.startsWith('/object-bookmarks/')) {
            final id = request.url.path.split('/').last;
            stored[id] = (jsonDecode(request.body) as Map)['color'] as String;
            return jsonRes({
              'object_id': id,
              'color': stored[id],
              'updated_at': '2026-09-09T13:00:00Z',
            });
          }
          if (request.method == 'DELETE' &&
              request.url.path.startsWith('/object-bookmarks/')) {
            stored.remove(request.url.path.split('/').last);
            return jsonRes({}, 200);
          }
          return jsonRes({}, 404);
        }),
      );
      apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
      final auth = AuthController(
        apiClient: apiClient,
        tokenStore: FakeTokenStore(),
        serverUrlStore: FakeServerUrlStore(),
      );
      auth.status = AuthStatus.authenticated;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: TodayScreen(
              apiClient: apiClient,
              authController: auth,
              captureController: CaptureController(
                apiClient: apiClient,
                authController: auth,
              ),
              passiveRefreshInterval: const Duration(days: 1),
              now: () => DateTime(2026, 8, 28, 12),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
    }

    Future<void> assertAlignedNeutralBookmarks() async {
      for (final title in [titles.task, titles.google, titles.yandex]) {
        await tester.ensureVisible(controlOn(title));
      }
      await tester.pumpAndSettle();
      final taskX = tester.getTopLeft(controlOn(titles.task)).dx;
      final googleX = tester.getTopLeft(controlOn(titles.google)).dx;
      final yandexX = tester.getTopLeft(controlOn(titles.yandex)).dx;
      expect((taskX - yandexX).abs(), lessThanOrEqualTo(1.0));
      expect((googleX - yandexX).abs(), lessThanOrEqualTo(1.0));
    }

    Future<void> cycleRow(String title) async {
      await tester.ensureVisible(controlOn(title));
      expect(controlOn(title), findsOneWidget);
      await tester.tap(controlOn(title));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Зелёный'));
      await tester.pumpAndSettle();
      expect(controlOn(title), findsNothing);
      expect(tabOn(title), findsOneWidget);
      await tester.tap(tabOn(title));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Убрать закладку'));
      await tester.pumpAndSettle();
      expect(tabOn(title), findsNothing);
      expect(controlOn(title), findsOneWidget);
    }

    await pumpToday(const Size(800, 900));
    await assertAlignedNeutralBookmarks();
    for (final title in [titles.task, titles.google, titles.yandex]) {
      await cycleRow(title);
    }
    await assertAlignedNeutralBookmarks();

    await pumpToday(const Size(360, 800));
    await assertAlignedNeutralBookmarks();
    await cycleRow(titles.task);
    await assertAlignedNeutralBookmarks();
    debugDefaultTargetPlatformOverride = null;
  });

  testWidgets('desktop drop on card center persists after that object',
      (tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.linux;
    addTearDown(() {
      debugDefaultTargetPlatformOverride = null;
    });
    tester.view.physicalSize = const Size(800, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var inboxCalls = 0;
    var putCalls = 0;
    String? putAfter;
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox' &&
            !request.url.path.endsWith('/inbox/feed')) {
          inboxCalls++;
          return jsonRes(
            inboxPayload(
              sources: [
                sourceRow(
                  id: 'a',
                  title: 'Card A',
                  feedAt: '2026-09-09T12:00:00Z',
                ),
                sourceRow(
                  id: 'b',
                  title: 'Card B',
                  feedAt: '2026-09-08T12:00:00Z',
                ),
              ],
            ),
          );
        }
        if (request.url.path == '/labels/by-objects' ||
            request.url.path == '/object-bookmarks/by-objects') {
          return jsonRes({'objects': {}});
        }
        if (request.method == 'PUT' &&
            request.url.path == '/inbox/review-marker') {
          putCalls++;
          putAfter =
              (jsonDecode(request.body) as Map)['after_object_id'] as String;
          return jsonRes({
            'anchor_feed_at': '2026-09-09T12:00:00Z',
            'anchor_object_id': 'a',
            'updated_at': '2026-09-09T13:00:00Z',
          });
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    await tester.pumpWidget(pumpInbox(apiClient));
    await tester.pumpAndSettle();
    await dragHandleToCard(tester, title: 'Card A');
    expect(putCalls, 1);
    expect(putAfter, 'a');
    expect(inboxCalls, 1);
    expect(find.byKey(const Key('inbox_review_marker')), findsOneWidget);
    expect(find.text('Card A'), findsOneWidget);
    expect(find.text('Card B'), findsOneWidget);
    debugDefaultTargetPlatformOverride = null;
  });

  testWidgets('android tablet rail tap places marker after object',
      (tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    addTearDown(() {
      debugDefaultTargetPlatformOverride = null;
    });
    tester.view.physicalSize = const Size(800, 1280);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var putCalls = 0;
    String? putAfter;
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox' &&
            !request.url.path.endsWith('/inbox/feed')) {
          return jsonRes(
            inboxPayload(
              sources: [
                sourceRow(
                  id: 'a',
                  title: 'Card A',
                  feedAt: '2026-09-09T12:00:00Z',
                ),
                sourceRow(
                  id: 'b',
                  title: 'Card B',
                  feedAt: '2026-09-08T12:00:00Z',
                ),
              ],
            ),
          );
        }
        if (request.url.path == '/labels/by-objects' ||
            request.url.path == '/object-bookmarks/by-objects') {
          return jsonRes({'objects': {}});
        }
        if (request.method == 'PUT' &&
            request.url.path == '/inbox/review-marker') {
          putCalls++;
          putAfter =
              (jsonDecode(request.body) as Map)['after_object_id'] as String;
          return jsonRes({
            'anchor_feed_at': '2026-09-08T12:00:00Z',
            'anchor_object_id': 'b',
            'updated_at': '2026-09-09T13:00:00Z',
          });
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    await tester.pumpWidget(pumpInbox(apiClient));
    await tester.pumpAndSettle();
    expect(find.byWidgetPredicate((widget) => widget is LongPressDraggable),
        findsNothing);
    final railB = tester.getSize(find.byKey(const Key('inbox_review_rail_b')));
    expect(railB.width, greaterThanOrEqualTo(36));
    await tester.tap(find.byKey(const Key('inbox_review_rail_b')));
    await tester.pumpAndSettle();
    expect(putCalls, 1);
    expect(putAfter, 'b');
    expect(find.text('Просмотрено досюда'), findsOneWidget);
    debugDefaultTargetPlatformOverride = null;
  });

  testWidgets('android rail tap on continuation object issues one PUT',
      (tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    addTearDown(() {
      debugDefaultTargetPlatformOverride = null;
    });
    tester.view.physicalSize = const Size(360, 400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var putCalls = 0;
    var feedCalls = 0;
    String? putAfter;
    final firstPage = [
      for (var index = 0; index < 8; index++)
        sourceRow(
          id: 'p1-$index',
          title: 'First page $index',
          feedAt: '2026-09-08T${(18 - index).toString().padLeft(2, '0')}:00:00Z',
        ),
    ];
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox' &&
            !request.url.path.endsWith('/inbox/feed')) {
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
                id: 'far',
                title: 'Far object',
                feedAt: '2026-09-07T10:00:00Z',
              ),
            ],
            'next_cursor': null,
            'has_more': false,
          });
        }
        if (request.url.path == '/labels/by-objects' ||
            request.url.path == '/object-bookmarks/by-objects') {
          return jsonRes({'objects': {}});
        }
        if (request.method == 'PUT' &&
            request.url.path == '/inbox/review-marker') {
          putCalls++;
          putAfter =
              (jsonDecode(request.body) as Map)['after_object_id'] as String;
          return jsonRes({
            'anchor_feed_at': '2026-09-07T10:00:00Z',
            'anchor_object_id': 'far',
            'updated_at': '2026-09-09T13:00:00Z',
          });
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    await tester.pumpWidget(pumpInbox(apiClient));
    await tester.pumpAndSettle();
    expect(find.text('First page 0'), findsOneWidget);

    inboxFeedPosition(tester).jumpTo(inboxFeedPosition(tester).maxScrollExtent);
    await tester.pumpAndSettle();
    if (find.text('Far object').evaluate().isEmpty) {
      inboxFeedPosition(tester).jumpTo(inboxFeedPosition(tester).maxScrollExtent);
      await tester.pumpAndSettle();
    }
    expect(find.text('Far object'), findsOneWidget);
    expect(feedCalls, 1);

    await tester.ensureVisible(find.byKey(const Key('inbox_review_rail_far')));
    await tester.tap(find.byKey(const Key('inbox_review_rail_far')));
    await tester.pumpAndSettle();
    expect(putCalls, 1);
    expect(putAfter, 'far');
    final placedMarker = find.byKey(
      const Key('inbox_review_marker'),
      skipOffstage: false,
    );
    expect(placedMarker, findsOneWidget);
    await tester.ensureVisible(placedMarker);
    await tester.pumpAndSettle();
    expect(find.text('Просмотрено досюда'), findsOneWidget);
    debugDefaultTargetPlatformOverride = null;
  });

  testWidgets('android card tap still opens detail without marker write',
      (tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    addTearDown(() {
      debugDefaultTargetPlatformOverride = null;
    });
    tester.view.physicalSize = const Size(800, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var putCalls = 0;
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox' &&
            !request.url.path.endsWith('/inbox/feed')) {
          return jsonRes(
            inboxPayload(
              sources: [
                sourceRow(
                  id: 'a',
                  title: 'Card A',
                  feedAt: '2026-09-09T12:00:00Z',
                ),
                sourceRow(
                  id: 'b',
                  title: 'Card B',
                  feedAt: '2026-09-08T12:00:00Z',
                ),
              ],
            ),
          );
        }
        if (request.url.path == '/labels/by-objects' ||
            request.url.path == '/object-bookmarks/by-objects') {
          return jsonRes({'objects': {}});
        }
        if (request.url.path == '/objects/a') {
          return jsonRes(objectDetailJson(id: 'a', title: 'Card A'));
        }
        if (request.url.path == '/objects/a/neighbors') {
          return jsonRes({'object_id': 'a', 'neighbors': []});
        }
        if (request.url.path == '/objects/a/context') {
          return jsonRes({
            'object': objectDetailJson(id: 'a', title: 'Card A'),
            'edges': [],
            'neighbors': [],
          });
        }
        if (request.url.path == '/objects/a/labels') {
          return jsonRes({'labels': []});
        }
        if (request.method == 'PUT' &&
            request.url.path == '/inbox/review-marker') {
          putCalls++;
          return jsonRes({
            'anchor_feed_at': '2026-09-09T12:00:00Z',
            'anchor_object_id': 'a',
            'updated_at': '2026-09-09T13:00:00Z',
          });
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    await tester.pumpWidget(pumpInbox(apiClient));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Card A'));
    await tester.pumpAndSettle();
    expect(putCalls, 0);
    expect(find.text('Card A'), findsWidgets);
    debugDefaultTargetPlatformOverride = null;
  });

  testWidgets('marker hover over card shows preview below then clears',
      (tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.linux;
    addTearDown(() {
      debugDefaultTargetPlatformOverride = null;
    });
    tester.view.physicalSize = const Size(800, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox' &&
            !request.url.path.endsWith('/inbox/feed')) {
          return jsonRes(
            inboxPayload(
              sources: [
                sourceRow(
                  id: 'a',
                  title: 'Card A',
                  feedAt: '2026-09-09T12:00:00Z',
                ),
                sourceRow(
                  id: 'b',
                  title: 'Card B',
                  feedAt: '2026-09-08T12:00:00Z',
                ),
              ],
            ),
          );
        }
        if (request.url.path == '/labels/by-objects' ||
            request.url.path == '/object-bookmarks/by-objects') {
          return jsonRes({'objects': {}});
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    await tester.pumpWidget(pumpInbox(apiClient));
    await tester.pumpAndSettle();
    final handle = find.byKey(const Key('inbox_review_marker_handle'));
    final gesture = await tester.startGesture(tester.getCenter(handle));
    await tester.pump();
    await gesture.moveTo(tester.getCenter(find.text('Card A')));
    await tester.pump();
    expect(
      find.byKey(const Key('inbox_review_marker_card_preview_a')),
      findsOneWidget,
    );
    await gesture.moveTo(const Offset(12, 12));
    await tester.pump();
    expect(
      find.byKey(const Key('inbox_review_marker_card_preview_a')),
      findsNothing,
    );
    await gesture.up();
    await tester.pumpAndSettle();
    debugDefaultTargetPlatformOverride = null;
  });

  testWidgets('card tap still opens detail and feed still scrolls',
      (tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.linux;
    addTearDown(() {
      debugDefaultTargetPlatformOverride = null;
    });
    tester.view.physicalSize = const Size(800, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox' &&
            !request.url.path.endsWith('/inbox/feed')) {
          return jsonRes(
            inboxPayload(
              sources: [
                sourceRow(
                  id: 'a',
                  title: 'Card A',
                  feedAt: '2026-09-09T12:00:00Z',
                ),
                sourceRow(
                  id: 'b',
                  title: 'Card B',
                  feedAt: '2026-09-08T12:00:00Z',
                ),
              ],
            ),
          );
        }
        if (request.url.path == '/labels/by-objects' ||
            request.url.path == '/object-bookmarks/by-objects') {
          return jsonRes({'objects': {}});
        }
        if (request.url.path == '/objects/a') {
          return jsonRes(objectDetailJson(id: 'a', title: 'Card A'));
        }
        if (request.url.path == '/objects/a/neighbors') {
          return jsonRes({'object_id': 'a', 'neighbors': []});
        }
        if (request.url.path == '/objects/a/context') {
          return jsonRes({
            'object': objectDetailJson(id: 'a', title: 'Card A'),
            'edges': [],
            'neighbors': [],
          });
        }
        if (request.url.path == '/objects/a/labels') {
          return jsonRes({'labels': []});
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    await tester.pumpWidget(pumpInbox(apiClient));
    await tester.pumpAndSettle();
    await tester.drag(find.byKey(const Key('inbox_feed_list')), const Offset(0, -40));
    await tester.pumpAndSettle();
    expect(find.text('Card A'), findsOneWidget);
    await tester.tap(find.text('Card A'));
    await tester.pumpAndSettle();
    expect(find.text('Card A'), findsWidgets);
    debugDefaultTargetPlatformOverride = null;
  });

  testWidgets('linux rail click persists marker without swipe-to-remove', (
    tester,
  ) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.linux;
    addTearDown(() {
      debugDefaultTargetPlatformOverride = null;
    });
    tester.view.physicalSize = const Size(800, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var putCalls = 0;
    var objectGets = 0;
    var feedCalls = 0;
    String? putAfter;
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox' &&
            !request.url.path.endsWith('/inbox/feed')) {
          return jsonRes(
            inboxPayload(
              sources: [
                sourceRow(
                  id: 'a',
                  title: 'Card A',
                  feedAt: '2026-09-09T12:00:00Z',
                ),
                sourceRow(
                  id: 'b',
                  title: 'Card B',
                  feedAt: '2026-09-08T12:00:00Z',
                ),
              ],
              hasMore: true,
            ),
          );
        }
        if (request.url.path.endsWith('/inbox/feed')) {
          feedCalls++;
          return jsonRes({}, 404);
        }
        if (request.url.path == '/labels/by-objects' ||
            request.url.path == '/object-bookmarks/by-objects') {
          return jsonRes({'objects': {}});
        }
        if (request.method == 'PUT' &&
            request.url.path == '/inbox/review-marker') {
          putCalls++;
          putAfter =
              (jsonDecode(request.body) as Map)['after_object_id'] as String;
          return jsonRes({
            'anchor_feed_at':
                putAfter == 'b' ? '2026-09-08T12:00:00Z' : '2026-09-09T12:00:00Z',
            'anchor_object_id': putAfter,
            'updated_at': '2026-09-09T13:00:00Z',
          });
        }
        if (request.method == 'DELETE' &&
            request.url.path == '/inbox/review-marker') {
          return jsonRes({});
        }
        if (request.url.path.startsWith('/objects/')) {
          objectGets++;
          return jsonRes({}, 404);
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    await tester.pumpWidget(pumpInbox(apiClient));
    await tester.pumpAndSettle();
    expect(find.byType(InboxSwipeToRemove), findsNothing);
    expect(find.byKey(const Key('inbox_review_rail_b')), findsOneWidget);
    expect(find.byKey(const Key('inbox_review_marker_handle')), findsOneWidget);

    await tester.tap(find.byKey(const Key('inbox_review_rail_b')));
    await tester.pumpAndSettle();
    expect(putCalls, 1);
    expect(putAfter, 'b');
    expect(objectGets, 0);
    expect(feedCalls, 0);
    expect(find.byKey(const Key('inbox_review_marker')), findsOneWidget);
    expect(find.text('Просмотрено досюда'), findsOneWidget);
    final label = tester.widget<Text>(find.text('Просмотрено досюда'));
    expect(label.style?.color, kInboxReviewMarkerAccent);
    expect(label.style?.fontWeight, FontWeight.w600);
    final line = tester.widget<Divider>(
      find.byKey(const Key('inbox_review_marker_line')),
    );
    expect(line.thickness, 2);
    expect(line.color, kInboxReviewMarkerAccent);

    await tester.tap(find.byKey(const Key('inbox_review_rail_reset')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('inbox_review_marker')), findsNothing);
    debugDefaultTargetPlatformOverride = null;
  });

  testWidgets('linux rail persistence failure restores previous marker', (
    tester,
  ) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.linux;
    addTearDown(() {
      debugDefaultTargetPlatformOverride = null;
    });
    tester.view.physicalSize = const Size(800, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox' &&
            !request.url.path.endsWith('/inbox/feed')) {
          return jsonRes({
            ...inboxPayload(
              sources: [
                sourceRow(
                  id: 'a',
                  title: 'Card A',
                  feedAt: '2026-09-09T12:00:00Z',
                ),
                sourceRow(
                  id: 'b',
                  title: 'Card B',
                  feedAt: '2026-09-08T12:00:00Z',
                ),
              ],
            ),
            'review_marker': {
              'anchor_feed_at': '2026-09-09T12:00:00Z',
              'anchor_object_id': 'a',
              'updated_at': '2026-09-09T13:00:00Z',
            },
          });
        }
        if (request.url.path == '/labels/by-objects' ||
            request.url.path == '/object-bookmarks/by-objects') {
          return jsonRes({'objects': {}});
        }
        if (request.method == 'PUT' &&
            request.url.path == '/inbox/review-marker') {
          return jsonRes({'detail': 'boom'}, 500);
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    await tester.pumpWidget(pumpInbox(apiClient));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('inbox_review_marker')), findsOneWidget);
    await tester.tap(find.byKey(const Key('inbox_review_rail_b')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('inbox_review_marker')), findsOneWidget);
    expect(find.text('Просмотрено досюда'), findsOneWidget);
    debugDefaultTargetPlatformOverride = null;
  });
}
