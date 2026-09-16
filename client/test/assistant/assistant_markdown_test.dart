import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/assistant/assistant_message_body.dart';

void main() {
  testWidgets('assistant markdown renders bold and list', (tester) async {
    const markdown = '**Горит одна задача:**\n\n- пункт один\n- пункт два';
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: AssistantMessageBody(content: markdown),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Горит одна задача:'), findsOneWidget);
    expect(find.text('пункт один'), findsOneWidget);
    expect(find.text('пункт два'), findsOneWidget);
    expect(find.textContaining('**'), findsNothing);
  });

  testWidgets('assistant markdown uses MarkdownBody with selectable flag', (tester) async {
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
