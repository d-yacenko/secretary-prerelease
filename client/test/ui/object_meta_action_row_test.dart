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
              actions: [
                AskSecretaryAction(onPressed: () {}),
              ],
              labels: [
                LabelItem(id: 'label-1', title: 'Метка'),
              ],
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      final action = tester.getCenter(find.text('Спросить секретаря'));
      final label = tester.getCenter(find.text('Метка'));
      expect(label.dx, greaterThan(action.dx));
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
  });
}
