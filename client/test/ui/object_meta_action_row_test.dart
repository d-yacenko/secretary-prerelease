import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/ui/object_actions.dart';
import 'package:personal_secretary/ui/object_label_strip.dart';

void main() {
  testWidgets(
    'shared wide row keeps labels on the right for Search and Today',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(900, 700));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: ObjectMetaActionRow(
              actions: [AskSecretaryAction(onPressed: () {})],
              labels: [LabelItem(id: 'label-1', title: 'Метка')],
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      final action = tester.getCenter(find.text('Секретарь'));
      final label = tester.getCenter(find.text('Метка'));
      final row = tester.getRect(find.byType(ObjectMetaActionRow));
      final strip = tester.getRect(find.byType(ObjectLabelStrip));
      expect(label.dx, greaterThan(action.dx));
      expect(strip.right, closeTo(row.right, 1));
    },
  );

  testWidgets('Inbox wrap option keeps a later action inside the row', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(900, 700));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 280,
            child: ObjectMetaActionRow(
              wrapActions: true,
              actions: [
                AskSecretaryAction(onPressed: () {}),
                OpenInGraphAction(onPressed: () {}),
                DeleteObjectAction(
                  key: const Key('wrapped_delete'),
                  onPressed: () {},
                ),
              ],
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.byKey(const Key('wrapped_delete')), findsOneWidget);
    expect(find.text('Секретарь'), findsOneWidget);
    expect(find.text('Граф'), findsOneWidget);
    expect(find.text('Удалить'), findsOneWidget);
    expect(find.byTooltip('Спросить секретаря'), findsOneWidget);
    expect(find.byTooltip('Открыть в графе'), findsOneWidget);
  });

  testWidgets('Inbox wrap keeps labels pinned to the right of actions', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(900, 700));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 720,
            child: ObjectMetaActionRow(
              wrapActions: true,
              actions: [
                AskSecretaryAction(onPressed: () {}),
                OpenInGraphAction(onPressed: () {}),
                DeleteObjectAction(onPressed: () {}),
              ],
              labels: [
                LabelItem(id: 'l1', title: 'Личное'),
                LabelItem(id: 'l2', title: 'Проект'),
                LabelItem(id: 'l3', title: 'Архив'),
              ],
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    final row = tester.getRect(find.byType(ObjectMetaActionRow));
    final personal = tester.getRect(find.text('Личное'));
    final project = tester.getRect(find.text('Проект'));
    final ask = tester.getRect(find.text('Секретарь'));
    expect(find.text('Архив'), findsNothing);
    expect(find.text('+1'), findsOneWidget);
    expect(personal.right, lessThanOrEqualTo(row.right + 1));
    expect(project.right, lessThanOrEqualTo(row.right + 1));
    expect(ask.left, greaterThanOrEqualTo(row.left - 1));
    expect(personal.left, greaterThan(ask.right));
    expect(project.right, greaterThan(personal.right));
    final overflow = tester.getRect(
      find.byKey(const Key('object_label_overflow')),
    );
    expect(overflow.right, closeTo(row.right, 1));
  });
}
