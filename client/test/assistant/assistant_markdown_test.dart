import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/assistant/assistant_message_body.dart';

void main() {
  const exactId = '11111111-1111-4111-8111-111111111111';
  const foreignId = '22222222-2222-4222-8222-222222222222';

  test('validated secretary citation opens the exact object', () {
    final target = classifyAssistantLink('secretary://object/$exactId', {
      exactId,
    });
    expect(target.kind, AssistantLinkKind.objectDetail);
    expect(target.objectId, exactId);
  });

  test('http links stay external and unproven schemes do not launch', () {
    expect(
      classifyAssistantLink('https://example.com/mail', {exactId}).kind,
      AssistantLinkKind.external,
    );
    expect(
      classifyAssistantLink('http://example.com/mail', {exactId}).kind,
      AssistantLinkKind.external,
    );
    expect(
      classifyAssistantLink('secretary://object/$foreignId', {exactId}).kind,
      AssistantLinkKind.ignore,
    );
    expect(
      classifyAssistantLink('secretary://object/not-a-uuid', {exactId}).kind,
      AssistantLinkKind.ignore,
    );
    expect(
      classifyAssistantLink('javascript:alert(1)', {exactId}).kind,
      AssistantLinkKind.ignore,
    );
    expect(
      classifyAssistantLink(null, {exactId}).kind,
      AssistantLinkKind.ignore,
    );
  });

  testWidgets('assistant markdown renders bold and list', (tester) async {
    const markdown = '**Горит одна задача:**\n\n- пункт один\n- пункт два';
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: AssistantMessageBody(content: markdown)),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Горит одна задача:'), findsOneWidget);
    expect(find.text('пункт один'), findsOneWidget);
    expect(find.text('пункт два'), findsOneWidget);
    expect(find.textContaining('**'), findsNothing);
  });

  testWidgets('assistant markdown uses MarkdownBody with selectable flag', (
    tester,
  ) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: AssistantMessageBody(content: 'Selectable assistant text'),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Selectable assistant text'), findsOneWidget);
    final markdown = tester.widget<MarkdownBody>(find.byType(MarkdownBody));
    expect(markdown.selectable, isTrue);
  });
}
