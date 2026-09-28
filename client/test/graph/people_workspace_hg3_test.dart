import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets('inspector opens on candidates and selection does not re-root', (tester) async {
    final harness = await _open(tester, const Size(1280, 900), client: _client());
    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    expect(harness.graph.rootId, isNull);
    expect(find.byKey(const ValueKey('promotion-review')), findsNothing);

    await tester.tap(find.byKey(const ValueKey('people-inspector-toggle')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('people-inspector')), findsOneWidget);
    expect(find.text('Предлагаемые · 1'), findsOneWidget);
    expect(
      find.descendant(
        of: find.byKey(const ValueKey('people-inspector')),
        matching: find.byType(Scrollbar),
      ),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('person-summary-header')), findsNothing);
    expect(harness.graph.selectedObjectId, isNull);

    await tester.tap(find.byKey(const Key('graph_node_person-bound')));
    await tester.pumpAndSettle();
    expect(harness.graph.rootId, isNull);
    expect(harness.graph.selectedObjectId, 'person-bound');
    expect(find.text('Детали'), findsOneWidget);
    expect(find.text('Письмо bound'), findsOneWidget);
    expect(find.text('Сообщения · ≥4'), findsWidgets);

    await tester.tap(
      find.descendant(
        of: find.byKey(const ValueKey('people-inspector-switch')),
        matching: find.text('Кандидаты'),
      ),
    );
    await tester.pumpAndSettle();
    expect(harness.graph.selectedObjectId, 'person-bound');
    expect(find.text('Предлагаемые · 1'), findsOneWidget);
    expect(find.text('Письмо bound'), findsNothing);

    await tester.tap(
      find.descendant(
        of: find.byKey(const ValueKey('people-inspector-switch')),
        matching: find.text('Детали'),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Письмо bound'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('people-inspector-close')));
    await tester.pumpAndSettle();
    expect(harness.graph.selectedObjectId, 'person-bound');
    expect(find.byKey(const ValueKey('promotion-review-scroll')), findsNothing);

    await tester.tap(find.byKey(const ValueKey('people-inspector-toggle')));
    await tester.pumpAndSettle();
    expect(harness.graph.selectedObjectId, 'person-bound');
    expect(find.text('Письмо bound'), findsOneWidget);
    expect(find.text('Человек'), findsNothing);
    expect(find.text('Связанные задачи · 2'), findsWidgets);
  });

  testWidgets('rooted detail waits, ignores a stale person, and retries', (tester) async {
    final gates = {
      'person-a': Completer<void>(),
      'person-b': Completer<void>(),
    };
    final failures = {'person-a': 2};
    await _open(tester, const Size(1280, 900), client: _client(gates: gates, failures: failures));
    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('graph_node_person-a')));
    await tester.pump();
    expect(find.byKey(const ValueKey('person-detail-loading')), findsOneWidget);
    expect(find.text('Нет недавних коммуникаций'), findsNothing);
    expect(find.text('Письмо A'), findsNothing);

    await tester.tap(find.byKey(const Key('graph_node_person-b')));
    await tester.pump();
    gates['person-a']!.complete();
    await tester.pump();
    expect(find.text('Письмо A'), findsNothing);
    expect(find.byKey(const ValueKey('person-detail-loading')), findsOneWidget);

    gates['person-b']!.complete();
    await tester.pumpAndSettle();
    expect(find.text('Письмо B'), findsOneWidget);
    expect(find.text('Письмо A'), findsNothing);

    await tester.tap(find.byKey(const Key('graph_node_person-a')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-detail-error')), findsOneWidget);
    expect(find.text('Письмо B'), findsNothing);
    await tester.tap(find.byKey(const ValueKey('person-detail-retry')));
    await tester.pumpAndSettle();
    expect(find.text('Письмо A'), findsOneWidget);
    expect(find.text('ada-a@example.com'), findsWidgets);
  });

  testWidgets('overview metrics disclose truncation and rename keeps the identity', (tester) async {
    final titles = {'person-exact': 'Exact'};
    final patched = <String>[];
    await _open(
      tester,
      const Size(1280, 900),
      client: _client(titles: titles, patched: patched),
    );
    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    expect(find.text('Сообщения · 0'), findsOneWidget);
    expect(find.byKey(const Key('person-message-partial-person-gap')), findsOneWidget);
    expect(find.text('Сообщения · ≥3'), findsOneWidget);
    expect(
      find.descendant(
        of: find.byKey(const Key('graph_node_person-gap')),
        matching: find.text('Сообщения · 0'),
      ),
      findsNothing,
    );

    await tester.tap(find.byKey(const Key('graph_node_person-exact')));
    await tester.pumpAndSettle();
    expect(find.text('ada-exact@example.com'), findsWidgets);
    await tester.tap(find.byKey(const ValueKey('person-rename')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.descendant(of: find.byType(AlertDialog), matching: find.byType(TextField)),
      'Exact Renamed',
    );
    await tester.tap(find.widgetWithText(FilledButton, 'Сохранить'));
    await tester.pumpAndSettle();

    expect(patched, ['Exact Renamed']);
    expect(find.text('Exact Renamed'), findsWidgets);
    expect(find.text('ada-exact@example.com'), findsWidgets);
    expect(find.text('Exact'), findsNothing);
  });

  testWidgets('narrow people inspector stays on screen', (tester) async {
    await _open(tester, const Size(390, 700), client: _client());
    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('people-inspector-toggle')));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.byKey(const ValueKey('people-inspector')), findsOneWidget);
    expect(find.text('Предлагаемые · 1'), findsOneWidget);
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
  Map<String, Completer<void>>? gates,
  Map<String, int>? failures,
  Map<String, String>? titles,
  List<String>? patched,
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
    if (request.method == 'PATCH' && request.url.path == '/objects/person-exact') {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      final title = body['title'] as String;
      titles!['person-exact'] = title;
      patched?.add(title);
      return jsonUtf8Response({
        ...graphObjectJson(id: 'person-exact', title: title, kind: 'person'),
        'created_at': '2026-09-01T00:00:00Z',
        'updated_at': '2026-09-28T00:00:00Z',
      });
    }
    if (request.url.path == '/graph/people-workspace') {
      final root = request.url.queryParameters['root_id'];
      if (root != null) {
        final gate = gates?[root];
        if (gate != null && !gate.isCompleted) {
          await gate.future;
        }
        final left = failures?[root] ?? 0;
        if (left > 0) {
          failures![root] = left - 1;
          return http.Response('{}', 500);
        }
        return jsonUtf8Response(_workspace(root: root, titles: titles));
      }
      return jsonUtf8Response(_workspace(titles: titles));
    }
    return http.Response('{}', 404);
  });
}

Map<String, dynamic> _workspace({String? root, Map<String, String>? titles}) {
  final people = [
    _person('person-bound', 'Bound', messages: 4, truncated: true, tasks: 2, marker: 'Письмо bound'),
    _person('person-gap', 'Gap', messages: 0, truncated: true, tasks: 0, marker: 'Письмо gap'),
    _person(
      'person-exact',
      titles?['person-exact'] ?? 'Exact',
      messages: 0,
      truncated: false,
      tasks: 1,
      marker: 'Письмо exact',
    ),
    _person('person-lower', 'Lower', messages: 3, truncated: true, tasks: 0, marker: 'Письмо lower'),
    _person('person-a', 'Person A', messages: 1, truncated: false, tasks: 1, marker: 'Письмо A'),
    _person('person-b', 'Person B', messages: 2, truncated: false, tasks: 1, marker: 'Письмо B'),
  ];
  final visible = root == null ? people : people.where((item) => item['person_id'] == root);
  return {
    'root_id': root,
    'seed_ids': root == null ? <String>[] : [root],
    'nodes': [
      for (final person in visible)
        graphObjectJson(
          id: person['person_id'] as String,
          title: person['title'] as String,
          kind: 'person',
        ),
    ],
    'edges': [],
    'truncated': false,
    'people': visible.toList(),
    'promotion_candidates': root == null ? [_candidate()] : <Map<String, dynamic>>[],
    'promotion_candidates_truncated': false,
    'promotion_suppressions': <Map<String, dynamic>>[],
  };
}

Map<String, dynamic> _person(
  String id,
  String title, {
  required int messages,
  required bool truncated,
  required int tasks,
  required String marker,
}) {
  return {
    'person_id': id,
    'title': title,
    'salience_score': 1,
    'identities': [
      {
        'provider': 'email',
        'identity_type': 'email',
        'display_value': 'ada-$id@example.com'.replaceFirst('person-', ''),
        'realm': '',
        'canonical_value': 'ada-$id@example.com'.replaceFirst('person-', ''),
        'state': 'effective',
        'confirmable': false,
      },
    ],
    'routes': const [],
    'identity_conflict': false,
    'open_task_count': tasks,
    'recent_communication_count': messages,
    'recent_communication_count_truncated': truncated,
    'task_involvement': [
      for (var index = 0; index < tasks; index++)
        {
          'task_id': 'task-$id-$index',
          'title': 'Task $index',
          'role': 'involves',
          'edge_state': 'confirmed',
          'edge_origin': 'user',
          'completion_mode': 'ongoing',
        },
    ],
    'recent_communications': [
      {
        'object_id': 'flow-$id',
        'kind': 'email',
        'provider': 'email',
        'title': marker,
        'occurred_at': '2026-09-20T08:00:00Z',
      },
    ],
    'salience': null,
  };
}

Map<String, dynamic> _candidate() {
  return {
    'provider': 'email',
    'identity_type': 'email',
    'realm': '',
    'canonical_value': 'candidate@example.com',
    'display_value': 'Candidate',
    'direct_hit_count': 2,
    'latest_occurred_at': '2026-09-28T10:00:00Z',
    'reasons': ['repeated_direct_contact'],
    'sources': [
      {
        'object_id': 'flow-candidate',
        'kind': 'email',
        'provider': 'email',
        'title': 'Note',
        'occurred_at': '2026-09-28T10:00:00Z',
      },
    ],
  };
}
