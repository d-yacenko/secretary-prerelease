import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/ui/object_label_strip.dart';

LabelItem item(String id, String title, {String? description}) {
  return LabelItem(id: id, title: title, description: description);
}

void main() {
  Widget wrap(Widget child) {
    return MaterialApp(home: Scaffold(body: child));
  }

  testWidgets('zero labels render nothing', (tester) async {
    await tester.pumpWidget(wrap(const ObjectLabelStrip(labels: [])));
    expect(find.byType(ObjectLabelStrip), findsOneWidget);
    expect(find.text('Work'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('one and two labels render titles', (tester) async {
    await tester.pumpWidget(
      wrap(
        ObjectLabelStrip(
          labels: [item('1', 'Work'), item('2', 'Home')],
        ),
      ),
    );
    expect(find.text('Work'), findsOneWidget);
    expect(find.text('Home'), findsOneWidget);
    expect(find.byKey(const Key('object_label_overflow')), findsNothing);
  });

  testWidgets('more than two shows plus N', (tester) async {
    await tester.pumpWidget(
      wrap(
        ObjectLabelStrip(
          labels: [
            item('1', 'Alpha'),
            item('2', 'Beta'),
            item('3', 'Gamma'),
            item('4', 'Delta'),
          ],
        ),
      ),
    );
    expect(find.text('Alpha'), findsOneWidget);
    expect(find.text('Beta'), findsOneWidget);
    expect(find.text('Gamma'), findsNothing);
    expect(find.text('+2'), findsOneWidget);
  });

  testWidgets('long titles do not overflow', (tester) async {
    await tester.pumpWidget(
      wrap(
        SizedBox(
          width: 220,
          child: ObjectLabelStrip(
            labels: [
              item('1', 'Очень длинное название пользовательской метки'),
            ],
          ),
        ),
      ),
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('description is exposed in tooltip', (tester) async {
    await tester.pumpWidget(
      wrap(
        ObjectLabelStrip(
          labels: [item('1', 'Work', description: 'офис и встречи')],
        ),
      ),
    );
    expect(find.byTooltip('Work\nофис и встречи'), findsOneWidget);
  });

  testWidgets('unicode prefixed titles render as opaque text', (tester) async {
    await tester.pumpWidget(
      wrap(
        ObjectLabelStrip(
          labels: [
            item('1', '⚙ Personal Secretary'),
            item('2', '◎ Личное'),
          ],
        ),
      ),
    );
    expect(find.text('⚙ Personal Secretary'), findsOneWidget);
    expect(find.text('◎ Личное'), findsOneWidget);
    expect(find.textContaining('Проект'), findsNothing);
  });

  testWidgets('hidden overflow titles stay in +N tooltip', (tester) async {
    await tester.pumpWidget(
      wrap(
        ObjectLabelStrip(
          labels: [
            item('1', 'Alpha'),
            item('2', 'Beta'),
            item('3', '🎭 Gamma'),
            item('4', '🏭 Delta'),
          ],
        ),
      ),
    );
    expect(find.byTooltip('🎭 Gamma, 🏭 Delta'), findsOneWidget);
  });
}
