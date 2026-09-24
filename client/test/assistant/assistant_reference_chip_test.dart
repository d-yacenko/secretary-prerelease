import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/assistant/assistant_reference_chip.dart';
import 'package:personal_secretary/ui/object_presentation.dart';

void main() {
  AssistantReference reference({
    String? provider,
    String? primaryAt,
    String kind = 'email',
    String title = 'Письмо от коллеги',
  }) {
    return AssistantReference(
      objectId: 'obj-1',
      title: title,
      kind: kind,
      provider: provider,
      primaryAt: primaryAt,
    );
  }

  Future<void> pumpChip(WidgetTester tester, AssistantReference ref) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: AssistantReferenceChip(reference: ref, onPressed: () {}),
        ),
      ),
    );
  }

  test('fromJson keeps provider and primary_at optional', () {
    final dated = AssistantReference.fromJson({
      'object_id': 'a',
      'title': 'Hello',
      'kind': 'email',
      'provider': 'google',
      'primary_at': '2026-03-04T15:00:00Z',
    });
    expect(dated.provider, 'google');
    expect(dated.primaryAt, '2026-03-04T15:00:00Z');

    final plain = AssistantReference.fromJson({
      'object_id': 'b',
      'title': 'Note',
      'kind': 'note',
    });
    expect(plain.provider, isNull);
    expect(plain.primaryAt, isNull);
  });

  testWidgets('google email chip shows kind icon, provider, title, and date', (
    tester,
  ) async {
    await pumpChip(
      tester,
      reference(provider: 'google', primaryAt: '2026-03-04T15:00:00Z'),
    );
    expect(find.byIcon(iconForObjectKind('email')), findsOneWidget);
    expect(find.byKey(const Key('provider_icon_google')), findsOneWidget);
    expect(find.text('Письмо от коллеги'), findsOneWidget);
    expect(find.textContaining(RegExp(r'^\d{2}\.\d{2}\.\d{2}$')), findsOneWidget);
    expect(find.textContaining('Письмо:'), findsNothing);
    expect(
      find.byTooltip('Письмо · google · Письмо от коллеги · 04.03.26'),
      findsWidgets,
    );
  });

  testWidgets('yandex chip shows the yandex provider icon', (tester) async {
    await pumpChip(
      tester,
      reference(provider: 'yandex', primaryAt: '2026-01-02T00:00:00Z'),
    );
    expect(find.byKey(const Key('provider_icon_yandex')), findsOneWidget);
  });

  testWidgets('long title at phone width keeps icons and date without overflow', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(320, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await pumpChip(
      tester,
      reference(
        provider: 'google',
        primaryAt: '2026-03-04T15:00:00Z',
        title:
            'Очень длинный заголовок письма которое не должно вызвать переполнение строки чипа',
      ),
    );
    expect(tester.takeException(), isNull);
    expect(find.byIcon(iconForObjectKind('email')), findsOneWidget);
    expect(find.byKey(const Key('provider_icon_google')), findsOneWidget);
    expect(find.textContaining(RegExp(r'^\d{2}\.\d{2}\.\d{2}$')), findsOneWidget);
    expect(
      find.byWidgetPredicate(
        (widget) =>
            widget is Text &&
            widget.overflow == TextOverflow.ellipsis &&
            widget.data!.startsWith('Очень длинный'),
      ),
      findsOneWidget,
    );
  });

  testWidgets('providerless undated chip keeps the kind icon and title only', (
    tester,
  ) async {
    await pumpChip(tester, reference(kind: 'note', title: 'Заметка'));
    expect(find.byIcon(iconForObjectKind('note')), findsOneWidget);
    expect(find.byKey(const Key('provider_icon_google')), findsNothing);
    expect(find.text('Заметка'), findsOneWidget);
    expect(find.textContaining(RegExp(r'^\d{2}\.\d{2}\.\d{2}$')), findsNothing);
  });
}
