import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets('rooted Person detail can bind an exact email', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var bound = false;
    final harness = GraphTestHarness(_client(bound: () => bound, onBind: () => bound = true));
    harness.configure();
    await openGraph(tester, harness);
    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Ada').first);
    await tester.pumpAndSettle();
    expect(find.text('Добавить email'), findsNothing);

    await tester.tap(find.text('В центр'));
    await tester.pumpAndSettle();
    expect(find.text('Добавить email'), findsOneWidget);
    expect(find.text('Отклонить'), findsNothing);

    await tester.tap(find.text('Добавить email'));
    await tester.pumpAndSettle();
    expect(
      find.text(
        'Добавляется только точный адрес, который вы подтверждаете как принадлежащий этому человеку.',
      ),
      findsOneWidget,
    );
    await tester.enterText(
      find.descendant(of: find.byType(AlertDialog), matching: find.byType(TextField)),
      'ada@example.com',
    );
    await tester.pump();
    await tester.tap(find.widgetWithText(FilledButton, 'Добавить'));
    await tester.pumpAndSettle();

    expect(find.text('Добавить email'), findsOneWidget);
    expect(find.text('ada@example.com'), findsWidgets);
    expect(find.text('Письмо Ada'), findsOneWidget);
    expect(find.text('Отклонить'), findsOneWidget);
  });

  testWidgets('malformed email stays in the dialog', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = GraphTestHarness(_client(malformed: true));
    harness.configure();
    await openGraph(tester, harness);
    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Ada').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('В центр'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Добавить email'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.descendant(of: find.byType(AlertDialog), matching: find.byType(TextField)),
      'not-an-email',
    );
    await tester.pump();
    await tester.tap(find.widgetWithText(FilledButton, 'Добавить'));
    await tester.pumpAndSettle();
    expect(find.text('Укажите точный email.'), findsOneWidget);
    await tester.tap(find.text('Отмена'));
    await tester.pumpAndSettle();
    expect(find.text('Добавить email'), findsOneWidget);
  });

  testWidgets('email bind keeps a conflict visible and recoverable', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = GraphTestHarness(_client(conflict: true));
    harness.configure();
    await openGraph(tester, harness);
    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Ada').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('В центр'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Добавить email'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.descendant(of: find.byType(AlertDialog), matching: find.byType(TextField)),
      'ada@example.com',
    );
    await tester.pump();
    await tester.tap(find.widgetWithText(FilledButton, 'Добавить'));
    await tester.pumpAndSettle();

    expect(find.text('Этот email уже принадлежит другому человеку.'), findsOneWidget);
    expect(find.text('Добавить email'), findsWidgets);
    await tester.tap(find.text('Отмена'));
    await tester.pumpAndSettle();
    expect(find.text('Этот email уже принадлежит другому человеку.'), findsNothing);
    expect(find.text('Добавить email'), findsOneWidget);
  });
}

MockClient _client({
  bool Function()? bound,
  void Function()? onBind,
  bool conflict = false,
  bool malformed = false,
}) {
  return MockClient((request) async {
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
      return jsonUtf8Response(
        graphWorkspaceJson(nodes: [graphObjectJson(id: 'task-home', title: 'Home')]),
      );
    }
    if (request.url.path == '/graph/people/person-ada/emails') {
      if (malformed) {
        return http.Response(
          jsonEncode({'detail': 'email identity is malformed'}),
          422,
        );
      }
      if (conflict) {
        return http.Response(
          jsonEncode({'detail': 'person email is already bound'}),
          409,
        );
      }
      onBind?.call();
      return jsonUtf8Response({
        'person_id': 'person-ada',
        'evidence_id': 'evidence-1',
        'evidence_type': 'user_confirmed',
        'state': 'active',
      });
    }
    if (request.url.path == '/graph/people-workspace') {
      final root = request.url.queryParameters['root_id'];
      if (root == 'person-ada') {
        return jsonUtf8Response(_rooted(bound: bound?.call() ?? false));
      }
      return jsonUtf8Response(_overview());
    }
    return http.Response(jsonEncode({}), 404);
  });
}

Map<String, dynamic> _overview() {
  return {
    'root_id': null,
    'seed_ids': ['person-ada'],
    'nodes': [graphObjectJson(id: 'person-ada', title: 'Ada', kind: 'person')],
    'edges': [],
    'truncated': false,
    'people': [_person(rooted: false, bound: false)],
  };
}

Map<String, dynamic> _rooted({required bool bound}) {
  return {
    'root_id': 'person-ada',
    'seed_ids': ['person-ada'],
    'nodes': [graphObjectJson(id: 'person-ada', title: 'Ada', kind: 'person')],
    'edges': [],
    'truncated': false,
    'people': [_person(rooted: true, bound: bound)],
  };
}

Map<String, dynamic> _person({required bool rooted, required bool bound}) {
  return {
    'person_id': 'person-ada',
    'title': 'Ada',
    'salience_score': 0,
    'identities': bound
        ? [
            {
              'provider': 'email',
              'identity_type': 'email',
              'display_value': 'ada@example.com',
              'realm': '',
              'canonical_value': 'ada@example.com',
              'state': 'effective',
              'confirmable': false,
            },
          ]
        : [],
    'routes': [],
    'identity_conflict': false,
    'open_task_count': 0,
    'recent_communication_count': bound ? 1 : 0,
    'recent_communications': bound
        ? [
            {
              'object_id': 'flow-1',
              'kind': 'email',
              'provider': 'gmail',
              'title': 'Письмо Ada',
              'occurred_at': '2026-09-01T12:00:00Z',
            },
          ]
        : [],
    'salience': rooted
        ? {
            'score': 1,
            'tier': 'incidental',
            'components': [],
            'truncated': false,
            'window_days': 90,
            'claims_object_importance': false,
          }
        : null,
  };
}
