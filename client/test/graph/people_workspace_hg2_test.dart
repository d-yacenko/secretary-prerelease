import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets('promotion review stays bounded and collapse survives refresh', (tester) async {
    final approved = <String>[];
    await _open(
      tester,
      const Size(1280, 900),
      client: _client(approved: approved),
    );
    expect(find.byKey(const ValueKey('person-summary-card-task-home')), findsNothing);
    expect(find.byKey(const Key('graph_node_task-home')), findsOneWidget);

    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('promotion-review')), findsNothing);
    await tester.tap(find.byKey(const ValueKey('people-inspector-toggle')));
    await tester.pumpAndSettle();
    expect(find.text('Предлагаемые · 5'), findsOneWidget);
    expect(find.byType(Scrollbar), findsWidgets);
    expect(find.byKey(const ValueKey('promotion-candidate-person-4@example.com')), findsOneWidget);
    final canvas = tester.getSize(find.byKey(const ValueKey('graph-canvas-region')));
    expect(canvas.height, greaterThan(200));
    final source = tester.getSize(
      find.byKey(const ValueKey('promotion-source-person-0@example.com-flow-0-0')),
    );
    expect(source.width, lessThanOrEqualTo(148));
    expect(find.textContaining('тело письма'), findsNothing);

    await tester.tap(find.byKey(const ValueKey('people-inspector-close')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('promotion-review-scroll')), findsNothing);
    expect(tester.getSize(find.byKey(const ValueKey('graph-canvas-region'))).height, greaterThan(200));
  });

  testWidgets('closed inspector survives the same screen refresh', (tester) async {
    final harness = await _open(tester, const Size(1280, 900), client: _client());
    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('people-inspector-toggle')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('people-inspector-close')));
    await tester.pumpAndSettle();
    await harness.graph.loadOverview();
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('promotion-review-scroll')), findsNothing);
    expect(find.text('Кандидаты · 5'), findsOneWidget);
    expect(find.byKey(const ValueKey('graph-canvas-region')), findsOneWidget);
  });

  testWidgets('candidate action targets that identity and hidden restore works', (tester) async {
    final approved = <String>[];
    await _open(tester, const Size(800, 700), client: _client(approved: approved));
    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('people-inspector-toggle')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const ValueKey('promotion-approve-person-2@example.com')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('promotion-approve-person-2@example.com')));
    await tester.pumpAndSettle();
    expect(approved, ['person-2@example.com']);
    final reviewScroll = tester.state<ScrollableState>(
      find.descendant(
        of: find.byKey(const ValueKey('promotion-review-scroll')),
        matching: find.byType(Scrollable),
      ),
    );
    reviewScroll.position.jumpTo(0);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Скрытые предложения · 1'));
    await tester.pumpAndSettle();
    expect(find.text('Вернуть'), findsOneWidget);
  });

  testWidgets('rooted person summary uses compact task and flow tiles', (tester) async {
    await _open(tester, const Size(1280, 900), client: _client(rootedDetail: true));
    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-summary-card-person-ada')), findsOneWidget);
    expect(find.text('Ada'), findsWidgets);
    expect(find.text('Связанные задачи · 1'), findsWidgets);
    expect(find.text('Сообщения · 1'), findsWidgets);
    expect(find.byKey(const Key('person-provider-cues-person-ada')), findsOneWidget);

    await tester.tap(find.text('Ada').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('В центр'));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('person-summary-header')), findsOneWidget);
    expect(find.text('Связанные задачи · 1'), findsWidgets);
    expect(find.text('Сообщения · 1'), findsWidgets);
    expect(find.byKey(const ValueKey('person-task-tile-task-1')), findsOneWidget);
    expect(find.textContaining('Направление'), findsWidgets);
    expect(find.textContaining('Участвует'), findsOneWidget);
    expect(find.byKey(const ValueKey('person-flow-tile-flow-1')), findsOneWidget);
    expect(find.textContaining('очень длинный заголовок'), findsOneWidget);
    expect(find.textContaining('тело письма'), findsNothing);
    expect(find.text('Известные контакты'), findsOneWidget);
    expect(find.textContaining('Сигнал активности'), findsOneWidget);
    final tile = tester.getSize(find.byKey(const ValueKey('person-task-tile-task-1')));
    expect(tile.width, lessThanOrEqualTo(168));
  });

  testWidgets('person without tasks or flow stays compact', (tester) async {
    await _open(tester, const Size(1280, 900), client: _client(emptyPerson: true));
    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Ada').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('В центр'));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-task-empty')), findsOneWidget);
    expect(find.byKey(const ValueKey('person-flow-empty')), findsOneWidget);
    expect(tester.getSize(find.byKey(const ValueKey('person-task-empty'))).height, lessThanOrEqualTo(48));
  });
}

Future<GraphTestHarness> _open(
  WidgetTester tester,
  Size size, {
  required MockClient client,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final harness = GraphTestHarness(client);
  harness.configure();
  await openGraph(tester, harness);
  return harness;
}

MockClient _client({
  List<String>? approved,
  bool rootedDetail = false,
  bool emptyPerson = false,
}) {
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
      approved?.add(body['canonical_value'] as String);
      return jsonUtf8Response({'action': body['action'], 'person_id': 'person-ada'});
    }
    if (request.url.path == '/graph/people-workspace') {
      final root = request.url.queryParameters['root_id'];
      if (root == 'person-ada') {
        return jsonUtf8Response(_rooted(empty: emptyPerson));
      }
      return jsonUtf8Response(_overview(detail: rootedDetail || emptyPerson));
    }
    return http.Response('{}', 404);
  });
}

Map<String, dynamic> _overview({required bool detail}) {
  return {
    'root_id': null,
    'seed_ids': detail ? ['person-ada'] : <String>[],
    'nodes': detail
        ? [graphObjectJson(id: 'person-ada', title: 'Ada', kind: 'person')]
        : [graphObjectJson(id: 'person-ada', title: 'Ada', kind: 'person')],
    'edges': [],
    'truncated': false,
    'people': [_person(rooted: false, empty: !detail)],
    'promotion_candidates': [
      for (var index = 0; index < 5; index++) _candidate(index),
    ],
    'promotion_candidates_truncated': false,
    'promotion_suppressions': [_suppression()],
  };
}

Map<String, dynamic> _rooted({required bool empty}) {
  return {
    'root_id': 'person-ada',
    'seed_ids': ['person-ada'],
    'nodes': [graphObjectJson(id: 'person-ada', title: 'Ada', kind: 'person')],
    'edges': [],
    'truncated': false,
    'people': [_person(rooted: true, empty: empty)],
    'promotion_candidates': [],
    'promotion_suppressions': [],
  };
}

Map<String, dynamic> _candidate(int index) {
  return {
    'provider': 'email',
    'identity_type': 'email',
    'realm': '',
    'canonical_value': 'person-$index@example.com',
    'display_value': 'Person $index',
    'direct_hit_count': 2,
    'latest_occurred_at': '2026-09-28T10:00:00Z',
    'reasons': ['repeated_direct_contact'],
    'sources': [
      for (var source = 0; source < 3; source++)
        {
          'object_id': 'flow-$index-$source',
          'kind': 'email',
          'provider': 'yandex_mail',
          'title': 'Note $index $source',
          'occurred_at': '2026-09-28T10:00:00Z',
        },
    ],
  };
}

Map<String, dynamic> _suppression() {
  return {
    'provider': 'email',
    'identity_type': 'email',
    'realm': '',
    'canonical_value': 'hidden@example.com',
    'display_value': 'Hidden',
  };
}

Map<String, dynamic> _person({required bool rooted, required bool empty}) {
  final longTitle = 'очень длинный заголовок ${'направление ' * 12}';
  return {
    'person_id': 'person-ada',
    'title': 'Ada',
    'salience_score': 4,
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
    'open_task_count': empty ? 0 : 1,
    'recent_communication_count': empty ? 0 : 1,
    'task_involvement': !rooted || empty
        ? const []
        : [
            {
              'task_id': 'task-1',
              'title': longTitle,
              'role': 'involves',
              'edge_state': 'confirmed',
              'edge_origin': 'user',
              'completion_mode': 'ongoing',
              'due_at': '2026-10-01T09:00:00Z',
            },
          ],
    'recent_communications': !rooted || empty
        ? const []
        : [
            {
              'object_id': 'flow-1',
              'kind': 'email',
              'provider': 'yandex_mail',
              'title': 'Письмо без тела',
              'occurred_at': '2026-09-20T08:00:00Z',
            },
          ],
    'salience': rooted
        ? {
            'score': 4,
            'tier': 'known',
            'components': [
              {'name': 'directness', 'value': 4},
            ],
            'truncated': false,
            'window_days': 90,
            'claims_object_importance': false,
          }
        : null,
  };
}
