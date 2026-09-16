import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/capture/capture_controller.dart';
import 'package:personal_secretary/graph/graph_workspace_screen.dart';
import 'package:personal_secretary/objects/object_detail_screen.dart';
import 'package:personal_secretary/search/search_screen.dart';
import 'package:personal_secretary/today/today_screen.dart';
import 'package:personal_secretary/ui/date_format.dart';
import 'package:personal_secretary/ui/inbox_date_groups.dart';
import 'package:personal_secretary/ui/object_bookmark.dart';
import 'package:personal_secretary/ui/object_bookmark_controller.dart';
import 'package:personal_secretary/ui/object_label_strip.dart';
import 'package:personal_secretary/ui/object_presentation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../graph/graph_test_harness.dart';
import 'temporal_correctness_inbox_feed_a_test.dart';

LabelItem labelItem(String id, String title, {String? description}) {
  return LabelItem(id: id, title: title, description: description);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  group('labels', () {
    testWidgets('zero labels render no tokens', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(body: ObjectLabelStrip(labels: [])),
        ),
      );
      expect(find.text('Work'), findsNothing);
      expect(find.byKey(const Key('object_label_overflow')), findsNothing);
    });

    testWidgets('one or two labels stay compact tokens', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: ObjectLabelStrip(
              labels: [
                labelItem('1', '◎ Личное'),
                labelItem('2', '⚙ Personal Secretary'),
              ],
            ),
          ),
        ),
      );
      expect(find.text('◎ Личное'), findsOneWidget);
      expect(find.text('⚙ Personal Secretary'), findsOneWidget);
      expect(find.byKey(const Key('object_label_overflow')), findsNothing);
      final token = tester.getSize(find.text('◎ Личное'));
      expect(token.height, lessThan(20));
    });

    testWidgets('more than two shows two tokens and +N', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: ObjectLabelStrip(
              labels: [
                labelItem('1', 'Alpha'),
                labelItem('2', 'Beta'),
                labelItem('3', 'Gamma'),
              ],
            ),
          ),
        ),
      );
      expect(find.text('Alpha'), findsOneWidget);
      expect(find.text('Beta'), findsOneWidget);
      expect(find.text('Gamma'), findsNothing);
      expect(find.text('+1'), findsOneWidget);
    });

    testWidgets('description tooltip is retained', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: ObjectLabelStrip(
              labels: [labelItem('1', 'Work', description: 'офис')],
            ),
          ),
        ),
      );
      expect(find.byTooltip('Work\nофис'), findsOneWidget);
    });

    testWidgets('unicode title is not parsed as taxonomy', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: ObjectLabelStrip(
              labels: [
                labelItem('1', '⚙ Personal Secretary'),
                labelItem('2', '🎭 Role'),
              ],
            ),
          ),
        ),
      );
      expect(find.text('⚙ Personal Secretary'), findsOneWidget);
      expect(find.text('🎭 Role'), findsOneWidget);
      final first = tester.widget<Text>(find.text('⚙ Personal Secretary'));
      final second = tester.widget<Text>(find.text('🎭 Role'));
      expect(first.style?.color, second.style?.color);
    });
  });

  group('inbox presentation', () {
    testWidgets('wide source card keeps timestamp at the far right', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(1280, 768);
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
                ],
              ),
            );
          }
          if (request.url.path == '/labels/by-objects') {
            return jsonRes({
              'objects': {
                'a': [
                  {'id': 'l1', 'title': '◎ Личное'},
                  {'id': 'l2', 'title': '⚙ Project'},
                ],
              },
            });
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

      final title = tester.getRect(find.text('Card A'));
      final stamp = tester.getRect(
        find.byKey(const Key('object_compact_header_timestamp')),
      );
      expect(stamp.left, greaterThan(title.right));
      expect(find.text('◎ Личное'), findsOneWidget);
      expect(find.text('⚙ Project'), findsOneWidget);
      expect(find.byType(ObjectMetaActionRow), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('active bookmark does not cover timestamp', (tester) async {
      tester.view.physicalSize = const Size(1280, 768);
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
          if (request.method == 'PUT' &&
              request.url.path == '/object-bookmarks/a') {
            return jsonRes({
              'object_id': 'a',
              'color': 'red',
              'updated_at': '2026-09-09T13:00:00Z',
            });
          }
          return jsonRes({}, 404);
        }),
      );
      apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
      await tester.pumpWidget(pumpInbox(apiClient));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('object_bookmark_control')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Красный'));
      await tester.pumpAndSettle();

      final stamp = tester.getRect(
        find.byKey(const Key('object_compact_header_timestamp')),
      );
      final tab = tester.getRect(find.byKey(const Key('object_bookmark_tab')));
      expect(stamp.right, lessThanOrEqualTo(tab.left + 1));
      expect(find.byKey(const Key('object_bookmark_control')), findsNothing);
    });

    testWidgets('narrow long title and labels do not overflow', (tester) async {
      debugDefaultTargetPlatformOverride = TargetPlatform.linux;
      addTearDown(() {
        debugDefaultTargetPlatformOverride = null;
      });
      tester.view.physicalSize = const Size(360, 760);
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
                  {
                    'id': 'a',
                    'title':
                        'Очень длинное русское название входящего письма которое должно переноситься без вылета',
                    'kind': 'email',
                    'provider': 'yandex_mail',
                    'state': 'observed',
                    'status': null,
                    'origin': 'source',
                    'primary_at': '2026-09-05T12:00:00Z',
                    'feed_at': '2026-09-05T12:00:00Z',
                    'excerpt':
                        'Длинный отрывок текста для узкой ширины экрана телефона',
                  },
                ],
              ),
            );
          }
          if (request.url.path == '/labels/by-objects') {
            return jsonRes({
              'objects': {
                'a': [
                  {
                    'id': 'l1',
                    'title': 'Очень длинное название пользовательской метки',
                  },
                  {'id': 'l2', 'title': '⚙ Personal Secretary'},
                  {'id': 'l3', 'title': '🎭 Extra'},
                ],
              },
            });
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
      expect(tester.takeException(), isNull);
      const title =
          'Очень длинное русское название входящего письма которое должно переноситься без вылета';
      final titleFinder = find.text(title);
      expect(tester.widget<Text>(titleFinder).maxLines, 2);
      expect(tester.getRect(titleFinder).height, greaterThan(30));
      expect(find.text(formatUserTime('2026-09-05T12:00:00Z')), findsOneWidget);
      expect(
        find.text(formatUserDateTime('2026-09-05T12:00:00Z')),
        findsNothing,
      );
      expect(find.text('+1'), findsOneWidget);
      debugDefaultTargetPlatformOverride = null;
    });

    testWidgets('date separators wrap the label with left and right lines', (
      tester,
    ) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Column(
              children: [
                InboxDateSeparator(
                  entry: InboxDateSeparatorEntry(
                    date: DateTime(2026, 9, 9),
                    label: '09 сентября · среда',
                  ),
                ),
                const InboxDateSeparator(
                  entry: InboxDateSeparatorEntry(date: null, label: 'Без даты'),
                ),
              ],
            ),
          ),
        ),
      );
      expect(find.text('09 сентября · среда'), findsOneWidget);
      expect(find.text('Без даты'), findsOneWidget);
      expect(find.byType(InboxDateSeparatorPill), findsNWidgets(2));
      expect(
        find.descendant(
          of: find.byType(InboxDateSeparatorPill).first,
          matching: find.text('09 сентября · среда'),
        ),
        findsOneWidget,
      );
      expect(
        find.descendant(
          of: find.byType(InboxDateSeparatorPill).at(1),
          matching: find.text('Без даты'),
        ),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('inbox_date_separator_pill')),
        findsNWidgets(2),
      );
      expect(
        find.byKey(const Key('inbox_date_separator_line_start')),
        findsNWidgets(2),
      );
      expect(
        find.byKey(const Key('inbox_date_separator_line_end')),
        findsNWidgets(2),
      );
      final datedPill = tester.getSize(
        find.byType(InboxDateSeparatorPill).first,
      );
      expect(datedPill.height, greaterThanOrEqualTo(22));
      expect(datedPill.height, lessThanOrEqualTo(24));
      final scheme = Theme.of(
        tester.element(find.byType(InboxDateSeparatorPill).first),
      ).colorScheme;
      Color pillColor(Finder finder) {
        final box = tester.widget<DecoratedBox>(
          find.descendant(
            of: finder,
            matching: find.byKey(const Key('inbox_date_separator_pill')),
          ),
        );
        return (box.decoration as BoxDecoration).color!;
      }

      expect(
        pillColor(find.byType(InboxDateSeparatorPill).first),
        scheme.tertiaryContainer,
      );
      expect(
        pillColor(find.byType(InboxDateSeparatorPill).first),
        isNot(scheme.secondaryContainer),
      );
      expect(
        pillColor(find.byType(InboxDateSeparatorPill).at(1)),
        scheme.tertiaryContainer,
      );
    });

    testWidgets('date pill stays usable on a narrow long label', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(360, 640);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 360,
              child: InboxDateSeparator(
                entry: InboxDateSeparatorEntry(
                  date: DateTime(2026, 9, 9),
                  label:
                      '09 сентября · среда · очень длинная локализованная подпись',
                ),
              ),
            ),
          ),
        ),
      );
      expect(tester.takeException(), isNull);
      expect(find.byType(InboxDateSeparatorPill), findsOneWidget);
      expect(
        find.byKey(const Key('inbox_date_separator_line_start')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('inbox_date_separator_line_end')),
        findsOneWidget,
      );
    });
  });

  group('bookmark visual cycle', () {
    testWidgets('inbox outline to tab to recolor to remove', (tester) async {
      tester.view.physicalSize = const Size(1280, 768);
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
            return jsonRes({
              'objects': {
                if (stored != null) 'a': {'color': stored},
              },
            });
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

      await tester.tap(find.byKey(const Key('object_bookmark_control')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Красный'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('object_bookmark_control')), findsNothing);
      expect(find.byKey(const Key('object_bookmark_tab')), findsOneWidget);
      expect(find.byType(ObjectBookmarkGlyph), findsOneWidget);
      expect(find.byKey(const Key('object_bookmark_tab_hit')), findsOneWidget);

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
      expect(find.byKey(const Key('object_bookmark_tab_hit')), findsNothing);
      expect(find.byKey(const Key('object_bookmark_control')), findsOneWidget);
    });

    testWidgets('active ribbon keeps small tab and 36 hit target', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(400, 400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      String? color = 'red';
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Center(
              child: StatefulBuilder(
                builder: (context, setState) {
                  return SizedBox(
                    width: 240,
                    height: 80,
                    child: ObjectBookmarkRibbon(
                      color: color,
                      onSelect: (value) => setState(() => color = value),
                      onClear: () => setState(() => color = null),
                      child: const ColoredBox(
                        color: Color(0x00000000),
                        child: Text('card'),
                      ),
                    ),
                  );
                },
              ),
            ),
          ),
        ),
      );

      expect(find.byKey(const Key('object_bookmark_tab')), findsOneWidget);
      expect(find.byKey(const Key('object_bookmark_tab_hit')), findsOneWidget);
      expect(find.byKey(const Key('object_bookmark_control')), findsNothing);
      expect(find.byType(ObjectBookmarkGlyph), findsOneWidget);

      final glyph = tester.getSize(
        find.byKey(const Key('object_bookmark_tab')),
      );
      expect(glyph.width, kBookmarkTabSize.width);
      expect(glyph.height, kBookmarkTabSize.height);
      final hit = tester.getSize(
        find.byKey(const Key('object_bookmark_tab_hit')),
      );
      expect(hit.width, greaterThanOrEqualTo(kBookmarkTabHitSize.width));
      expect(hit.height, greaterThanOrEqualTo(kBookmarkTabHitSize.height));
      expect(hit.width, lessThan(80));
      expect(hit.height, lessThan(80));

      final hitRect = tester.getRect(
        find.byKey(const Key('object_bookmark_tab_hit')),
      );
      final glyphRect = tester.getRect(
        find.byKey(const Key('object_bookmark_tab')),
      );
      expect(glyphRect.right, closeTo(hitRect.right, 0.5));
      expect(glyphRect.top, closeTo(hitRect.top, 0.5));
      await tester.tapAt(Offset(hitRect.left + 4, hitRect.bottom - 4));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Синий'));
      await tester.pumpAndSettle();
      expect(color, 'blue');
      expect(find.byKey(const Key('object_bookmark_tab')), findsOneWidget);
      expect(find.byType(ObjectBookmarkGlyph), findsOneWidget);

      await tester.tap(find.byKey(const Key('object_bookmark_tab_hit')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Убрать закладку'));
      await tester.pumpAndSettle();
      expect(color, isNull);
      expect(find.byKey(const Key('object_bookmark_tab')), findsNothing);
      expect(find.byKey(const Key('object_bookmark_tab_hit')), findsNothing);
    });

    testWidgets('bookmarked card keeps full width with overlay tab', (
      tester,
    ) async {
      Future<void> pumpAt(Size size) async {
        tester.view.physicalSize = size;
        tester.view.devicePixelRatio = 1.0;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
      }

      await pumpAt(const Size(1280, 768));
      final colors = <String, String?>{'A': 'red', 'B': null};
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: StatefulBuilder(
              builder: (context, setState) {
                Widget sampleCard(String title) {
                  final color = colors[title];
                  return ObjectBookmarkRibbon(
                    color: color,
                    onSelect: (value) => setState(() => colors[title] = value),
                    onClear: () => setState(() => colors[title] = null),
                    child: Card(
                      key: Key('sample_card_$title'),
                      margin: EdgeInsets.zero,
                      child: Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 8,
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            ObjectCompactHeaderRow(
                              title: 'Card $title',
                              kind: 'email',
                              trailingText: '12:00',
                              trailingReserve: color != null
                                  ? kBookmarkRibbonReserve
                                  : 0,
                            ),
                            if (color == null)
                              ObjectBookmarkControl(
                                color: color,
                                onSelect: (value) =>
                                    setState(() => colors[title] = value),
                                onClear: () =>
                                    setState(() => colors[title] = null),
                              ),
                          ],
                        ),
                      ),
                    ),
                  );
                }

                return ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 640),
                  child: Column(
                    children: [
                      sampleCard('A'),
                      const SizedBox(height: 8),
                      sampleCard('B'),
                    ],
                  ),
                );
              },
            ),
          ),
        ),
      );

      final bookmarked = tester.getRect(find.byKey(const Key('sample_card_A')));
      final plain = tester.getRect(find.byKey(const Key('sample_card_B')));
      expect(bookmarked.width, closeTo(plain.width, 0.5));
      expect(bookmarked.left, closeTo(plain.left, 0.5));
      expect(bookmarked.right, closeTo(plain.right, 0.5));
      expect(find.byKey(const Key('object_bookmark_tab')), findsOneWidget);
      expect(
        find.descendant(
          of: find.byKey(const Key('sample_card_A')),
          matching: find.byKey(const Key('object_bookmark_tab')),
        ),
        findsNothing,
      );
      expect(
        find.descendant(
          of: find.byKey(const Key('sample_card_B')),
          matching: find.byKey(const Key('object_bookmark_tab')),
        ),
        findsNothing,
      );
      expect(find.byType(ObjectBookmarkGlyph), findsNWidgets(2));

      final tab = tester.getRect(find.byKey(const Key('object_bookmark_tab')));
      expect(tab.right, closeTo(bookmarked.right, 2));
      expect(tab.top, lessThan(bookmarked.top + 6));
      final stamp = tester.getRect(
        find.descendant(
          of: find.byKey(const Key('sample_card_A')),
          matching: find.byKey(const Key('object_compact_header_timestamp')),
        ),
      );
      expect(stamp.right, lessThanOrEqualTo(tab.left + 1));
      final hit = tester.getSize(
        find.byKey(const Key('object_bookmark_tab_hit')),
      );
      expect(hit.width, greaterThanOrEqualTo(36));
      expect(hit.height, greaterThanOrEqualTo(36));

      tester.view.physicalSize = const Size(360, 760);
      await tester.pump();
      expect(tester.takeException(), isNull);
      expect(
        tester.getRect(find.byKey(const Key('sample_card_A'))).right,
        closeTo(
          tester.getRect(find.byKey(const Key('sample_card_B'))).right,
          0.5,
        ),
      );
      expect(
        find.byKey(const Key('object_compact_header_timestamp')),
        findsNWidgets(2),
      );
      tester.view.physicalSize = const Size(1280, 768);
      await tester.pump();

      final hitRect = tester.getRect(
        find.byKey(const Key('object_bookmark_tab_hit')),
      );
      await tester.tapAt(Offset(hitRect.left + 4, hitRect.bottom - 4));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Синий'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('object_bookmark_tab')), findsOneWidget);
      expect(find.byKey(const Key('object_bookmark_control')), findsOneWidget);

      await tester.tap(find.byKey(const Key('object_bookmark_tab_hit')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Убрать закладку'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('object_bookmark_tab')), findsNothing);
      expect(
        find.byKey(const Key('object_bookmark_control')),
        findsNWidgets(2),
      );
      expect(find.byType(ObjectBookmarkGlyph), findsNWidgets(2));
      expect(
        tester.getRect(find.byKey(const Key('sample_card_A'))).right,
        closeTo(
          tester.getRect(find.byKey(const Key('sample_card_B'))).right,
          0.5,
        ),
      );

      tester.view.physicalSize = const Size(360, 760);
      await tester.pump();
      expect(tester.takeException(), isNull);
      expect(
        find.byKey(const Key('object_compact_header_timestamp')),
        findsNWidgets(2),
      );
      expect(
        find.byKey(const Key('object_bookmark_control')),
        findsNWidgets(2),
      );
    });
  });

  group('review marker presentation', () {
    testWidgets('placed marker keeps forgiving handle and thin line copy', (
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
          return jsonRes({}, 404);
        }),
      );
      apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
      await tester.pumpWidget(pumpInbox(apiClient));
      await tester.pumpAndSettle();
      expect(find.text('Просмотрено досюда'), findsOneWidget);
      final handle = tester.getSize(
        find.byKey(const Key('inbox_review_marker_handle')),
      );
      expect(handle.width, greaterThanOrEqualTo(28));
      expect(handle.height, greaterThanOrEqualTo(24));
      expect(
        tester
            .getSize(find.byKey(const Key('inbox_review_marker_gap_a')))
            .height,
        10,
      );
      debugDefaultTargetPlatformOverride = null;
    });
  });

  group('today and search', () {
    testWidgets('today keeps a shared left bookmark lane', (tester) async {
      tester.view.physicalSize = const Size(1280, 768);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final apiClient = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.url.path == '/today') {
            return jsonRes({
              'date': '2026-08-28',
              'timezone': 'Europe/Amsterdam',
              'day_start': '2026-08-28T00:00:00+02:00',
              'tasks': [
                {
                  'id': 'task-plain',
                  'kind': 'task',
                  'title': 'Task without labels',
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
              'calendar_events': [
                {
                  'id': 'google-plain',
                  'kind': 'event',
                  'title': 'Google event without labels',
                  'body': null,
                  'provider': 'google_calendar',
                  'external_id': null,
                  'canonical_uri': null,
                  'status': null,
                  'start_at': '2026-08-28T09:00:00+02:00',
                  'due_at': null,
                  'metadata': {},
                  'origin': 'source',
                  'state': 'observed',
                  'confidence': null,
                  'created_at': '2026-08-28T08:00:00Z',
                  'updated_at': '2026-08-28T08:00:00Z',
                },
                {
                  'id': 'yandex-labeled',
                  'kind': 'event',
                  'title': 'Yandex event with label',
                  'body': null,
                  'provider': 'yandex_calendar',
                  'external_id': null,
                  'canonical_uri': null,
                  'status': null,
                  'start_at': '2026-08-28T10:00:00+02:00',
                  'due_at': null,
                  'metadata': {},
                  'origin': 'source',
                  'state': 'observed',
                  'confidence': null,
                  'created_at': '2026-08-28T08:00:00Z',
                  'updated_at': '2026-08-28T08:00:00Z',
                },
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
            return jsonRes({'objects': {}});
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
      final taskX = tester
          .getTopLeft(find.byKey(const Key('object_bookmark_control')).at(0))
          .dx;
      final controls = find.byKey(const Key('object_bookmark_control'));
      expect(controls, findsNWidgets(3));
      expect(
        (tester.getTopLeft(controls.at(1)).dx - taskX).abs(),
        lessThanOrEqualTo(1),
      );
      expect(
        (tester.getTopLeft(controls.at(2)).dx - taskX).abs(),
        lessThanOrEqualTo(1),
      );
      expect(find.text('Work'), findsOneWidget);
    });

    testWidgets('calendar events keep compact separators', (tester) async {
      final now = DateTime.parse('2026-09-08T12:00:00+03:00');
      Map<String, dynamic> eventJson({
        required String id,
        required String title,
        required String start,
        String? due,
      }) {
        return {
          'id': id,
          'kind': 'event',
          'title': title,
          'body': null,
          'provider': 'google_calendar',
          'external_id': null,
          'canonical_uri': null,
          'status': null,
          'start_at': start,
          'due_at': due,
          'metadata': {},
          'origin': 'source',
          'state': 'observed',
          'confidence': null,
          'created_at': '2026-09-08T08:00:00Z',
          'updated_at': '2026-09-08T08:00:00Z',
        };
      }

      final events = [
        eventJson(
          id: 'current',
          title: 'Current meeting',
          start: '2026-09-08T11:30:00+03:00',
          due: '2026-09-08T12:30:00+03:00',
        ),
        eventJson(
          id: 'soon',
          title: 'Soon standup',
          start: '2026-09-08T12:40:00+03:00',
        ),
        eventJson(
          id: 'later',
          title: 'Later review',
          start: '2026-09-08T15:00:00+03:00',
        ),
      ];

      Finder separators() {
        return find.byWidgetPredicate(
          (widget) =>
              widget.key is ValueKey<String> &&
              (widget.key as ValueKey<String>).value.startsWith(
                'today_event_separator_',
              ),
        );
      }

      Future<void> pumpAt(Size size) async {
        tester.view.physicalSize = size;
        tester.view.devicePixelRatio = 1.0;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final apiClient = SecretaryApiClient(
          httpClient: MockClient((request) async {
            if (request.url.path == '/today') {
              return jsonRes({
                'date': '2026-09-08',
                'timezone': 'Europe/Amsterdam',
                'day_start': '2026-09-08T00:00:00+03:00',
                'tasks': [],
                'calendar_events': events,
                'notifications': [],
              });
            }
            if (request.url.path == '/labels/by-objects') {
              return jsonRes({
                'objects': {
                  'soon': [
                    {'id': 'lab-1', 'title': 'Work'},
                  ],
                },
              });
            }
            if (request.url.path == '/object-bookmarks/by-objects') {
              return jsonRes({
                'objects': {
                  'current': {'color': 'red'},
                },
              });
            }
            final objectMatch = RegExp(
              r'^/objects/([^/]+)$',
            ).firstMatch(request.url.path);
            if (objectMatch != null) {
              final id = objectMatch.group(1)!;
              final row = events.firstWhere((item) => item['id'] == id);
              return jsonRes(row);
            }
            if (request.url.path.endsWith('/neighbors')) {
              final id = request.url.path.split('/')[2];
              return jsonRes({'object_id': id, 'neighbors': []});
            }
            if (request.url.path.endsWith('/context')) {
              final id = request.url.path.split('/')[2];
              final row = events.firstWhere((item) => item['id'] == id);
              return jsonRes({'object': row, 'edges': [], 'neighbors': []});
            }
            if (request.url.path.endsWith('/labels')) {
              return jsonRes({'labels': []});
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
                now: () => now,
                clockTick: const Duration(days: 1),
                passiveRefreshInterval: const Duration(days: 1),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
      }

      await pumpAt(const Size(1280, 900));
      expect(tester.takeException(), isNull);
      expect(find.text('Current meeting'), findsOneWidget);
      expect(find.text('Soon standup'), findsOneWidget);
      expect(find.text('Later review'), findsOneWidget);
      expect(separators(), findsNWidgets(2));
      expect(
        tester.getTopLeft(find.text('Current meeting')).dy,
        lessThan(tester.getTopLeft(find.text('Soon standup')).dy),
      );
      expect(
        tester.getTopLeft(find.text('Soon standup')).dy,
        lessThan(tester.getTopLeft(find.text('Later review')).dy),
      );
      expect(
        find.byKey(const Key('today_event_current_current')),
        findsOneWidget,
      );
      expect(find.byKey(const Key('today_event_soon_soon')), findsOneWidget);
      expect(find.byKey(const Key('today_event_none_later')), findsOneWidget);
      final currentDeco =
          tester
                  .widget<DecoratedBox>(
                    find.byKey(const Key('today_event_current_current')),
                  )
                  .decoration
              as BoxDecoration;
      final soonDeco =
          tester
                  .widget<DecoratedBox>(
                    find.byKey(const Key('today_event_soon_soon')),
                  )
                  .decoration
              as BoxDecoration;
      final laterDeco =
          tester
                  .widget<DecoratedBox>(
                    find.byKey(const Key('today_event_none_later')),
                  )
                  .decoration
              as BoxDecoration;
      expect(currentDeco.color, isNotNull);
      expect(currentDeco.border, isNotNull);
      expect(soonDeco.color, isNotNull);
      expect(soonDeco.border, isNotNull);
      expect(laterDeco.color, isNull);
      expect(find.byKey(const Key('object_bookmark_tab')), findsOneWidget);
      expect(find.text('Work'), findsOneWidget);

      await tester.tap(find.text('Current meeting'));
      await tester.pumpAndSettle();
      expect(find.byType(ObjectDetailScreen), findsOneWidget);
      await tester.pageBack();
      await tester.pumpAndSettle();
      await tester.tap(find.text('Soon standup'));
      await tester.pumpAndSettle();
      expect(find.byType(ObjectDetailScreen), findsOneWidget);
      await tester.pageBack();
      await tester.pumpAndSettle();
      await tester.tap(find.text('Later review'));
      await tester.pumpAndSettle();
      expect(find.byType(ObjectDetailScreen), findsOneWidget);
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(separators(), findsNWidgets(2));

      await pumpAt(const Size(360, 800));
      expect(tester.takeException(), isNull);
      expect(separators(), findsNWidgets(2));
      expect(find.text('Current meeting'), findsOneWidget);
      expect(
        find.byKey(const Key('today_event_current_current')),
        findsOneWidget,
      );
      expect(find.byKey(const Key('today_event_soon_soon')), findsOneWidget);
    });

    testWidgets('search task result is bookmarkable', (tester) async {
      tester.view.physicalSize = const Size(1280, 768);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      String? stored;
      final apiClient = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.url.path == '/search/facets') {
            return jsonRes({'kinds': [], 'providers': []});
          }
          if (request.url.path == '/labels') {
            return jsonRes({'labels': []});
          }
          if (request.url.path == '/search') {
            return jsonRes([
              {
                'id': 'task-1',
                'kind': 'task',
                'title': 'Найденная задача',
                'body': 'body',
                'provider': null,
                'external_id': null,
                'canonical_uri': null,
                'status': 'open',
                'start_at': null,
                'due_at': null,
                'metadata': {},
                'origin': 'user',
                'state': 'confirmed',
                'confidence': null,
                'created_at': '2026-08-30T08:00:00Z',
                'updated_at': '2026-08-30T08:00:00Z',
              },
            ]);
          }
          if (request.url.path == '/labels/by-objects') {
            return jsonRes({'objects': {}});
          }
          if (request.url.path == '/object-bookmarks/by-objects') {
            return jsonRes({
              'objects': {
                if (stored != null) 'task-1': {'color': stored},
              },
            });
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
            body: SearchScreen(
              apiClient: apiClient,
              authController: auth,
              captureController: CaptureController(
                apiClient: apiClient,
                authController: auth,
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField).first, 'задача');
      await tester.tap(find.widgetWithText(FilledButton, 'Поиск'));
      await tester.pumpAndSettle();
      expect(find.text('Найденная задача'), findsOneWidget);
      expect(find.byKey(const Key('object_bookmark_control')), findsOneWidget);
      await tester.tap(find.byKey(const Key('object_bookmark_control')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Зелёный'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('object_bookmark_tab')), findsOneWidget);
      expect(find.byKey(const Key('object_bookmark_control')), findsNothing);
    });
  });

  group('graph bookmarks', () {
    Finder nodeTab(String id) {
      return find.descendant(
        of: find.byKey(Key('graph_node_$id')),
        matching: find.byKey(const Key('object_bookmark_tab')),
      );
    }

    Finder nodeControl(String id) {
      return find.descendant(
        of: find.byKey(Key('graph_node_$id')),
        matching: find.byKey(const Key('object_bookmark_control')),
      );
    }

    testWidgets('visible nodes reconcile and mutate without reload', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(1280, 768);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      var workspaceCalls = 0;
      var batchCalls = 0;
      final stored = <String, String>{};
      final mock = MockClient((request) async {
        if (request.url.path == '/notifications') {
          return jsonUtf8Response({'notifications': []});
        }
        if (request.url.path == '/today') {
          return jsonUtf8Response({
            'date': '2026-08-28',
            'timezone': 'Europe/Amsterdam',
            'day_start': '2026-08-28T00:00:00+02:00',
            'tasks': [],
            'calendar_events': [],
            'notifications': [],
          });
        }
        if (request.url.path == '/search/facets') {
          return jsonUtf8Response({'kinds': [], 'providers': []});
        }
        if (request.url.path == '/graph/workspace') {
          workspaceCalls++;
          return jsonUtf8Response(
            graphWorkspaceJson(
              nodes: [
                graphObjectJson(id: 'task-1', title: 'Graph task'),
                graphObjectJson(id: 'task-2', title: 'Other task'),
              ],
            ),
          );
        }
        if (request.url.path == '/object-bookmarks/by-objects') {
          batchCalls++;
          final ids =
              (jsonDecode(request.body) as Map)['object_ids'] as List<dynamic>;
          expect(ids.length, lessThanOrEqualTo(100));
          final objects = <String, Map<String, String>>{};
          for (final rawId in ids) {
            final id = rawId as String;
            final color = stored[id];
            if (color != null) {
              objects[id] = {'color': color};
            }
          }
          return jsonUtf8Response({'objects': objects});
        }
        if (request.method == 'PUT' &&
            request.url.path.startsWith('/object-bookmarks/')) {
          final id = request.url.path.split('/').last;
          stored[id] = (jsonDecode(request.body) as Map)['color'] as String;
          return jsonUtf8Response({
            'object_id': id,
            'color': stored[id],
            'updated_at': '2026-09-09T13:00:00Z',
          });
        }
        if (request.method == 'DELETE' &&
            request.url.path.startsWith('/object-bookmarks/')) {
          stored.remove(request.url.path.split('/').last);
          return jsonUtf8Response({});
        }
        return jsonUtf8Response({}, statusCode: 404);
      });
      final harness = GraphTestHarness(mock);
      harness.configure();
      final bookmarks = ObjectBookmarkController(
        apiClient: harness.auth.apiClient,
        authController: harness.auth,
      );
      stored['task-1'] = 'red';

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: GraphWorkspaceScreen(
              controller: harness.graph,
              apiClient: harness.auth.apiClient,
              authController: harness.auth,
              captureController: harness.capture,
              assistantController: harness.assistant,
              onAskSecretary: (_) {},
              bookmarkController: bookmarks,
            ),
          ),
        ),
      );
      await harness.graph.loadOverview();
      await tester.pumpAndSettle();

      expect(workspaceCalls, 1);
      expect(batchCalls, 1);
      expect(nodeTab('task-1'), findsOneWidget);
      expect(nodeTab('task-2'), findsNothing);
      expect(nodeControl('task-1'), findsNothing);
      expect(nodeControl('task-2'), findsNothing);
      expect(
        find.descendant(
          of: find.byKey(const Key('graph_node_task-1')),
          matching: find.byKey(const Key('object_bookmark_tab_hit')),
        ),
        findsNothing,
      );

      harness.graph.selectObject('task-2');
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('object_bookmark_control')), findsOneWidget);
      expect(find.text('Graph task'), findsWidgets);

      await tester.tap(find.byKey(const Key('object_bookmark_control')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Синий'));
      await tester.pumpAndSettle();
      expect(nodeTab('task-2'), findsOneWidget);
      expect(workspaceCalls, 1);

      await tester.tap(
        find.descendant(
          of: find.byType(ListView),
          matching: find.byKey(const Key('object_bookmark_tab')),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Зелёный'));
      await tester.pumpAndSettle();
      expect(nodeTab('task-2'), findsOneWidget);
      expect(bookmarks.colorFor('task-2'), 'green');
      expect(workspaceCalls, 1);

      await tester.tap(
        find.descendant(
          of: find.byType(ListView),
          matching: find.byKey(const Key('object_bookmark_tab')),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Убрать закладку'));
      await tester.pumpAndSettle();
      expect(nodeTab('task-2'), findsNothing);
      expect(find.byKey(const Key('object_bookmark_control')), findsOneWidget);
      expect(workspaceCalls, 1);

      await bookmarks.setColor('task-2', 'violet');
      await tester.pumpAndSettle();
      expect(nodeTab('task-2'), findsOneWidget);
      expect(workspaceCalls, 1);

      final batchesAfterLoad = batchCalls;
      await tester.pump();
      await tester.pump();
      harness.graph.selectObject('task-1');
      await tester.pumpAndSettle();
      expect(batchCalls, batchesAfterLoad);
      expect(workspaceCalls, 1);
    });

    testWidgets('failed bookmark batch can retry the same visible ids', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(1280, 768);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      var workspaceCalls = 0;
      var batchCalls = 0;
      final stored = <String, String>{};
      final mock = MockClient((request) async {
        if (request.url.path == '/notifications') {
          return jsonUtf8Response({'notifications': []});
        }
        if (request.url.path == '/today') {
          return jsonUtf8Response({
            'date': '2026-08-28',
            'timezone': 'Europe/Amsterdam',
            'day_start': '2026-08-28T00:00:00+02:00',
            'tasks': [],
            'calendar_events': [],
            'notifications': [],
          });
        }
        if (request.url.path == '/search/facets') {
          return jsonUtf8Response({'kinds': [], 'providers': []});
        }
        if (request.url.path == '/graph/workspace') {
          workspaceCalls++;
          return jsonUtf8Response(
            graphWorkspaceJson(
              nodes: [
                graphObjectJson(id: 'task-1', title: 'Graph task'),
                graphObjectJson(id: 'task-2', title: 'Other task'),
              ],
            ),
          );
        }
        if (request.url.path == '/object-bookmarks/by-objects') {
          batchCalls++;
          if (batchCalls == 1) {
            return jsonUtf8Response({'detail': 'unavailable'}, statusCode: 500);
          }
          final ids =
              (jsonDecode(request.body) as Map)['object_ids'] as List<dynamic>;
          expect(ids.length, lessThanOrEqualTo(100));
          final objects = <String, Map<String, String>>{};
          for (final rawId in ids) {
            final id = rawId as String;
            final color = stored[id];
            if (color != null) {
              objects[id] = {'color': color};
            }
          }
          return jsonUtf8Response({'objects': objects});
        }
        if (request.method == 'PUT' &&
            request.url.path.startsWith('/object-bookmarks/')) {
          final id = request.url.path.split('/').last;
          stored[id] = (jsonDecode(request.body) as Map)['color'] as String;
          return jsonUtf8Response({
            'object_id': id,
            'color': stored[id],
            'updated_at': '2026-09-09T13:00:00Z',
          });
        }
        return jsonUtf8Response({}, statusCode: 404);
      });
      final harness = GraphTestHarness(mock);
      harness.configure();
      final bookmarks = ObjectBookmarkController(
        apiClient: harness.auth.apiClient,
        authController: harness.auth,
      );
      await bookmarks.setColor('task-1', 'orange');
      stored['task-1'] = 'red';

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: GraphWorkspaceScreen(
              controller: harness.graph,
              apiClient: harness.auth.apiClient,
              authController: harness.auth,
              captureController: harness.capture,
              assistantController: harness.assistant,
              onAskSecretary: (_) {},
              bookmarkController: bookmarks,
            ),
          ),
        ),
      );
      await harness.graph.loadOverview();
      await tester.pumpAndSettle();

      expect(workspaceCalls, 1);
      expect(batchCalls, 1);
      expect(tester.takeException(), isNull);
      expect(bookmarks.colorFor('task-1'), 'orange');
      expect(nodeTab('task-1'), findsOneWidget);
      expect(nodeTab('task-2'), findsNothing);
      expect(nodeControl('task-1'), findsNothing);
      expect(nodeControl('task-2'), findsNothing);

      harness.graph.selectObject('task-2');
      await tester.pumpAndSettle();
      expect(batchCalls, 2);
      expect(bookmarks.colorFor('task-1'), 'red');
      expect(nodeTab('task-1'), findsOneWidget);
      expect(nodeTab('task-2'), findsNothing);
      expect(nodeControl('task-2'), findsNothing);
      expect(find.byKey(const Key('object_bookmark_control')), findsOneWidget);

      final batchesAfterSuccess = batchCalls;
      harness.graph.selectObject('task-1');
      await tester.pumpAndSettle();
      harness.graph.selectObject('task-2');
      await tester.pumpAndSettle();
      expect(batchCalls, batchesAfterSuccess);
      expect(workspaceCalls, 1);

      await bookmarks.setColor('task-2', 'violet');
      await tester.pumpAndSettle();
      expect(nodeTab('task-2'), findsOneWidget);
      expect(nodeControl('task-2'), findsNothing);
      expect(workspaceCalls, 1);
    });
  });
}
