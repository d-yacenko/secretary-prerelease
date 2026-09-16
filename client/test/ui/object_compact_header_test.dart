import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/ui/object_presentation.dart';

void main() {
  Widget wrap(Widget child, {double width = 320}) {
    return MaterialApp(
      home: Scaffold(
        body: MediaQuery(
          data: MediaQueryData(size: Size(width, 800)),
          child: SizedBox(width: width, child: child),
        ),
      ),
    );
  }

  testWidgets('compact header places kind and provider before title', (
    tester,
  ) async {
    await tester.pumpWidget(
      wrap(
        ObjectCompactHeaderRow(
          title: 'Тема письма',
          kind: 'email',
          provider: 'gmail',
          trailingText: '09:42',
        ),
      ),
    );

    final iconBox = tester.getRect(find.byIcon(Icons.email_outlined));
    final providerBox = tester.getRect(
      find.byKey(const Key('source_mark_google')),
    );
    final titleBox = tester.getRect(find.text('Тема письма'));
    final timeBox = tester.getRect(find.text('09:42'));

    expect(iconBox.left, lessThan(titleBox.left));
    expect(providerBox.left, lessThan(titleBox.left));
    expect(iconBox.left, lessThan(providerBox.left));
    expect(timeBox.left, greaterThan(titleBox.right));
  });

  testWidgets('compact header supports calendar event and missing provider', (
    tester,
  ) async {
    await tester.pumpWidget(
      wrap(
        Column(
          children: [
            ObjectCompactHeaderRow(
              title: 'Weekly sync',
              kind: 'event',
              provider: 'google_calendar',
              trailingText: '10:00',
            ),
            ObjectCompactHeaderRow(
              title: 'Локальная задача без провайдера',
              kind: 'task',
              provider: null,
              trailingText: 'сегодня',
            ),
          ],
        ),
      ),
    );

    expect(find.byIcon(Icons.event_outlined), findsOneWidget);
    expect(find.byKey(const Key('source_mark_google')), findsOneWidget);
    expect(find.byIcon(Icons.calendar_month), findsNothing);
    expect(find.text('Weekly sync'), findsOneWidget);
    expect(find.text('Локальная задача без провайдера'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'compact header long russian title does not overflow on narrow width',
    (tester) async {
      await tester.pumpWidget(
        wrap(
          ObjectCompactHeaderRow(
            title:
                'Очень длинное русское название письма которое должно сокращаться',
            kind: 'email',
            provider: 'yandex_mail',
            trailingText: 'вчера 18:30',
          ),
        ),
      );

      expect(tester.takeException(), isNull);
      expect(find.byKey(const Key('source_mark_yandex')), findsOneWidget);
      expect(find.textContaining('вчера'), findsOneWidget);
    },
  );

  testWidgets(
    'compact header allows two title lines and keeps full date accessible',
    (tester) async {
      const title =
          'test-user: Это синтетический длинный заголовок сообщения для проверки переноса текста на две строки';
      await tester.pumpWidget(
        wrap(
          ObjectCompactHeaderRow(
            title: title,
            kind: 'chat_message',
            provider: 'telegram',
            trailingText: '09:42',
            trailingTooltip: '16.09.2026, 09:42',
            titleMaxLines: 2,
          ),
        ),
      );

      final titleFinder = find.text(title);
      expect(tester.widget<Text>(titleFinder).maxLines, 2);
      expect(tester.getRect(titleFinder).height, greaterThan(30));
      expect(find.text('09:42'), findsOneWidget);
      expect(find.byTooltip('16.09.2026, 09:42'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'wide header pins timestamp to the right for short and long titles',
    (tester) async {
      Future<void> pumpHeader({
        required String title,
        required double width,
        double trailingReserve = 0,
      }) async {
        await tester.pumpWidget(
          wrap(
            ObjectCompactHeaderRow(
              title: title,
              kind: 'email',
              provider: 'gmail',
              trailingText: '09:42',
              trailingReserve: trailingReserve,
            ),
            width: width,
          ),
        );
      }

      await pumpHeader(title: 'Тема', width: 800);
      var header = tester.getRect(find.byType(ObjectCompactHeaderRow));
      var stamp = tester.getRect(
        find.byKey(const Key('object_compact_header_timestamp')),
      );
      var titleBox = tester.getRect(find.text('Тема'));
      expect(stamp.right, closeTo(header.right, 1.5));
      expect(stamp.left, greaterThan(titleBox.right));
      expect(header.right - stamp.right, lessThan(8));
      expect(tester.widget<Text>(find.text('Тема')).maxLines, 1);
      expect(titleBox.width, greaterThan(600));

      await pumpHeader(
        title:
            'Очень длинное русское название письма которое должно сокращаться на широкой карточке',
        width: 800,
      );
      header = tester.getRect(find.byType(ObjectCompactHeaderRow));
      stamp = tester.getRect(
        find.byKey(const Key('object_compact_header_timestamp')),
      );
      titleBox = tester.getRect(find.textContaining('Очень длинное'));
      expect(stamp.right, closeTo(header.right, 1.5));
      expect(stamp.left, greaterThan(titleBox.left));
      expect(titleBox.right, lessThanOrEqualTo(stamp.left + 0.5));

      await pumpHeader(title: 'Тема', width: 800, trailingReserve: 18);
      header = tester.getRect(find.byType(ObjectCompactHeaderRow));
      stamp = tester.getRect(
        find.byKey(const Key('object_compact_header_timestamp')),
      );
      expect(stamp.right, closeTo(header.right - 18, 1.5));

      await pumpHeader(title: 'Тема', width: 360);
      header = tester.getRect(find.byType(ObjectCompactHeaderRow));
      stamp = tester.getRect(
        find.byKey(const Key('object_compact_header_timestamp')),
      );
      titleBox = tester.getRect(find.text('Тема'));
      expect(stamp.left, greaterThan(titleBox.right));
      expect(stamp.right, closeTo(header.right, 1.5));
      expect(tester.widget<Text>(find.text('Тема')).maxLines, 2);
    },
  );
}
