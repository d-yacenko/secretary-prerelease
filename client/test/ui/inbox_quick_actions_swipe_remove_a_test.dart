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
import 'package:personal_secretary/inbox/inbox_review_marker.dart';
import 'package:personal_secretary/inbox/inbox_screen.dart';
import 'package:personal_secretary/inbox/inbox_swipe_to_remove.dart';
import 'package:personal_secretary/ui/object_bookmark_controller.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'temporal_correctness_inbox_feed_a_test.dart';

Future<void> withPlatform(
  WidgetTester tester, {
  required TargetPlatform platform,
  Size size = const Size(360, 760),
  required Future<void> Function() body,
}) async {
  debugDefaultTargetPlatformOverride = platform;
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(() {
    debugDefaultTargetPlatformOverride = null;
  });
  try {
    await body();
  } finally {
    debugDefaultTargetPlatformOverride = null;
  }
}

Future<void> dragHandleToGap(
  WidgetTester tester, {
  required String gapId,
}) async {
  final handle = find.byKey(const Key('inbox_review_marker_handle'));
  final gap = find.byKey(Key('inbox_review_marker_gap_$gapId'));
  final gesture = await tester.startGesture(tester.getCenter(handle));
  await tester.pump();
  await gesture.moveTo(tester.getCenter(gap));
  await tester.pump();
  await gesture.up();
  await tester.pumpAndSettle();
}

Future<void> dragHandleToCard(
  WidgetTester tester, {
  required String title,
}) async {
  final handle = find.byKey(const Key('inbox_review_marker_handle'));
  final card = find.text(title);
  final gesture = await tester.startGesture(tester.getCenter(handle));
  await tester.pump();
  await gesture.moveTo(tester.getCenter(card));
  await tester.pump();
  await gesture.up();
  await tester.pumpAndSettle();
}

Map<String, dynamic> deleteOk(String id) {
  return {
    'object_id': id,
    'deleted_at': '2026-09-10T12:00:00Z',
    'already_deleted': false,
  };
}

Map<String, dynamic> inboxWith({
  required List<Map<String, dynamic>> sources,
  String? cursor,
  bool hasMore = false,
  Map<String, dynamic>? reviewMarker,
}) {
  return {
    ...inboxPayload(sources: sources, cursor: cursor, hasMore: hasMore),
    if (reviewMarker != null) 'review_marker': reviewMarker,
  };
}

List<Map<String, dynamic>> cardsABC() {
  return [
    sourceRow(id: 'a', title: 'Card A', feedAt: '2026-09-09T12:00:00Z'),
    sourceRow(id: 'b', title: 'Card B', feedAt: '2026-09-09T11:00:00Z'),
    sourceRow(id: 'c', title: 'Card C', feedAt: '2026-09-09T10:00:00Z'),
  ];
}

class InboxHarness {
  InboxHarness({
    List<Map<String, dynamic>>? sources,
    this.hasMore = false,
    this.cursor,
    this.reviewMarker,
    this.bookmarks = const {},
    this.deleteStatus = 200,
    this.deleteError,
    this.continuation = const [],
  }) : sources = sources ?? cardsABC();

  final List<Map<String, dynamic>> sources;
  final bool hasMore;
  final String? cursor;
  final Map<String, dynamic>? reviewMarker;
  final Map<String, String> bookmarks;
  int deleteStatus;
  final String? deleteError;
  final List<Map<String, dynamic>> continuation;

  int inboxCalls = 0;
  int feedCalls = 0;
  int deleteCalls = 0;
  final List<String> deletedIds = [];
  int markerPutCalls = 0;
  int markerDeleteCalls = 0;
  String? putAfter;

  late final SecretaryApiClient apiClient = SecretaryApiClient(
    httpClient: MockClient((request) async => _handle(request)),
  );

  Future<http.Response> _handle(http.Request request) async {
    if (request.url.path == '/inbox' &&
        !request.url.path.endsWith('/inbox/feed')) {
      inboxCalls++;
      return jsonRes(
        inboxWith(
          sources: sources,
          cursor: cursor,
          hasMore: hasMore,
          reviewMarker: reviewMarker,
        ),
      );
    }
    if (request.url.path.endsWith('/inbox/feed')) {
      feedCalls++;
      return jsonRes({
        'items': continuation,
        'next_cursor': null,
        'has_more': false,
      });
    }
    if (request.url.path == '/labels/by-objects') {
      return jsonRes({'objects': {}});
    }
    if (request.url.path == '/object-bookmarks/by-objects') {
      return jsonRes({
        'objects': {
          for (final entry in bookmarks.entries)
            entry.key: {'color': entry.value},
        },
      });
    }
    if (request.method == 'PUT' &&
        request.url.path.startsWith('/object-bookmarks/')) {
      final color = (jsonDecode(request.body) as Map)['color'] as String;
      return jsonRes({
        'object_id': request.url.path.split('/').last,
        'color': color,
        'updated_at': '2026-09-09T13:00:00Z',
      });
    }
    if (request.method == 'PUT' && request.url.path == '/inbox/review-marker') {
      markerPutCalls++;
      putAfter = (jsonDecode(request.body) as Map)['after_object_id'] as String;
      return jsonRes({
        'anchor_feed_at': '2026-09-09T11:00:00Z',
        'anchor_object_id': putAfter,
        'updated_at': '2026-09-09T13:00:00Z',
      });
    }
    if (request.method == 'DELETE' &&
        request.url.path == '/inbox/review-marker') {
      markerDeleteCalls++;
      return jsonRes({});
    }
    if (request.method == 'DELETE' &&
        request.url.path.startsWith('/objects/')) {
      deleteCalls++;
      deletedIds.add(request.url.path.split('/').last);
      if (deleteStatus != 200) {
        return jsonRes({'detail': deleteError ?? 'boom'}, deleteStatus);
      }
      return jsonRes(deleteOk(request.url.path.split('/').last));
    }
    return jsonRes({}, 404);
  }
}

Widget pumpHarness(
  InboxHarness harness, {
  ObjectBookmarkController? bookmarkController,
  AuthController? authController,
  bool desktopActions = false,
}) {
  final apiClient = harness.apiClient;
  apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
  final auth =
      authController ??
      AuthController(
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
        bookmarkController: bookmarkController,
        onAskSecretary: desktopActions ? (_) {} : null,
        onShowInGraph: desktopActions ? (_) {} : null,
      ),
    ),
  );
}

Finder swipeCard(String id) => find.byKey(Key('inbox_swipe_remove_$id'));

Future<void> swipeEndToStart(
  WidgetTester tester,
  Finder card, {
  double dx = -320,
}) async {
  await tester.drag(card, Offset(dx, 0));
  await tester.pumpAndSettle();
}

Future<TestGesture> dragHold(
  WidgetTester tester,
  Finder finder,
  Offset total, {
  int steps = 16,
}) async {
  final gesture = await tester.startGesture(tester.getCenter(finder));
  await tester.pump();
  final step = Offset(total.dx / steps, total.dy / steps);
  for (var i = 0; i < steps; i++) {
    await gesture.moveBy(step);
    await tester.pump();
  }
  return gesture;
}

Future<void> cancelDelete(WidgetTester tester) async {
  await tester.tap(find.text('Отмена'));
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  test('swipe-to-remove is touch-only', () {
    expect(inboxUsesSwipeToRemove(TargetPlatform.android), isTrue);
    expect(inboxUsesSwipeToRemove(TargetPlatform.iOS), isTrue);
    expect(inboxUsesSwipeToRemove(TargetPlatform.linux), isFalse);
    expect(inboxUsesSwipeToRemove(TargetPlatform.windows), isFalse);
    expect(inboxUsesSwipeToRemove(TargetPlatform.macOS), isFalse);
  });

  test(
    'review rail is available on Android and Linux without enabling swipe',
    () {
      expect(inboxUsesReviewRail(TargetPlatform.android), isTrue);
      expect(inboxUsesReviewRail(TargetPlatform.linux), isTrue);
      expect(inboxUsesTouchReviewRail(TargetPlatform.linux), isFalse);
      expect(inboxUsesSwipeToRemove(TargetPlatform.linux), isFalse);
    },
  );

  test('activation threshold is usable on phone and tablet widths', () {
    expect(inboxSwipeRemoveDismissThreshold(324), closeTo(96 / 324, 0.001));
    expect(inboxSwipeRemoveDismissThreshold(764), 0.18);
    expect(inboxSwipeRemoveDismissThreshold(764) * 764, closeTo(137.5, 0.2));
    expect(inboxSwipeRemoveDismissThreshold(360), lessThan(0.4));
  });

  test('direct-delete threshold is ~180px on phone and tablet', () {
    expect(inboxSwipeDirectDeleteThreshold(308), closeTo(180 / 308, 0.001));
    expect(inboxSwipeDirectDeleteThreshold(308) * 308, closeTo(180, 0.5));
    expect(inboxSwipeDirectDeleteThreshold(324), closeTo(180 / 324, 0.001));
    expect(inboxSwipeDirectDeleteThreshold(748), closeTo(180 / 748, 0.001));
    expect(inboxSwipeDirectDeleteThreshold(748) * 748, closeTo(180, 0.5));
    expect(inboxSwipeDirectDeleteThreshold(764), 0.24);
    expect(inboxSwipeDirectDeleteThreshold(764) * 764, closeTo(183.4, 0.5));
    expect(
      inboxSwipeDirectDeleteThreshold(308),
      greaterThan(inboxSwipeRemoveDismissThreshold(308)),
    );
  });

  test('missing anchor still interpolates after neighbor deletion', () {
    final remaining = [
      InboxSourceObjectOut(
        id: 'a',
        title: 'Card A',
        kind: 'email',
        provider: 'gmail',
        origin: 'source',
        state: 'observed',
        status: null,
        primaryAt: '2026-09-09T12:00:00Z',
        excerpt: 'x',
        feedAt: '2026-09-09T12:00:00Z',
      ),
      InboxSourceObjectOut(
        id: 'c',
        title: 'Card C',
        kind: 'email',
        provider: 'gmail',
        origin: 'source',
        state: 'observed',
        status: null,
        primaryAt: '2026-09-09T10:00:00Z',
        excerpt: 'x',
        feedAt: '2026-09-09T10:00:00Z',
      ),
    ];
    final marker = InboxReviewMarker(
      anchorFeedAt: '2026-09-09T11:00:00Z',
      anchorObjectId: 'b',
      updatedAt: '2026-09-09T13:00:00Z',
    );
    expect(
      reviewMarkerInsertIndex(
        objects: remaining,
        marker: marker,
        hasMore: false,
      ),
      1,
    );
  });

  testWidgets('A: below armed threshold restores with no dialog or DELETE', (
    tester,
  ) async {
    await withPlatform(
      tester,
      platform: TargetPlatform.android,
      body: () async {
        final harness = InboxHarness();
        await tester.pumpWidget(pumpHarness(harness));
        await tester.pumpAndSettle();

        expect(swipeCard('a'), findsOneWidget);
        expect(find.byType(Dismissible), findsNWidgets(3));

        await tester.drag(find.text('Card A'), const Offset(240, 0));
        await tester.pumpAndSettle();
        expect(find.byType(AlertDialog), findsNothing);
        expect(harness.deleteCalls, 0);
        expect(find.text('Card A'), findsOneWidget);

        await swipeEndToStart(tester, find.text('Card A'), dx: -100);
        expect(find.byType(AlertDialog), findsNothing);
        expect(harness.deleteCalls, 0);
        expect(find.text('Card A'), findsOneWidget);
      },
    );
  });

  testWidgets('B: armed visual appears after crossing the direct threshold', (
    tester,
  ) async {
    await withPlatform(
      tester,
      platform: TargetPlatform.android,
      body: () async {
        final harness = InboxHarness();
        await tester.pumpWidget(pumpHarness(harness));
        await tester.pumpAndSettle();

        final gesture = await dragHold(
          tester,
          find.text('Card B'),
          const Offset(-240, 0),
        );
        expect(find.byType(AlertDialog), findsNothing);
        expect(find.text('Отпустите, чтобы удалить'), findsOneWidget);
        expect(harness.deleteCalls, 0);
        await gesture.moveBy(const Offset(200, 0));
        await tester.pump();
        expect(find.text('Отпустите, чтобы удалить'), findsNothing);
        await gesture.up();
        await tester.pumpAndSettle();
        expect(harness.deleteCalls, 0);
        expect(find.text('Card B'), findsOneWidget);
      },
    );
  });

  testWidgets('C: dragging back below armed threshold does not delete', (
    tester,
  ) async {
    await withPlatform(
      tester,
      platform: TargetPlatform.android,
      body: () async {
        final harness = InboxHarness();
        await tester.pumpWidget(pumpHarness(harness));
        await tester.pumpAndSettle();

        final gesture = await dragHold(
          tester,
          find.text('Card B'),
          const Offset(-240, 0),
        );
        expect(find.text('Отпустите, чтобы удалить'), findsOneWidget);
        await gesture.moveBy(const Offset(200, 0));
        await tester.pump();
        expect(find.text('Отпустите, чтобы удалить'), findsNothing);
        await gesture.up();
        await tester.pumpAndSettle();
        expect(find.byType(AlertDialog), findsNothing);
        expect(harness.deleteCalls, 0);
        expect(find.text('Card B'), findsOneWidget);
      },
    );
  });

  testWidgets('D: armed full swipe deletes without a dialog or Inbox reload', (
    tester,
  ) async {
    await withPlatform(
      tester,
      platform: TargetPlatform.android,
      body: () async {
        final harness = InboxHarness(
          hasMore: true,
          cursor: 'cursor-1',
          continuation: [
            sourceRow(id: 'd', title: 'Card D', feedAt: '2026-09-08T09:00:00Z'),
          ],
          bookmarks: const {'b': 'red'},
        );
        await tester.pumpWidget(pumpHarness(harness));
        await tester.pumpAndSettle();
        if (find.text('Card D').evaluate().isEmpty) {
          inboxFeedPosition(
            tester,
          ).jumpTo(inboxFeedPosition(tester).maxScrollExtent);
          await tester.pumpAndSettle();
        }

        final inboxBefore = harness.inboxCalls;
        final feedBefore = harness.feedCalls;
        expect(find.byKey(const Key('object_bookmark_tab')), findsOneWidget);

        await swipeEndToStart(tester, find.text('Card B'));
        expect(find.byType(AlertDialog), findsNothing);
        expect(harness.deleteCalls, 1);
        expect(harness.deletedIds, ['b']);
        expect(harness.inboxCalls, inboxBefore);
        expect(harness.feedCalls, feedBefore);
        expect(find.text('Card B'), findsNothing);
        expect(find.text('Card A'), findsOneWidget);
        expect(find.text('Card C'), findsOneWidget);
        expect(find.byKey(const Key('object_bookmark_tab')), findsNothing);
        expect(swipeCard('b'), findsNothing);
      },
    );
  });

  testWidgets(
    'adjacent provider-backed cards can be swipe-deleted in succession',
    (tester) async {
      await withPlatform(
        tester,
        platform: TargetPlatform.android,
        body: () async {
          final harness = InboxHarness();
          await tester.pumpWidget(pumpHarness(harness));
          await tester.pumpAndSettle();

          await swipeEndToStart(tester, find.text('Card A'));
          expect(harness.deletedIds, ['a']);
          expect(find.text('Card A'), findsNothing);
          expect(find.text('Card B'), findsOneWidget);
          expect(find.text('Card C'), findsOneWidget);

          await swipeEndToStart(tester, find.text('Card B'));
          expect(harness.deletedIds, ['a', 'b']);
          expect(find.text('Card B'), findsNothing);
          expect(find.text('Card C'), findsOneWidget);

          await swipeEndToStart(tester, find.text('Card C'));
          expect(harness.deleteCalls, 3);
          expect(harness.deletedIds, ['a', 'b', 'c']);
          expect(find.text('Card C'), findsNothing);
          expect(find.byType(AlertDialog), findsNothing);
        },
      );
    },
  );

  testWidgets('E: direct swipe API failure restores the card without a modal', (
    tester,
  ) async {
    await withPlatform(
      tester,
      platform: TargetPlatform.android,
      body: () async {
        final harness = InboxHarness(
          deleteStatus: 500,
          deleteError: 'не удалось удалить',
        );
        await tester.pumpWidget(pumpHarness(harness));
        await tester.pumpAndSettle();

        await swipeEndToStart(tester, find.text('Card B'));
        expect(find.byType(AlertDialog), findsNothing);
        expect(harness.deleteCalls, 1);
        expect(find.text('Card B'), findsOneWidget);
        expect(find.text('не удалось удалить'), findsOneWidget);
        expect(swipeCard('b'), findsOneWidget);

        harness.deleteStatus = 200;
        await swipeEndToStart(tester, find.text('Card B'));
        expect(harness.deleteCalls, 2);
        expect(find.text('Card B'), findsNothing);
        expect(find.text('Card A'), findsOneWidget);
      },
    );
  });

  testWidgets('F: vertical drag on a card scrolls and does not delete', (
    tester,
  ) async {
    await withPlatform(
      tester,
      platform: TargetPlatform.android,
      size: const Size(360, 400),
      body: () async {
        final harness = InboxHarness(
          sources: [
            for (var i = 0; i < 12; i++)
              sourceRow(
                id: 'n$i',
                title: 'Row $i',
                feedAt:
                    '2026-09-09T${(20 - i).toString().padLeft(2, '0')}:00:00Z',
              ),
          ],
        );
        await tester.pumpWidget(pumpHarness(harness));
        await tester.pumpAndSettle();

        final before = inboxFeedPosition(tester).pixels;
        await tester.drag(find.text('Row 0'), const Offset(0, -240));
        await tester.pumpAndSettle();
        expect(inboxFeedPosition(tester).pixels, greaterThan(before));
        expect(find.byType(AlertDialog), findsNothing);
        expect(harness.deleteCalls, 0);
      },
    );
  });

  testWidgets('G: rail tap still PUTs; card swipe does not move the marker', (
    tester,
  ) async {
    await withPlatform(
      tester,
      platform: TargetPlatform.android,
      body: () async {
        final harness = InboxHarness();
        await tester.pumpWidget(pumpHarness(harness));
        await tester.pumpAndSettle();

        await tester.tap(find.byKey(const Key('inbox_review_rail_b')));
        await tester.pumpAndSettle();
        expect(harness.markerPutCalls, 1);
        expect(harness.putAfter, 'b');
        expect(find.byType(AlertDialog), findsNothing);
        expect(harness.deleteCalls, 0);
        expect(find.byKey(const Key('inbox_review_marker')), findsOneWidget);

        final markerY = tester
            .getTopLeft(find.byKey(const Key('inbox_review_marker')))
            .dy;
        await swipeEndToStart(tester, find.text('Card A'), dx: -100);
        expect(find.byType(AlertDialog), findsNothing);
        expect(harness.deleteCalls, 0);
        expect(harness.markerPutCalls, 1);
        expect(harness.markerDeleteCalls, 0);
        expect(
          tester.getTopLeft(find.byKey(const Key('inbox_review_marker'))).dy,
          closeTo(markerY, 1),
        );
      },
    );
  });

  testWidgets(
    'H: deleting marker anchor keeps interpolated marker, no marker API',
    (tester) async {
      await withPlatform(
        tester,
        platform: TargetPlatform.android,
        body: () async {
          final harness = InboxHarness(
            reviewMarker: {
              'anchor_feed_at': '2026-09-09T11:00:00Z',
              'anchor_object_id': 'b',
              'updated_at': '2026-09-09T13:00:00Z',
            },
          );
          await tester.pumpWidget(pumpHarness(harness));
          await tester.pumpAndSettle();
          expect(find.byKey(const Key('inbox_review_marker')), findsOneWidget);

          await swipeEndToStart(tester, find.text('Card B'));
          expect(find.byType(AlertDialog), findsNothing);
          expect(find.text('Card B'), findsNothing);
          expect(find.text('Card A'), findsOneWidget);
          expect(find.text('Card C'), findsOneWidget);
          expect(find.byKey(const Key('inbox_review_marker')), findsOneWidget);
          expect(harness.markerPutCalls, 0);
          expect(harness.markerDeleteCalls, 0);

          final aBottom = tester.getRect(find.text('Card A')).bottom;
          final marker = tester.getRect(
            find.byKey(const Key('inbox_review_marker')),
          );
          final cTop = tester.getRect(find.text('Card C')).top;
          expect(marker.top, greaterThan(aBottom));
          expect(marker.bottom, lessThan(cTop));
        },
      );
    },
  );

  testWidgets('I: bookmark tap still opens palette; swipe forgets cache', (
    tester,
  ) async {
    await withPlatform(
      tester,
      platform: TargetPlatform.android,
      body: () async {
        final harness = InboxHarness(bookmarks: const {'b': 'red'});
        final auth = AuthController(
          apiClient: harness.apiClient,
          tokenStore: FakeTokenStore(),
          serverUrlStore: FakeServerUrlStore(),
        );
        auth.status = AuthStatus.authenticated;
        final bookmarks = ObjectBookmarkController(
          apiClient: harness.apiClient,
          authController: auth,
        );
        await tester.pumpWidget(
          pumpHarness(
            harness,
            bookmarkController: bookmarks,
            authController: auth,
          ),
        );
        await tester.pumpAndSettle();
        expect(bookmarks.colorFor('b'), 'red');
        expect(find.byKey(const Key('object_bookmark_tab')), findsOneWidget);

        await tester.tap(find.byKey(const Key('object_bookmark_tab')));
        await tester.pumpAndSettle();
        expect(find.text('Синий'), findsOneWidget);
        await tester.tap(find.text('Синий'));
        await tester.pumpAndSettle();
        expect(bookmarks.colorFor('b'), 'blue');

        await swipeEndToStart(tester, find.text('Card B'));
        expect(find.byType(AlertDialog), findsNothing);
        expect(find.text('Card B'), findsNothing);
        expect(find.byKey(const Key('object_bookmark_tab')), findsNothing);
        expect(bookmarks.colorFor('b'), isNull);
        expect(find.text('Card A'), findsOneWidget);
      },
    );
  });

  testWidgets('J: tablet swipe still activates without overflow', (
    tester,
  ) async {
    await withPlatform(
      tester,
      platform: TargetPlatform.android,
      size: const Size(800, 1280),
      body: () async {
        final harness = InboxHarness();
        await tester.pumpWidget(pumpHarness(harness));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);

        final list = tester.getRect(find.byKey(const Key('inbox_feed_list')));
        final card = tester.getRect(swipeCard('b'));
        final rail = tester.getRect(
          find.byKey(const Key('inbox_review_rail_b')),
        );
        expect(card.left, closeTo(rail.right, 0.5));
        expect(card.right, lessThanOrEqualTo(list.right + 0.5));
        expect(card.width, greaterThan(600));
        expect(
          inboxSwipeDirectDeleteThreshold(card.width),
          closeTo((180 / card.width).clamp(0.24, 0.60), 0.001),
        );
        expect(
          inboxSwipeDirectDeleteThreshold(card.width) * card.width,
          closeTo(card.width <= 180 / 0.24 ? 180 : 0.24 * card.width, 1),
        );

        await swipeEndToStart(tester, find.text('Card B'), dx: -220);
        expect(find.byType(AlertDialog), findsNothing);
        expect(tester.takeException(), isNull);
        expect(harness.deleteCalls, 1);
        expect(find.text('Card B'), findsNothing);
        expect(find.text('Card A'), findsOneWidget);
        expect(tester.takeException(), isNull);
      },
    );
  });

  testWidgets('note swipe keeps the existing confirmation dialog', (
    tester,
  ) async {
    await withPlatform(
      tester,
      platform: TargetPlatform.android,
      body: () async {
        final harness = InboxHarness(
          sources: [
            sourceRow(
              id: 'n',
              title: 'Note N',
              kind: 'note',
              provider: 'gmail',
              feedAt: '2026-09-09T12:00:00Z',
            ),
            sourceRow(id: 'a', title: 'Card A', feedAt: '2026-09-09T11:00:00Z'),
          ],
        );
        await tester.pumpWidget(pumpHarness(harness));
        await tester.pumpAndSettle();

        await swipeEndToStart(tester, find.text('Note N'));
        expect(find.byType(AlertDialog), findsOneWidget);
        expect(find.text('Удалить из Секретаря?'), findsWidgets);
        expect(find.textContaining('Письмо останется'), findsNothing);
        expect(harness.deleteCalls, 0);
        await cancelDelete(tester);
        expect(harness.deleteCalls, 0);
        expect(find.text('Note N'), findsOneWidget);
        expect(find.text('Card A'), findsOneWidget);
      },
    );
  });

  testWidgets('unknown provider swipe is fail-closed to the dialog', (
    tester,
  ) async {
    await withPlatform(
      tester,
      platform: TargetPlatform.android,
      body: () async {
        final harness = InboxHarness(
          sources: [
            sourceRow(
              id: 'u',
              title: 'Mystery',
              kind: 'chat_message',
              provider: 'telegram',
              feedAt: '2026-09-09T12:00:00Z',
            ),
          ],
        );
        await tester.pumpWidget(pumpHarness(harness));
        await tester.pumpAndSettle();

        await swipeEndToStart(tester, find.text('Mystery'));
        expect(find.byType(AlertDialog), findsOneWidget);
        expect(find.text('Удалить из Секретаря?'), findsWidgets);
        expect(harness.deleteCalls, 0);
        await cancelDelete(tester);
        expect(find.text('Mystery'), findsOneWidget);
        expect(harness.deleteCalls, 0);
      },
    );
  });

  testWidgets('Linux keeps DragTarget Review Marker and has no swipe wrapper', (
    tester,
  ) async {
    await withPlatform(
      tester,
      platform: TargetPlatform.linux,
      size: const Size(800, 900),
      body: () async {
        final harness = InboxHarness(bookmarks: const {'a': 'red'});
        await tester.pumpWidget(pumpHarness(harness));
        await tester.pumpAndSettle();

        expect(find.byType(Dismissible), findsNothing);
        expect(swipeCard('a'), findsNothing);
        expect(
          find.byKey(const Key('inbox_review_marker_handle')),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key('inbox_review_marker_card_a')),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key('inbox_review_marker_gap_a')),
          findsOneWidget,
        );
        expect(find.byKey(const Key('object_bookmark_tab')), findsOneWidget);

        await tester.tap(find.byKey(const Key('object_bookmark_tab')));
        await tester.pumpAndSettle();
        expect(find.text('Синий'), findsOneWidget);
        await tester.tapAt(Offset.zero);
        await tester.pumpAndSettle();

        await dragHandleToCard(tester, title: 'Card A');
        expect(harness.markerPutCalls, 1);
        expect(harness.putAfter, 'a');
        expect(find.byKey(const Key('inbox_review_marker')), findsOneWidget);

        await dragHandleToGap(tester, gapId: 'c');
        expect(harness.markerPutCalls, 2);
        expect(harness.putAfter, 'c');
        expect(harness.deleteCalls, 0);
        expect(find.byType(AlertDialog), findsNothing);
      },
    );
  });

  testWidgets(
    'Linux trash follows Ask Secretary and Graph and deletes locally',
    (tester) async {
      await withPlatform(
        tester,
        platform: TargetPlatform.linux,
        size: const Size(800, 900),
        body: () async {
          final harness = InboxHarness();
          await tester.pumpWidget(pumpHarness(harness, desktopActions: true));
          await tester.pumpAndSettle();
          final trash = find.byKey(const Key('inbox_card_delete_b'));
          final card = find
              .ancestor(of: trash, matching: find.byType(Card))
              .first;
          final ask = tester.getCenter(
            find.descendant(
              of: card,
              matching: find.text('Спросить секретаря'),
            ),
          );
          final graph = tester.getCenter(
            find.descendant(of: card, matching: find.text('Открыть в графе')),
          );
          final trashCenter = tester.getCenter(trash);
          int visualOrder(Offset left, Offset right) {
            final dy = left.dy.compareTo(right.dy);
            return dy != 0 ? dy : left.dx.compareTo(right.dx);
          }

          expect(visualOrder(ask, graph), lessThan(0));
          expect(visualOrder(graph, trashCenter), lessThan(0));
          final cardRect = tester.getRect(card);
          expect(cardRect.contains(trashCenter), isTrue);
          final inboxCalls = harness.inboxCalls;
          await tester.tap(find.byKey(const Key('inbox_card_delete_b')));
          await tester.pumpAndSettle();
          expect(harness.deleteCalls, 1);
          expect(harness.deletedIds, ['b']);
          expect(find.text('Card B'), findsNothing);
          expect(harness.inboxCalls, inboxCalls);
          expect(find.byType(AlertDialog), findsNothing);
        },
      );
    },
  );

  testWidgets(
    'Linux trash keeps confirmation for notes and the card on failure',
    (tester) async {
      await withPlatform(
        tester,
        platform: TargetPlatform.linux,
        size: const Size(800, 900),
        body: () async {
          final harness = InboxHarness(
            sources: [
              sourceRow(
                id: 'n',
                title: 'Note N',
                kind: 'note',
                provider: 'local',
                feedAt: '2026-09-09T12:00:00Z',
              ),
            ],
          );
          await tester.pumpWidget(pumpHarness(harness, desktopActions: true));
          await tester.pumpAndSettle();
          await tester.tap(find.byKey(const Key('inbox_card_delete_n')));
          await tester.pumpAndSettle();
          expect(find.text('Удалить из Секретаря?'), findsWidgets);
          expect(harness.deleteCalls, 0);
          await tester.tap(find.widgetWithText(FilledButton, 'Удалить'));
          await tester.pumpAndSettle();
          expect(harness.deleteCalls, 1);
          expect(find.text('Note N'), findsNothing);
        },
      );
    },
  );

  testWidgets('Linux cancelled trash keeps the card', (tester) async {
    await withPlatform(
      tester,
      platform: TargetPlatform.linux,
      size: const Size(800, 900),
      body: () async {
        final harness = InboxHarness(
          sources: [
            sourceRow(
              id: 'n',
              title: 'Note N',
              kind: 'note',
              provider: 'local',
              feedAt: '2026-09-09T12:00:00Z',
            ),
          ],
        );
        await tester.pumpWidget(pumpHarness(harness, desktopActions: true));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('inbox_card_delete_n')));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Отмена'));
        await tester.pumpAndSettle();
        expect(harness.deleteCalls, 0);
        expect(find.text('Note N'), findsOneWidget);
        expect(find.byKey(const Key('inbox_card_delete_n')), findsOneWidget);
      },
    );
  });

  testWidgets('Linux failed trash keeps the card', (tester) async {
    await withPlatform(
      tester,
      platform: TargetPlatform.linux,
      size: const Size(800, 900),
      body: () async {
        final failed = InboxHarness(
          sources: [
            sourceRow(id: 'a', title: 'Card A', feedAt: '2026-09-09T12:00:00Z'),
          ],
          deleteStatus: 500,
        );
        await tester.pumpWidget(pumpHarness(failed, desktopActions: true));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('inbox_card_delete_a')));
        await tester.pumpAndSettle();
        expect(find.text('Card A'), findsOneWidget);
        expect(failed.deleteCalls, 1);
      },
    );
  });

  testWidgets('macOS list card shows trash and has no swipe', (tester) async {
    await withPlatform(
      tester,
      platform: TargetPlatform.macOS,
      size: const Size(900, 700),
      body: () async {
        final harness = InboxHarness();
        await tester.pumpWidget(pumpHarness(harness, desktopActions: true));
        await tester.pumpAndSettle();
        expect(find.byType(InboxSwipeToRemove), findsNothing);
        final trash = find.byKey(const Key('inbox_card_delete_b'));
        expect(trash, findsOneWidget);
        final card = find.ancestor(of: trash, matching: find.byType(Card)).first;
        expect(tester.getRect(card).contains(tester.getCenter(trash)), isTrue);
      },
    );
  });

  testWidgets('Android inbox keeps swipe and hides the desktop trash button', (
    tester,
  ) async {
    await withPlatform(
      tester,
      platform: TargetPlatform.android,
      size: const Size(360, 760),
      body: () async {
        final harness = InboxHarness();
        await tester.pumpWidget(pumpHarness(harness, desktopActions: true));
        await tester.pumpAndSettle();
        expect(find.byType(InboxSwipeToRemove), findsWidgets);
        expect(find.byKey(const Key('inbox_card_delete_a')), findsNothing);
      },
    );
  });

  testWidgets('iOS inbox keeps swipe and hides the desktop trash button', (
    tester,
  ) async {
    await withPlatform(
      tester,
      platform: TargetPlatform.iOS,
      size: const Size(360, 760),
      body: () async {
        final harness = InboxHarness();
        await tester.pumpWidget(pumpHarness(harness, desktopActions: true));
        await tester.pumpAndSettle();
        expect(find.byType(InboxSwipeToRemove), findsWidgets);
        expect(find.byKey(const Key('inbox_card_delete_a')), findsNothing);
      },
    );
  });

  testWidgets('Windows list card shows trash and has no swipe', (tester) async {
    await withPlatform(
      tester,
      platform: TargetPlatform.windows,
      size: const Size(900, 700),
      body: () async {
        final harness = InboxHarness();
        await tester.pumpWidget(pumpHarness(harness, desktopActions: true));
        await tester.pumpAndSettle();
        expect(find.byType(InboxSwipeToRemove), findsNothing);
        expect(find.byKey(const Key('inbox_card_delete_b')), findsOneWidget);
      },
    );
  });
}
