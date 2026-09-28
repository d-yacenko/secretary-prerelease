import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets('People overview can promote, hide, and restore an exact contact', (tester) async {
    final state = _PromotionState();
    await _open(tester, state);
    expect(find.text('Предлагаемые люди'), findsOneWidget);
    expect(find.textContaining('Email'), findsWidgets);
    expect(find.textContaining('2 прямых контакта'), findsOneWidget);
    expect(find.textContaining('сегодня'), findsOneWidget);
    expect(find.text('Hello Ada'), findsOneWidget);
    expect(find.textContaining('secret body'), findsNothing);
    await tester.tap(find.text('Hello Ada'));
    await tester.pumpAndSettle();
    expect(find.text('Hello Ada'), findsWidgets);
    expect(find.textContaining('secret body'), findsNothing);
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.textContaining('коллега'), findsNothing);
    expect(find.textContaining('руководитель'), findsNothing);

    await tester.tap(find.text('Не предлагать'));
    await tester.pumpAndSettle();
    expect(find.text('Предлагаемые люди'), findsNothing);
    expect(find.text('Скрытые предложения'), findsOneWidget);
    expect(state.actions, ['suppress']);

    await tester.tap(find.text('Вернуть'));
    await tester.pumpAndSettle();
    expect(find.text('Предлагаемые люди'), findsOneWidget);
    expect(find.text('Скрытые предложения'), findsNothing);
    expect(state.actions, ['suppress', 'retract']);

    await tester.tap(find.text('Добавить'));
    await tester.pumpAndSettle();
    expect(find.text('Предлагаемые люди'), findsNothing);
    expect(find.text('Ada'), findsWidgets);
    expect(state.actions, ['suppress', 'retract', 'approve']);
  });

  testWidgets('rooted Person detail does not show promotion review', (tester) async {
    final state = _PromotionState(showPerson: true);
    await _open(tester, state);
    await tester.tap(find.text('Ada').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('В центр'));
    await tester.pumpAndSettle();
    expect(find.text('Предлагаемые люди'), findsNothing);
    expect(find.text('Известные контакты'), findsOneWidget);
    expect(find.textContaining('Сигнал активности'), findsOneWidget);
    expect(find.textContaining('Прямые диалоги'), findsOneWidget);
  });
}

class _PromotionState {
  _PromotionState({this.showPerson = false});

  final actions = <String>[];
  final bool showPerson;
  bool suppressed = false;
  bool approved = false;
}

Future<void> _open(WidgetTester tester, _PromotionState state) async {
  tester.view.physicalSize = const Size(1280, 900);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final harness = GraphTestHarness(_client(state));
  harness.configure();
  await openGraph(tester, harness);
  await tester.tap(find.text('Люди'));
  await tester.pumpAndSettle();
}

MockClient _client(_PromotionState state) {
  return MockClient((request) async {
    if (request.url.path == '/notifications') {
      return jsonUtf8Response({'notifications': []});
    }
    if (request.url.path == '/today') {
      return jsonUtf8Response({
        'date': '2026-09-28',
        'timezone': 'Europe/Amsterdam',
        'day_start': '2026-09-28T00:00:00+02:00',
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
    if (request.url.path == '/graph/people/promotions') {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      final action = body['action'] as String;
      state.actions.add(action);
      state.suppressed = action == 'suppress' ? true : action == 'retract' ? false : state.suppressed;
      if (action == 'approve') {
        state.approved = true;
        state.suppressed = false;
      }
      return jsonUtf8Response({'action': action, 'person_id': 'person-ada'});
    }
    if (request.url.path == '/graph/people-workspace') {
      final root = request.url.queryParameters['root_id'];
      if (root == 'person-ada') {
        return jsonUtf8Response(_rooted());
      }
      return jsonUtf8Response(_overview(state));
    }
    if (request.url.path == '/objects/flow-1/neighbors') {
      return jsonUtf8Response({'object_id': 'flow-1', 'neighbors': []});
    }
    if (request.url.path == '/objects/flow-1/context') {
      return jsonUtf8Response({
        'object': graphObjectJson(id: 'flow-1', title: 'Hello Ada', kind: 'email', provider: 'yandex_mail'),
        'edges': [],
        'neighbors': [],
      });
    }
    if (request.url.path == '/objects/flow-1/open-target') {
      return jsonUtf8Response({
        'available': false,
        'action': 'unavailable',
        'label': 'Открыть в источнике',
        'reason': 'missing',
      });
    }
    if (request.url.path == '/objects/flow-1/labels') {
      return jsonUtf8Response({'labels': []});
    }
    if (request.url.path == '/objects/flow-1') {
      return jsonUtf8Response(
        graphObjectJson(id: 'flow-1', title: 'Hello Ada', kind: 'email', provider: 'yandex_mail'),
      );
    }
    return http.Response(jsonEncode({}), 404);
  });
}

Map<String, dynamic> _overview(_PromotionState state) {
  final visiblePerson = state.approved || state.showPerson;
  final people = visiblePerson ? [_person(rooted: false)] : <Map<String, dynamic>>[];
  final nodes = visiblePerson
      ? [graphObjectJson(id: 'person-ada', title: 'Ada', kind: 'person')]
      : <Map<String, dynamic>>[];
  return {
    'root_id': null,
    'seed_ids': visiblePerson ? ['person-ada'] : <String>[],
    'nodes': nodes,
    'edges': [],
    'truncated': false,
    'people': people,
    'promotion_candidates': state.suppressed || state.approved ? [] : [_candidate()],
    'promotion_candidates_truncated': false,
    'promotion_suppressions': state.suppressed ? [_suppression()] : [],
  };
}

Map<String, dynamic> _rooted() {
  return {
    'root_id': 'person-ada',
    'seed_ids': ['person-ada'],
    'nodes': [graphObjectJson(id: 'person-ada', title: 'Ada', kind: 'person')],
    'edges': [],
    'truncated': false,
    'people': [_person(rooted: true)],
    'promotion_candidates': [],
    'promotion_suppressions': [],
  };
}

Map<String, dynamic> _candidate() {
  return {
    'provider': 'email',
    'identity_type': 'email',
    'realm': '',
    'canonical_value': 'ada@example.com',
    'display_value': 'Ada',
    'direct_hit_count': 2,
    'latest_occurred_at': DateTime.now().toUtc().toIso8601String(),
    'reasons': ['repeated_direct_contact'],
    'sources': [
      {
        'object_id': 'flow-1',
        'kind': 'email',
        'provider': 'yandex_mail',
        'title': 'Hello Ada',
        'occurred_at': DateTime.now().toUtc().toIso8601String(),
      },
    ],
  };
}

Map<String, dynamic> _suppression() {
  return {
    'provider': 'email',
    'identity_type': 'email',
    'realm': '',
    'canonical_value': 'ada@example.com',
    'display_value': 'Ada',
  };
}

Map<String, dynamic> _person({required bool rooted}) {
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
              {'name': 'directness', 'value': 8},
            ],
            'truncated': false,
            'window_days': 90,
            'claims_object_importance': false,
          }
        : null,
  };
}
