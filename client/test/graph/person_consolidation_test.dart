import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/graph/graph_workspace_controller.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets('merge preview swaps, confirms, and undo restores both people', (tester) async {
    final state = _MergeState();
    final harness = await _open(tester, const Size(1280, 900), client: _client(state));
    expect(find.text('Объединить с…'), findsNothing);

    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('graph_node_person-a')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-merge')), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('person-merge')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('person-merge-search')), 'Person');
    await tester.pumpAndSettle();
    expect(state.calls, contains('search:person'));
    expect(find.byKey(const ValueKey('person-merge-option-person-a')), findsNothing);
    expect(find.byKey(const ValueKey('person-merge-option-task-home')), findsNothing);

    await tester.tap(find.byKey(const ValueKey('person-merge-option-person-b')));
    await tester.pumpAndSettle();
    expect(find.text('Остаётся: Person A'), findsOneWidget);
    expect(find.text('Исчезает: Person B'), findsOneWidget);
    expect(find.text('ada@example.com'), findsWidgets);
    expect(state.calls.where((call) => call == 'apply'), isEmpty);

    await tester.tap(find.byKey(const ValueKey('person-merge-swap')));
    await tester.pumpAndSettle();
    expect(find.text('Остаётся: Person B'), findsOneWidget);
    expect(find.text('Исчезает: Person A'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('person-merge-swap')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const ValueKey('person-merge-confirm')));
    await tester.pumpAndSettle();
    expect(state.calls, contains('apply'));
    expect(find.byKey(const Key('graph_node_person-b')), findsNothing);
    expect(harness.graph.selectedObjectId, 'person-a');
    expect(find.text('ada@example.com'), findsWidgets);
    expect(find.text('bob@example.com'), findsWidgets);
    expect(find.text('Связанные задачи · 2'), findsWidgets);
    expect(find.text('Объединено: Person B'), findsOneWidget);

    await tester.ensureVisible(find.byKey(const ValueKey('person-merge-undo-person-b')));
    await tester.tap(find.byKey(const ValueKey('person-merge-undo-person-b')));
    await tester.pumpAndSettle();
    expect(state.calls, contains('undo'));
    expect(find.byKey(const Key('graph_node_person-a')), findsOneWidget);
    expect(find.byKey(const Key('graph_node_person-b')), findsOneWidget);
    expect(find.text('Объединено: Person B'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('blocked preview cannot be applied', (tester) async {
    final state = _MergeState()..blocked = true;
    await _open(tester, const Size(1280, 900), client: _client(state));
    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('graph_node_person-a')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('person-merge')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('person-merge-search')), 'B');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('person-merge-option-person-b')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-merge-blocker')), findsOneWidget);
    final confirm = tester.widget<FilledButton>(find.byKey(const ValueKey('person-merge-confirm')));
    expect(confirm.onPressed, isNull);
    expect(state.calls.where((call) => call == 'apply'), isEmpty);
  });

  testWidgets('conflict shortcut opens preview and does not merge', (tester) async {
    final state = _MergeState()..conflict = true;
    await _open(tester, const Size(1280, 900), client: _client(state));
    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('graph_node_person-a')));
    await tester.pumpAndSettle();
    final shortcut = find.byKey(const ValueKey('person-merge-conflict-ada@example.com'));
    await tester.scrollUntilVisible(
      shortcut,
      200,
      scrollable: find.descendant(
        of: find.byKey(const ValueKey('people-inspector')),
        matching: find.byType(Scrollable),
      ),
    );
    final scroll = tester.state<ScrollableState>(
      find.descendant(
        of: find.byKey(const ValueKey('people-inspector')),
        matching: find.byType(Scrollable),
      ),
    );
    scroll.position.jumpTo(scroll.position.maxScrollExtent);
    await tester.pumpAndSettle();
    await tester.tap(shortcut);
    await tester.pumpAndSettle();
    expect(find.text('Остаётся: Person A'), findsOneWidget);
    expect(find.text('Исчезает: Person B'), findsOneWidget);
    expect(state.calls.where((call) => call == 'apply'), isEmpty);
    expect(find.byKey(const Key('graph_node_person-b')), findsOneWidget);
  });

  testWidgets('rename still works beside merge', (tester) async {
    final state = _MergeState();
    await _open(tester, const Size(1280, 900), client: _client(state));
    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('graph_node_person-a')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('person-rename')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.descendant(of: find.byType(AlertDialog), matching: find.byType(TextField)),
      'Person A renamed',
    );
    await tester.tap(find.widgetWithText(FilledButton, 'Сохранить'));
    await tester.pumpAndSettle();
    expect(state.titles['person-a'], 'Person A renamed');
    expect(find.text('Person A renamed'), findsWidgets);
  });

  testWidgets('merge dialog does not overflow on a narrow layout', (tester) async {
    final harness = await _open(tester, const Size(390, 700), client: _client(_MergeState()));
    await harness.graph.setMode(GraphWorkspaceMode.people);
    await tester.pumpAndSettle();
    harness.graph.selectObject('person-a');
    await tester.pumpAndSettle();
    final details = tester.widget<SegmentedButton<bool>>(
      find.byKey(const ValueKey('people-inspector-switch')),
    );
    details.onSelectionChanged!({false});
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    final merge = tester.widget<TextButton>(
      find.byKey(const ValueKey('person-merge'), skipOffstage: false),
    );
    merge.onPressed!.call();
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-merge-search')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

class _MergeState {
  final calls = <String>[];
  final titles = <String, String>{'person-a': 'Person A', 'person-b': 'Person B'};
  var merged = false;
  var blocked = false;
  var conflict = false;
}

Future<GraphTestHarness> _open(WidgetTester tester, Size size, {required MockClient client}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final harness = GraphTestHarness(client);
  harness.configure();
  await openGraph(tester, harness);
  return harness;
}

MockClient _client(_MergeState state) {
  return MockClient((request) async {
    if (request.url.path == '/notifications') {
      return jsonUtf8Response({'notifications': []});
    }
    if (request.url.path == '/today') {
      return jsonUtf8Response({
        'date': '2026-09-29',
        'timezone': 'Europe/Amsterdam',
        'day_start': '2026-09-29T00:00:00+02:00',
        'tasks': [],
        'calendar_events': [],
        'notifications': [],
      });
    }
    if (request.url.path == '/search/facets') {
      return jsonUtf8Response({'kinds': [], 'providers': []});
    }
    if (request.url.path == '/graph/workspace') {
      return jsonUtf8Response(graphWorkspaceJson(nodes: [graphObjectJson(id: 'task-home', title: 'Home')]));
    }
    if (request.url.path == '/search') {
      state.calls.add('search:${request.url.queryParameters['kind']}');
      return jsonUtf8Response([
        graphObjectJson(id: 'person-a', title: state.titles['person-a']!, kind: 'person'),
        graphObjectJson(id: 'person-b', title: 'Person B', kind: 'person'),
        graphObjectJson(id: 'task-home', title: 'Home'),
      ]);
    }
    if (request.url.path == '/graph/people/merges/preview') {
      state.calls.add('preview');
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      final survivorId = body['survivor_id'] as String;
      final duplicateId = body['duplicate_id'] as String;
      return jsonUtf8Response({
        'survivor_id': survivorId,
        'duplicate_id': duplicateId,
        'survivor': {'person_id': survivorId, 'title': state.titles[survivorId], 'cues': []},
        'duplicate': {'person_id': duplicateId, 'title': state.titles[duplicateId], 'cues': []},
        'identities': [
          {
            'provider': 'email',
            'identity_type': 'email',
            'realm': '',
            'canonical_value': 'ada@example.com',
            'display_value': 'ada@example.com',
          },
        ],
        'identity_count': 1,
        'actor_counts': {'involves': 1},
        'evidence_count': 0,
        'duplicate_bookmarked': false,
        'blockers': state.blocked ? ['duplicate has an unsupported graph edge'] : <String>[],
        'can_merge': !state.blocked,
      });
    }
    if (request.url.path == '/graph/people/merges/undo') {
      state.calls.add('undo');
      state.merged = false;
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      return jsonUtf8Response({
        'survivor_id': body['survivor_id'],
        'duplicate_id': body['duplicate_id'],
        'idempotent': false,
      });
    }
    if (request.url.path == '/graph/people/merges') {
      state.calls.add('apply');
      state.merged = true;
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      return jsonUtf8Response({
        'survivor_id': body['survivor_id'],
        'duplicate_id': body['duplicate_id'],
        'idempotent': false,
      });
    }
    if (request.method == 'PATCH' && request.url.path == '/objects/person-a') {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      state.titles['person-a'] = body['title'] as String;
      return jsonUtf8Response({
        ...graphObjectJson(id: 'person-a', title: state.titles['person-a']!, kind: 'person'),
        'created_at': '2026-09-01T00:00:00Z',
        'updated_at': '2026-09-29T00:00:00Z',
      });
    }
    if (request.url.path == '/graph/people-workspace') {
      final root = request.url.queryParameters['root_id'];
      return jsonUtf8Response(_workspace(state, root));
    }
    return http.Response('{}', 404);
  });
}

Map<String, dynamic> _workspace(_MergeState state, String? root) {
  final people = [
    _person(
      'person-a',
      state.titles['person-a']!,
      identities: state.merged
          ? ['ada@example.com', 'bob@example.com']
          : ['ada@example.com'],
      tasks: state.merged ? 2 : 1,
      conflict: state.conflict && !state.merged,
      consolidations: state.merged,
    ),
    if (!state.merged) _person('person-b', 'Person B', identities: ['bob@example.com'], tasks: 1),
  ];
  final visible = root == null ? people : people.where((item) => item['person_id'] == root);
  return {
    'root_id': root,
    'seed_ids': root == null ? <String>[] : [root],
    'nodes': [
      for (final person in visible)
        graphObjectJson(id: person['person_id'] as String, title: person['title'] as String, kind: 'person'),
    ],
    'edges': [],
    'truncated': false,
    'people': visible.toList(),
    'promotion_candidates': <Map<String, dynamic>>[],
    'promotion_candidates_truncated': false,
    'promotion_suppressions': <Map<String, dynamic>>[],
  };
}

Map<String, dynamic> _person(
  String id,
  String title, {
  required List<String> identities,
  required int tasks,
  bool conflict = false,
  bool consolidations = false,
}) {
  return {
    'person_id': id,
    'title': title,
    'salience_score': 1,
    'identities': [
      for (final value in identities)
        {
          'provider': 'email',
          'identity_type': 'email',
          'display_value': value,
          'realm': '',
          'canonical_value': value,
          'state': 'effective',
          'confirmable': false,
        },
    ],
    'routes': const [],
    'identity_conflict': conflict,
    'identity_candidates': conflict
        ? [
            {
              'provider': 'email',
              'identity_type': 'email',
              'realm': '',
              'canonical_value': 'ada@example.com',
              'display_value': 'ada@example.com',
              'confirmable': false,
              'state': 'conflicted',
              'reasons': ['owned_by_another_person'],
              'sources': <Map<String, dynamic>>[],
              'conflicting_person_id': 'person-b',
            },
          ]
        : <Map<String, dynamic>>[],
    'open_task_count': tasks,
    'recent_communication_count': 0,
    'recent_communication_count_truncated': false,
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
    'recent_communications': const [],
    'salience': conflict
        ? {
            'score': 4,
            'tier': 'known',
            'components': const [],
            'truncated': false,
            'window_days': 90,
            'claims_object_importance': false,
          }
        : null,
    'consolidations': consolidations
        ? [
            {'duplicate_id': 'person-b', 'duplicate_title': 'Person B', 'undo_available': true},
          ]
        : <Map<String, dynamic>>[],
  };
}
