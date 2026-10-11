import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets(
    'rename dialog starts from the current title and blocks a blank name',
    (tester) async {
      final state = _RenameState();
      await _openUnrooted(tester, _client(state));
      await _reveal(tester, find.byKey(const ValueKey('person-rename')));
      await tester.tap(find.byKey(const ValueKey('person-rename')));
      await tester.pumpAndSettle();

      final field = tester.widget<TextField>(
        find.byKey(const ValueKey('person-rename-title')),
      );
      expect(field.controller!.text, 'Ada');
      await tester.enterText(
        find.byKey(const ValueKey('person-rename-title')),
        '   ',
      );
      await tester.pump();
      expect(
        tester
            .widget<FilledButton>(
              find.byKey(const ValueKey('person-rename-save')),
            )
            .onPressed,
        isNull,
      );
      expect(state.renameCalls, 0);
    },
  );

  testWidgets('a delayed rename stays open and accepts one request', (
    tester,
  ) async {
    final state = _RenameState()..holdRename = Completer<void>();
    await _openUnrooted(tester, _client(state));
    await _reveal(tester, find.byKey(const ValueKey('person-rename')));
    await tester.tap(find.byKey(const ValueKey('person-rename')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('person-rename-title')),
      '  Ada Prime  ',
    );
    await tester.tap(find.byKey(const ValueKey('person-rename-save')));
    await tester.pump();

    expect(find.byKey(const ValueKey('person-rename-title')), findsOneWidget);
    expect(state.renameCalls, 1);
    expect(state.genericPatches, 0);
    expect(
      tester
          .widget<FilledButton>(
            find.byKey(const ValueKey('person-rename-save')),
          )
          .onPressed,
      isNull,
    );
    expect(
      tester
          .widget<TextButton>(
            find.byKey(const ValueKey('person-rename-cancel')),
          )
          .onPressed,
      isNull,
    );
    await tester.tap(find.byKey(const ValueKey('person-rename-save')));
    await tester.pump();
    expect(state.renameCalls, 1);

    state.holdRename!.complete();
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-rename-title')), findsNothing);
    expect(find.text('Ada Prime'), findsWidgets);
  });

  testWidgets(
    'unrooted rename uses the person endpoint and keeps the overview',
    (tester) async {
      final state = _RenameState();
      final harness = await _openUnrooted(tester, _client(state));
      final gets = state.peopleWorkspaceGets;
      expect(find.text('Люди · страница 1 из 2'), findsOneWidget);

      await _reveal(tester, find.byKey(const ValueKey('person-rename')));
      await tester.tap(find.byKey(const ValueKey('person-rename')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const ValueKey('person-rename-title')),
        'Ada Prime',
      );
      await tester.tap(find.byKey(const ValueKey('person-rename-save')));
      await tester.pumpAndSettle();

      expect(state.renameCalls, 1);
      expect(state.renamePaths, ['/graph/people/person-ada']);
      expect(state.genericPatches, 0);
      expect(state.peopleWorkspaceGets, gets);
      expect(harness.graph.rootId, isNull);
      expect(harness.graph.windowIndex, 0);
      expect(find.text('Люди · страница 1 из 2'), findsOneWidget);
      expect(find.text('Ada Prime'), findsWidgets);
      expect(find.text('Ada'), findsNothing);
      expect(harness.graph.personFor('person-ada')?.title, 'Ada Prime');
    },
  );

  testWidgets(
    'rooted rename updates the title without reloading the workspace',
    (tester) async {
      final state = _RenameState();
      final harness = await _openRooted(tester, _client(state));
      final gets = state.peopleWorkspaceGets;
      await _reveal(tester, find.byKey(const ValueKey('person-rename')));
      await tester.tap(find.byKey(const ValueKey('person-rename')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const ValueKey('person-rename-title')),
        'Ada Prime',
      );
      await tester.tap(find.byKey(const ValueKey('person-rename-save')));
      await tester.pumpAndSettle();

      expect(harness.graph.rootId, 'person-ada');
      expect(state.peopleWorkspaceGets, gets);
      expect(state.genericPatches, 0);
      expect(find.text('Ada Prime'), findsWidgets);
      expect(harness.graph.personFor('person-ada')?.title, 'Ada Prime');
    },
  );

  testWidgets('a failed rename keeps the dialog and the previous title', (
    tester,
  ) async {
    final state = _RenameState()..failNextRename = true;
    final harness = await _openUnrooted(tester, _client(state));
    await _reveal(tester, find.byKey(const ValueKey('person-rename')));
    await tester.tap(find.byKey(const ValueKey('person-rename')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('person-rename-title')),
      'Ada Prime',
    );
    await tester.tap(find.byKey(const ValueKey('person-rename-save')));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('person-rename-error')), findsOneWidget);
    expect(find.text('Имя отклонено'), findsOneWidget);
    expect(
      tester
          .widget<TextField>(find.byKey(const ValueKey('person-rename-title')))
          .controller!
          .text,
      'Ada Prime',
    );
    expect(harness.graph.personFor('person-ada')?.title, 'Ada');
    expect(find.byKey(const ValueKey('person-summary-header')), findsOneWidget);
    expect(
      find.descendant(
        of: find.byKey(const ValueKey('person-summary-header')),
        matching: find.text('Ada'),
      ),
      findsOneWidget,
    );
  });

  testWidgets('a stale people response cannot restore the title after rename', (
    tester,
  ) async {
    final state = _RenameState();
    final harness = await _openUnrooted(tester, _client(state));
    final hold = Completer<void>();
    state.holdPeopleWorkspace = hold;
    await _reveal(
      tester,
      find.byKey(const ValueKey('person-task-remove-edge-requested_by')),
    );
    await tester.tap(
      find.byKey(const ValueKey('person-task-remove-edge-requested_by')),
    );
    await tester.pump();
    expect(state.peopleWorkspaceInFlight, 1);

    await _reveal(tester, find.byKey(const ValueKey('person-rename')));
    await tester.tap(find.byKey(const ValueKey('person-rename')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('person-rename-title')),
      'Ada Prime',
    );
    await tester.tap(find.byKey(const ValueKey('person-rename-save')));
    await tester.pumpAndSettle();
    expect(find.text('Ada Prime'), findsWidgets);

    hold.complete();
    await tester.pumpAndSettle();
    expect(harness.graph.rootId, isNull);
    expect(harness.graph.personFor('person-ada')?.title, 'Ada Prime');
    expect(
      find.descendant(
        of: find.byKey(const ValueKey('person-summary-header')),
        matching: find.text('Ada Prime'),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byKey(const ValueKey('person-summary-header')),
        matching: find.text('Ada'),
      ),
      findsNothing,
    );
  });

  testWidgets(
    'task actor edges stay in participation and leave generic relations',
    (tester) async {
      final state = _RenameState();
      await _openUnrooted(tester, _client(state));
      for (final role in [
        'requested_by',
        'delegated_to',
        'waiting_on',
        'involves',
      ]) {
        expect(
          find.byKey(ValueKey('person-task-tile-edge-$role')),
          findsOneWidget,
        );
        expect(find.byKey(ValueKey('graph-relation-edge-$role')), findsNothing);
      }
      await _reveal(
        tester,
        find.byKey(const ValueKey('graph-relation-edge-related')),
      );
      expect(
        find.byKey(const ValueKey('graph-relation-edge-related')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('graph-relation-edge-off-actor')),
        findsNothing,
      );
      expect(
        find.byKey(const ValueKey('graph-relation-edge-ref')),
        findsOneWidget,
      );
    },
  );
}

class _RenameState {
  var title = 'Ada';
  var failNextRename = false;
  var renameCalls = 0;
  var genericPatches = 0;
  var peopleWorkspaceGets = 0;
  var peopleWorkspaceInFlight = 0;
  Completer<void>? holdRename;
  Completer<void>? holdPeopleWorkspace;
  final renamePaths = <String>[];
}

Future<GraphTestHarness> _openUnrooted(
  WidgetTester tester,
  MockClient client,
) async {
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
  expect(harness.graph.rootId, isNull);
  return harness;
}

Future<GraphTestHarness> _openRooted(
  WidgetTester tester,
  MockClient client,
) async {
  final harness = await _openUnrooted(tester, client);
  await tester.tap(find.text('В центр'));
  await tester.pumpAndSettle();
  expect(harness.graph.rootId, 'person-ada');
  return harness;
}

Future<void> _reveal(WidgetTester tester, Finder target) async {
  final scrollable = find.descendant(
    of: find.byKey(const ValueKey('graph-detail-panel')),
    matching: find.byType(Scrollable),
  );
  await tester.scrollUntilVisible(target, 120, scrollable: scrollable);
  await tester.pumpAndSettle();
}

MockClient _client(_RenameState state) {
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
          nodes: [graphObjectJson(id: 'task-home', title: 'Home')],
        ),
      );
    }
    if (request.method == 'PATCH' &&
        request.url.path == '/objects/person-ada') {
      state.genericPatches += 1;
      return jsonUtf8Response({'detail': 'generic patch'}, statusCode: 500);
    }
    if (request.method == 'PATCH' &&
        request.url.path == '/graph/people/person-ada') {
      state.renameCalls += 1;
      state.renamePaths.add(request.url.path);
      final hold = state.holdRename;
      if (hold != null) {
        await hold.future;
      }
      if (state.failNextRename) {
        state.failNextRename = false;
        return jsonUtf8Response({'detail': 'Имя отклонено'}, statusCode: 422);
      }
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      state.title = (body['title'] as String).trim();
      return jsonUtf8Response(
        graphObjectJson(id: 'person-ada', title: state.title, kind: 'person'),
      );
    }
    if (request.method == 'DELETE' &&
        request.url.path == '/tasks/task-ask/actors/edge-requested_by') {
      return jsonUtf8Response({
        'edge': _edge(
          'edge-requested_by',
          'task-ask',
          'requested_by',
          state: 'rejected',
        ),
        'created': false,
        'changed': true,
      });
    }
    if (request.url.path == '/objects/person-ada/neighbors') {
      return jsonUtf8Response({
        'object_id': 'person-ada',
        'neighbors': [
          {
            'object': graphObjectJson(
              id: 'task-off',
              title: 'Off canvas',
              kind: 'task',
            ),
            'edge': _edge('edge-off-actor', 'task-off', 'requested_by'),
            'direction': 'in',
          },
          {
            'object': graphObjectJson(
              id: 'note-ref',
              title: 'Reference',
              kind: 'note',
            ),
            'edge': _edge(
              'edge-ref',
              'person-ada',
              'references',
              targetId: 'note-ref',
            ),
            'direction': 'out',
          },
        ],
      });
    }
    if (request.url.path == '/graph/people-workspace') {
      final root = request.url.queryParameters['root_id'];
      state.peopleWorkspaceGets += 1;
      state.peopleWorkspaceInFlight += 1;
      final hold = state.holdPeopleWorkspace;
      Map<String, dynamic>? frozen;
      if (hold != null) {
        state.holdPeopleWorkspace = null;
        frozen = jsonDecode(
          jsonEncode(_workspace(state, root)),
        ) as Map<String, dynamic>;
        await hold.future;
      }
      state.peopleWorkspaceInFlight -= 1;
      return jsonUtf8Response(frozen ?? _workspace(state, root));
    }
    return http.Response('{}', 404);
  });
}

Map<String, dynamic> _edge(
  String id,
  String sourceId,
  String type, {
  String targetId = 'person-ada',
  String state = 'confirmed',
}) {
  return {
    'id': id,
    'source_id': sourceId,
    'target_id': targetId,
    'type': type,
    'origin': 'user',
    'state': state,
    'metadata': <String, dynamic>{},
    'created_at': '2026-09-29T00:00:00Z',
    'updated_at': '2026-09-29T00:00:00Z',
  };
}

Map<String, dynamic> _involvement(
  String edgeId,
  String taskId,
  String title,
  String role,
) {
  return {
    'edge_id': edgeId,
    'task_id': taskId,
    'title': title,
    'status': 'open',
    'role': role,
    'edge_state': 'confirmed',
    'edge_origin': 'user',
  };
}

Map<String, dynamic> _workspace(_RenameState state, String? root) {
  final windowIndex = int.tryParse(root == null ? '0' : '0') ?? 0;
  return {
    'root_id': root,
    'seed_ids': root == null ? ['person-ada', 'person-bob'] : ['person-ada'],
    'nodes': [
      graphObjectJson(id: 'person-ada', title: state.title, kind: 'person'),
      if (root == null)
        graphObjectJson(id: 'person-bob', title: 'Bob', kind: 'person'),
      graphObjectJson(id: 'task-ask', title: 'Ask', kind: 'task'),
      graphObjectJson(id: 'task-delegate', title: 'Delegate', kind: 'task'),
      graphObjectJson(id: 'task-wait', title: 'Wait', kind: 'task'),
      graphObjectJson(id: 'task-join', title: 'Join', kind: 'task'),
      graphObjectJson(id: 'note-1', title: 'Notes', kind: 'note'),
    ],
    'edges': [
      _edge('edge-requested_by', 'task-ask', 'requested_by'),
      _edge('edge-delegated_to', 'task-delegate', 'delegated_to'),
      _edge('edge-waiting_on', 'task-wait', 'waiting_on'),
      _edge('edge-involves', 'task-join', 'involves'),
      _edge('edge-related', 'person-ada', 'related_to', targetId: 'note-1'),
    ],
    'truncated': false,
    'window_index': windowIndex,
    'window_count': root == null ? 2 : 1,
    'has_previous_window': false,
    'has_next_window': root == null,
    'people': [
      {
        'person_id': 'person-ada',
        'title': state.title,
        'salience_score': 1,
        'identities': const [],
        'routes': const [],
        'identity_conflict': false,
        'open_task_count': 4,
        'recent_communication_count': 0,
        'task_involvement': [
          _involvement('edge-requested_by', 'task-ask', 'Ask', 'requested_by'),
          _involvement(
            'edge-delegated_to',
            'task-delegate',
            'Delegate',
            'delegated_to',
          ),
          _involvement('edge-waiting_on', 'task-wait', 'Wait', 'waiting_on'),
          _involvement('edge-involves', 'task-join', 'Join', 'involves'),
        ],
        'recent_communications': const [],
        'salience': null,
        'consolidations': const [],
      },
      if (root == null)
        {
          'person_id': 'person-bob',
          'title': 'Bob',
          'salience_score': 0,
          'identities': const [],
          'routes': const [],
          'identity_conflict': false,
          'open_task_count': 0,
          'recent_communication_count': 0,
          'task_involvement': const [],
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
