import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets('rooted activity discloses a bounded salience scan', (tester) async {
    await _open(tester, truncated: true);
    expect(
      find.text('Сигнал активности и контекста, не оценка важности человека или сообщения.'),
      findsOneWidget,
    );
    expect(find.textContaining('Прямые диалоги: 0'), findsOneWidget);
    expect(
      find.text('Показана часть активности: расчёт ограничен доступной выборкой коммуникаций.'),
      findsOneWidget,
    );
    expect(find.text('Возможные контакты'), findsNothing);
    expect(find.text('Добавить email'), findsOneWidget);
  });

  testWidgets('complete rooted activity does not add a truncation note', (tester) async {
    await _open(tester, truncated: false);
    expect(
      find.text('Сигнал активности и контекста, не оценка важности человека или сообщения.'),
      findsOneWidget,
    );
    expect(find.textContaining('Прямые диалоги: 8'), findsOneWidget);
    expect(
      find.text('Показана часть активности: расчёт ограничен доступной выборкой коммуникаций.'),
      findsNothing,
    );
  });
}

Future<void> _open(WidgetTester tester, {required bool truncated}) async {
  tester.view.physicalSize = const Size(1280, 900);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final harness = GraphTestHarness(_client(truncated: truncated));
  harness.configure();
  await openGraph(tester, harness);
  await tester.tap(find.text('Люди'));
  await tester.pumpAndSettle();
  await tester.tap(find.text('Ada').first);
  await tester.pumpAndSettle();
  await tester.tap(find.text('В центр'));
  await tester.pumpAndSettle();
}

MockClient _client({required bool truncated}) {
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
    if (request.url.path == '/graph/people-workspace') {
      final root = request.url.queryParameters['root_id'];
      return jsonUtf8Response(root == 'person-ada' ? _rooted(truncated) : _overview());
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
    'people': [_person(rooted: false, truncated: false)],
  };
}

Map<String, dynamic> _rooted(bool truncated) {
  return {
    'root_id': 'person-ada',
    'seed_ids': ['person-ada'],
    'nodes': [graphObjectJson(id: 'person-ada', title: 'Ada', kind: 'person')],
    'edges': [],
    'truncated': false,
    'people': [_person(rooted: true, truncated: truncated)],
  };
}

Map<String, dynamic> _person({required bool rooted, required bool truncated}) {
  return {
    'person_id': 'person-ada',
    'title': 'Ada',
    'salience_score': 8,
    'identities': [
      {
        'provider': 'email',
        'identity_type': 'email',
        'display_value': 'ada@example.com',
        'realm': '',
        'canonical_value': 'ada@example.com',
        'state': 'effective',
        'confirmable': false,
      },
    ],
    'routes': const [],
    'identity_conflict': false,
    'open_task_count': 0,
    'recent_communication_count': 1,
    'task_involvement': const [],
    'recent_communications': const [],
    'salience': rooted
        ? {
            'score': 8,
            'tier': 'incidental',
            'components': [
              {'name': 'directness', 'value': truncated ? 0 : 8},
            ],
            'truncated': truncated,
            'window_days': 90,
            'claims_object_importance': false,
          }
        : null,
  };
}
