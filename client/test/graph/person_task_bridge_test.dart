import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/graph/graph_workspace_controller.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets('person can link a task role and a repeat stays one row', (tester) async {
    final state = _BridgeState();
    final harness = await _open(tester, _client(state));
    expect(find.text('Добавить связь'), findsNothing);
    expect(find.text('Связать с задачей / направлением'), findsOneWidget);
    expect(find.textContaining('Этот человек попросил выполнить'), findsOneWidget);
    expect(find.textContaining('Ждём от этого человека'), findsOneWidget);
    expect(find.byKey(const ValueKey('person-task-tile-edge-ask')), findsOneWidget);
    expect(find.byKey(const ValueKey('person-task-tile-edge-wait')), findsOneWidget);

    await _reveal(tester, find.byKey(const ValueKey('person-task-link')));
    await tester.tap(find.byKey(const ValueKey('person-task-link')));
    await tester.pumpAndSettle();
    final add = tester.widget<FilledButton>(find.byKey(const ValueKey('person-task-add')));
    expect(add.onPressed, isNull);

    await tester.tap(find.byKey(const ValueKey('person-task-role-waiting_on')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('person-task-search')), 'Ship');
    await tester.pumpAndSettle();
    expect(find.textContaining('Открыта'), findsWidgets);
    expect(find.byKey(const ValueKey('person-task-option-task-deleted')), findsNothing);
    await tester.tap(find.byKey(const ValueKey('person-task-option-task-ship')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('person-task-add')));
    await tester.pumpAndSettle();

    expect(state.calls, contains('POST /tasks/task-ship/actors waiting_on'));
    expect(find.byKey(const ValueKey('person-task-tile-edge-ship')), findsOneWidget);
    expect(find.text('Связанные задачи · 3'), findsWidgets);

    await _reveal(tester, find.byKey(const ValueKey('person-task-link')));
    await tester.tap(find.byKey(const ValueKey('person-task-link')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('person-task-role-waiting_on')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('person-task-search')), 'Ship');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('person-task-option-task-ship')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('person-task-add')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-task-tile-edge-ship')), findsOneWidget);
    expect(state.calls.where((call) => call.startsWith('POST /tasks/task-ship/actors')), hasLength(2));
    expect(harness.graph.selectedObjectId, 'person-ada');
  });

  testWidgets('task picker hides terminal tasks and a second role keeps the count', (tester) async {
    final state = _BridgeState();
    await _open(tester, _client(state));
    expect(find.text('Связанные задачи · 2'), findsWidgets);

    await _reveal(tester, find.byKey(const ValueKey('person-task-link')));
    await tester.tap(find.byKey(const ValueKey('person-task-link')));
    await tester.pumpAndSettle();
    expect(find.text('Связано с'), findsNothing);
    expect(find.text('Ссылается на'), findsNothing);
    expect(find.text('Зависит от'), findsNothing);
    expect(find.text('Этот человек попросил выполнить'), findsWidgets);
    expect(find.text('Задача поручена этому человеку'), findsOneWidget);
    expect(find.text('Ждём от этого человека'), findsWidgets);
    expect(find.text('Этот человек участвует'), findsWidgets);

    await tester.tap(find.byKey(const ValueKey('person-task-role-requested_by')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('person-task-search')), 'task');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('person-task-option-task-ship')));
    await tester.pumpAndSettle();
    expect(
      find.text('Ada просит выполнить задачу «Ship report»'),
      findsOneWidget,
    );
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('person-task-add'))).onPressed, isNotNull);

    await tester.tap(find.byKey(const ValueKey('person-task-role-delegated_to')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('person-task-option-task-ask')));
    await tester.pumpAndSettle();
    expect(
      find.text('Задача «Ask» поручена человеку Ada'),
      findsOneWidget,
    );
    expect(find.textContaining('поручил'), findsNothing);

    await tester.enterText(find.byKey(const ValueKey('person-task-search')), 'task');
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-task-option-task-ship')), findsOneWidget);
    expect(find.byKey(const ValueKey('person-task-option-task-progress')), findsOneWidget);
    expect(find.byKey(const ValueKey('person-task-option-task-direction')), findsOneWidget);
    expect(find.byKey(const ValueKey('person-task-option-task-legacy')), findsOneWidget);
    for (final status in ['done', 'completed', 'cancelled', 'archived', 'deleted']) {
      expect(find.byKey(ValueKey('person-task-option-task-$status')), findsNothing);
    }

    await tester.tap(find.byKey(const ValueKey('person-task-add')));
    await tester.pumpAndSettle();
    expect(state.calls, contains('POST /tasks/task-ask/actors delegated_to'));
    expect(find.text('Связанные задачи · 2'), findsWidgets);
    expect(find.textContaining('Задача поручена этому человеку'), findsOneWidget);
    expect(find.textContaining('Делегировано'), findsNothing);
    expect(find.textContaining('Этот человек попросил выполнить'), findsWidgets);
  });

  testWidgets('confirmed actor is removed through the task actor endpoint', (tester) async {
    final state = _BridgeState();
    await _open(tester, _client(state));
    await _reveal(tester, find.byKey(const ValueKey('person-task-remove-edge-ask')));
    await tester.tap(find.byKey(const ValueKey('person-task-remove-edge-ask')));
    await tester.pumpAndSettle();
    expect(state.calls, contains('DELETE /tasks/task-ask/actors/edge-ask'));
    expect(find.byKey(const ValueKey('person-task-tile-edge-ask')), findsNothing);
    expect(find.byKey(const ValueKey('person-task-tile-edge-wait')), findsOneWidget);
  });

  testWidgets('proposed actor can be confirmed or rejected', (tester) async {
    final state = _BridgeState();
    await _open(tester, _client(state));
    expect(find.textContaining('Предложено секретарём'), findsOneWidget);
    await _reveal(tester, find.byKey(const ValueKey('person-task-confirm-edge-join')));
    await tester.tap(find.byKey(const ValueKey('person-task-confirm-edge-join')));
    await tester.pumpAndSettle();
    expect(state.calls, contains('POST /relations/edge-join/decision confirm'));
    expect(find.textContaining('Предложено секретарём'), findsNothing);
    expect(find.byKey(const ValueKey('person-task-remove-edge-join')), findsOneWidget);
  });

  testWidgets('proposed actor can be rejected', (tester) async {
    final state = _BridgeState();
    await _open(tester, _client(state));
    await _reveal(tester, find.byKey(const ValueKey('person-task-reject-edge-join')));
    await tester.tap(find.byKey(const ValueKey('person-task-reject-edge-join')));
    await tester.pumpAndSettle();
    expect(state.calls, contains('POST /relations/edge-join/decision reject'));
    expect(find.byKey(const ValueKey('person-task-tile-edge-join')), findsNothing);
  });

  testWidgets('task tile still opens the task', (tester) async {
    final state = _BridgeState();
    final harness = await _open(tester, _client(state));
    await _reveal(tester, find.text('Join'));
    await tester.tap(find.text('Join'));
    await tester.pumpAndSettle();
    expect(harness.graph.mode, GraphWorkspaceMode.tasks);
    expect(harness.graph.rootId, 'task-join');
  });
}

class _BridgeState {
  final calls = <String>[];
  final rows = <Map<String, dynamic>>[
    _row('edge-ask', 'task-ask', 'Ask', 'requested_by'),
    _row('edge-wait', 'task-ask', 'Ask', 'waiting_on'),
    _row('edge-join', 'task-join', 'Join', 'involves', state: 'proposed', origin: 'agent'),
  ];
}

Map<String, dynamic> _row(
  String edgeId,
  String taskId,
  String title,
  String role, {
  String state = 'confirmed',
  String origin = 'user',
}) {
  return {
    'edge_id': edgeId,
    'task_id': taskId,
    'title': title,
    'status': 'open',
    'completion_mode': 'finite',
    'due_at': null,
    'role': role,
    'edge_state': state,
    'edge_origin': origin,
  };
}

Future<void> _reveal(WidgetTester tester, Finder target) async {
  final scrollable = find.descendant(
    of: find.byKey(const ValueKey('graph-detail-panel')),
    matching: find.byType(Scrollable),
  );
  await tester.scrollUntilVisible(target, 120, scrollable: scrollable);
  await tester.pumpAndSettle();
}

Future<GraphTestHarness> _open(WidgetTester tester, MockClient client) async {
  tester.view.physicalSize = const Size(1280, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final harness = GraphTestHarness(client);
  harness.configure();
  await openGraph(tester, harness);
  await tester.tap(find.text('Люди'));
  await tester.pumpAndSettle();
  await tester.tap(find.text('Ada').first);
  await tester.pumpAndSettle();
  await tester.tap(find.text('В центр'));
  await tester.pumpAndSettle();
  return harness;
}

MockClient _client(_BridgeState state) {
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
      return jsonUtf8Response(
        graphWorkspaceJson(
          rootId: request.url.queryParameters['root_id'],
          nodes: [graphObjectJson(id: 'task-join', title: 'Join', kind: 'task')],
        ),
      );
    }
    if (request.url.path == '/search') {
      return jsonUtf8Response([
        graphObjectJson(id: 'task-ship', title: 'Ship report', kind: 'task', status: 'open', dueAt: '2026-10-01T09:00:00Z'),
        graphObjectJson(id: 'task-ask', title: 'Ask', kind: 'task', status: 'open'),
        graphObjectJson(id: 'task-progress', title: 'Moving', kind: 'task', status: 'in_progress'),
        graphObjectJson(id: 'task-direction', title: 'Weekly direction', kind: 'task', status: 'open', completionMode: 'ongoing'),
        {...graphObjectJson(id: 'task-legacy', title: 'Legacy active', kind: 'task'), 'status': null},
        for (final status in ['done', 'completed', 'cancelled', 'archived', 'deleted'])
          graphObjectJson(id: 'task-$status', title: 'Terminal $status', kind: 'task', status: status),
      ]);
    }
    if (request.method == 'POST' && request.url.path.startsWith('/tasks/') && request.url.path.endsWith('/actors')) {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      final taskId = request.url.path.split('/')[2];
      final role = body['role'] as String;
      state.calls.add('POST ${request.url.path} $role');
      final existing = state.rows.where((row) => row['task_id'] == taskId && row['role'] == role);
      final created = existing.isEmpty;
      final edgeId = created
          ? (taskId == 'task-ship' ? 'edge-ship' : 'edge-$taskId-$role')
          : existing.first['edge_id'] as String;
      if (created) {
        final title = taskId == 'task-ship' ? 'Ship report' : 'Ask';
        state.rows.add(_row(edgeId, taskId, title, role));
      }
      return jsonUtf8Response({
        'edge': _edge(edgeId, taskId, role),
        'created': created,
        'changed': created,
      });
    }
    if (request.method == 'DELETE' && request.url.path.startsWith('/tasks/') && request.url.path.contains('/actors/')) {
      state.calls.add('DELETE ${request.url.path}');
      final edgeId = request.url.path.split('/').last;
      state.rows.removeWhere((row) => row['edge_id'] == edgeId);
      return jsonUtf8Response({
        'edge': _edge(edgeId, 'task-ask', 'requested_by', state: 'rejected'),
        'created': false,
        'changed': true,
      });
    }
    if (request.method == 'POST' && request.url.path.startsWith('/relations/') && request.url.path.endsWith('/decision')) {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      final edgeId = request.url.path.split('/')[2];
      final decision = body['decision'] as String;
      state.calls.add('POST ${request.url.path} $decision');
      final row = state.rows.firstWhere((item) => item['edge_id'] == edgeId);
      if (decision == 'confirm') {
        row['edge_state'] = 'confirmed';
        row['edge_origin'] = 'agent';
      } else {
        state.rows.remove(row);
      }
      return jsonUtf8Response({
        'edge': _edge(edgeId, row['task_id'] as String? ?? 'task-join', row['role'] as String? ?? 'involves', state: decision == 'confirm' ? 'confirmed' : 'rejected'),
      });
    }
    if (request.url.path == '/graph/people-workspace') {
      final root = request.url.queryParameters['root_id'];
      return jsonUtf8Response(_workspace(state, root));
    }
    return http.Response('{}', 404);
  });
}

Map<String, dynamic> _edge(String id, String taskId, String role, {String state = 'confirmed'}) {
  return {
    'id': id,
    'source_id': taskId,
    'target_id': 'person-ada',
    'type': role,
    'origin': 'user',
    'state': state,
    'metadata': <String, dynamic>{},
    'created_at': '2026-09-29T00:00:00Z',
    'updated_at': '2026-09-29T00:00:00Z',
  };
}

Map<String, dynamic> _workspace(_BridgeState state, String? root) {
  return {
    'root_id': root,
    'seed_ids': ['person-ada'],
    'nodes': [graphObjectJson(id: 'person-ada', title: 'Ada', kind: 'person')],
    'edges': [],
    'truncated': false,
    'people': [
      {
        'person_id': 'person-ada',
        'title': 'Ada',
        'salience_score': 1,
        'identities': const [],
        'routes': const [],
        'identity_conflict': false,
        'open_task_count': state.rows.map((row) => row['task_id']).toSet().length,
        'recent_communication_count': 0,
        'task_involvement': root == null ? <Map<String, dynamic>>[] : state.rows,
        'recent_communications': const [],
        'salience': null,
        'consolidations': const [],
      },
    ],
    'promotion_candidates': <Map<String, dynamic>>[],
    'promotion_candidates_truncated': false,
    'promotion_suppressions': <Map<String, dynamic>>[],
  };
}
