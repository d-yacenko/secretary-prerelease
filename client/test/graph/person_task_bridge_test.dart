import 'dart:async';
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
    expect(find.byKey(const ValueKey('person-task-tile-edge-ask')), findsOneWidget);
    expect(find.byKey(const ValueKey('person-task-tile-edge-wait')), findsOneWidget);
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

  testWidgets('duplicate task titles show confirmed parents and a unique title stays plain', (
    tester,
  ) async {
    final state = _BridgeState();
    await _open(tester, _client(state));
    await _reveal(tester, find.byKey(const ValueKey('person-task-link')));
    await tester.tap(find.byKey(const ValueKey('person-task-link')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('person-task-search')), 'dup');
    await tester.pumpAndSettle();

    expect(state.profilePaths, [
      '/tasks/course-work/profile',
      '/tasks/course-academic/profile',
      '/tasks/course-orphan/profile',
      '/tasks/course-direction/profile',
    ]);
    expect(state.profilePaths, isNot(contains('/tasks/course-unique/profile')));
    expect(find.text('Обучение (Основная работа)'), findsOneWidget);
    expect(find.text('обучение (Академическая деятельность)'), findsOneWidget);
    expect(find.text('  Обучение (без родителя)'), findsOneWidget);
    expect(find.text('Обучение (Направление)'), findsOneWidget);
    expect(find.text('Уникальная'), findsOneWidget);
    expect(find.textContaining('Уникальная ('), findsNothing);

    await tester.tap(find.byKey(const ValueKey('person-task-role-involves')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('person-task-option-course-direction')));
    await tester.pumpAndSettle();
    expect(
      tester.widget<FilledButton>(find.byKey(const ValueKey('person-task-add'))).onPressed,
      isNotNull,
    );
  });

  testWidgets('a delayed actor removal blocks other task-role mutations', (tester) async {
    final state = _BridgeState()..holdActorMutation = Completer<void>();
    await _open(tester, _client(state));
    await _reveal(tester, find.byKey(const ValueKey('person-task-remove-edge-ask')));
    await tester.tap(find.byKey(const ValueKey('person-task-remove-edge-ask')));
    await tester.pump();
    await tester.pump();

    expect(find.byKey(const ValueKey('person-task-mutation-pending')), findsOneWidget);
    expect(find.byKey(const ValueKey('person-task-tile-edge-ask')), findsOneWidget);
    expect(find.byKey(const ValueKey('person-task-tile-edge-wait')), findsOneWidget);
    expect(
      tester.widget<IconButton>(find.byKey(const ValueKey('person-task-remove-edge-wait'))).onPressed,
      isNull,
    );
    expect(
      tester.widget<IconButton>(find.byKey(const ValueKey('person-task-confirm-edge-join'))).onPressed,
      isNull,
    );
    expect(
      tester.widget<TextButton>(find.byKey(const ValueKey('person-task-link'))).onPressed,
      isNull,
    );

    state.holdActorMutation!.complete();
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-task-mutation-pending')), findsNothing);
    expect(find.byKey(const ValueKey('person-task-tile-edge-ask')), findsNothing);
    expect(find.byKey(const ValueKey('person-task-tile-edge-wait')), findsOneWidget);
    expect(find.byKey(const ValueKey('person-task-tile-edge-join')), findsOneWidget);
  });

  testWidgets('a failed actor removal stays visible and can be retried', (tester) async {
    final state = _BridgeState()..failNextActorMutation = true;
    await _open(tester, _client(state));
    await _reveal(tester, find.byKey(const ValueKey('person-task-remove-edge-ask')));
    await tester.tap(find.byKey(const ValueKey('person-task-remove-edge-ask')));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('person-task-mutation-error')), findsOneWidget);
    expect(find.text('Не удалось изменить участие'), findsOneWidget);
    expect(find.byKey(const ValueKey('person-task-tile-edge-ask')), findsOneWidget);
    expect(find.byKey(const ValueKey('person-task-tile-edge-wait')), findsOneWidget);
    expect(
      tester.widget<IconButton>(find.byKey(const ValueKey('person-task-remove-edge-ask'))).onPressed,
      isNotNull,
    );

    await tester.tap(find.byKey(const ValueKey('person-task-remove-edge-ask')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-task-mutation-error')), findsNothing);
    expect(find.byKey(const ValueKey('person-task-tile-edge-ask')), findsNothing);
    expect(find.byKey(const ValueKey('person-task-tile-edge-wait')), findsOneWidget);
  });

  testWidgets('a successful add is visible before people workspace reconciliation', (
    tester,
  ) async {
    final state = _BridgeState();
    await _open(tester, _client(state));
    final before = state.peopleWorkspaceGets;
    await _reveal(tester, find.byKey(const ValueKey('person-task-link')));
    await tester.tap(find.byKey(const ValueKey('person-task-link')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('person-task-role-waiting_on')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('person-task-search')), 'Ship');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('person-task-option-task-ship')));
    await tester.pumpAndSettle();
    final hold = Completer<void>();
    state.holdPeopleWorkspace = hold;
    await tester.tap(find.byKey(const ValueKey('person-task-add')));
    await tester.pump();
    await tester.pump();

    expect(find.byKey(const ValueKey('person-task-mutation-pending')), findsNothing);
    expect(find.byKey(const ValueKey('person-task-tile-edge-ship')), findsOneWidget);
    expect(find.byKey(const ValueKey('person-task-tile-edge-ask')), findsOneWidget);
    expect(find.byKey(const ValueKey('person-task-tile-edge-wait')), findsOneWidget);
    expect(state.peopleWorkspaceGets, before + 1);
    expect(state.maxPeopleWorkspaceInFlight, 1);

    hold.complete();
    await tester.pumpAndSettle();
    expect(state.peopleWorkspaceGets, before + 1);
    expect(find.byKey(const ValueKey('person-task-tile-edge-ship')), findsOneWidget);
    expect(find.byKey(const ValueKey('person-task-tile-edge-wait')), findsOneWidget);
  });

  testWidgets('a successful remove is visible before people workspace reconciliation', (
    tester,
  ) async {
    final state = _BridgeState();
    await _open(tester, _client(state));
    final before = state.peopleWorkspaceGets;
    final hold = Completer<void>();
    state.holdPeopleWorkspace = hold;
    await _reveal(tester, find.byKey(const ValueKey('person-task-remove-edge-ask')));
    await tester.tap(find.byKey(const ValueKey('person-task-remove-edge-ask')));
    await tester.pump();
    await tester.pump();

    expect(find.byKey(const ValueKey('person-task-mutation-pending')), findsNothing);
    expect(find.byKey(const ValueKey('person-task-tile-edge-ask')), findsNothing);
    expect(find.byKey(const ValueKey('person-task-tile-edge-wait')), findsOneWidget);
    expect(state.peopleWorkspaceGets, before + 1);
    expect(state.maxPeopleWorkspaceInFlight, 1);

    hold.complete();
    await tester.pumpAndSettle();
    expect(state.peopleWorkspaceGets, before + 1);
    expect(find.byKey(const ValueKey('person-task-tile-edge-ask')), findsNothing);
    expect(find.byKey(const ValueKey('person-task-tile-edge-wait')), findsOneWidget);
  });

  testWidgets('proposal confirm applies before people workspace reconciliation', (
    tester,
  ) async {
    final state = _BridgeState();
    await _open(tester, _client(state));
    final hold = Completer<void>();
    state.holdPeopleWorkspace = hold;
    await _reveal(tester, find.byKey(const ValueKey('person-task-confirm-edge-join')));
    await tester.tap(find.byKey(const ValueKey('person-task-confirm-edge-join')));
    await tester.pump();
    await tester.pump();
    expect(find.textContaining('Предложено секретарём'), findsNothing);
    expect(find.byKey(const ValueKey('person-task-remove-edge-join')), findsOneWidget);
    expect(find.byKey(const ValueKey('person-task-mutation-pending')), findsNothing);
    hold.complete();
    await tester.pumpAndSettle();
  });

  testWidgets('proposal reject removes the row before reconciliation', (tester) async {
    final state = _BridgeState();
    await _open(tester, _client(state));
    final hold = Completer<void>();
    state.holdPeopleWorkspace = hold;
    await _reveal(tester, find.byKey(const ValueKey('person-task-reject-edge-join')));
    await tester.tap(find.byKey(const ValueKey('person-task-reject-edge-join')));
    await tester.pump();
    await tester.pump();
    expect(find.byKey(const ValueKey('person-task-tile-edge-join')), findsNothing);
    expect(find.byKey(const ValueKey('person-task-tile-edge-ask')), findsOneWidget);
    expect(find.byKey(const ValueKey('person-task-mutation-pending')), findsNothing);
    hold.complete();
    await tester.pumpAndSettle();
  });

  testWidgets('an older people workspace response cannot restore a newer removal', (
    tester,
  ) async {
    final state = _BridgeState();
    await _open(tester, _client(state));
    final before = state.peopleWorkspaceGets;
    final first = Completer<void>();
    final second = Completer<void>();
    state.holdPeopleWorkspace = first;
    await _reveal(tester, find.byKey(const ValueKey('person-task-remove-edge-ask')));
    await tester.tap(find.byKey(const ValueKey('person-task-remove-edge-ask')));
    await tester.pump();
    await tester.pump();
    expect(find.byKey(const ValueKey('person-task-tile-edge-ask')), findsNothing);

    state.holdPeopleWorkspace = second;
    await tester.tap(find.byKey(const ValueKey('person-task-remove-edge-wait')));
    await tester.pump();
    await tester.pump();
    expect(find.byKey(const ValueKey('person-task-tile-edge-wait')), findsNothing);
    expect(state.peopleWorkspaceGets, before + 1);
    expect(state.maxPeopleWorkspaceInFlight, 1);

    first.complete();
    await tester.pump();
    await tester.pump();
    expect(find.byKey(const ValueKey('person-task-tile-edge-ask')), findsNothing);
    expect(find.byKey(const ValueKey('person-task-tile-edge-wait')), findsNothing);
    expect(state.peopleWorkspaceGets, before + 2);
    expect(state.maxPeopleWorkspaceInFlight, 1);

    second.complete();
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-task-tile-edge-wait')), findsNothing);
    expect(find.byKey(const ValueKey('person-task-tile-edge-join')), findsOneWidget);
    expect(state.maxPeopleWorkspaceInFlight, 1);
  });

  testWidgets('a failed people workspace refresh keeps the saved removal', (tester) async {
    final state = _BridgeState();
    await _open(tester, _client(state));
    state.failNextPeopleWorkspace = true;
    await _reveal(tester, find.byKey(const ValueKey('person-task-remove-edge-ask')));
    await tester.tap(find.byKey(const ValueKey('person-task-remove-edge-ask')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-task-tile-edge-ask')), findsNothing);
    expect(find.byKey(const ValueKey('person-task-tile-edge-wait')), findsOneWidget);
    expect(find.byKey(const ValueKey('person-task-mutation-error')), findsNothing);
    expect(find.text('Изменение сохранено, обзор обновится позже'), findsOneWidget);
    expect(
      tester.widget<IconButton>(find.byKey(const ValueKey('person-task-remove-edge-wait'))).onPressed,
      isNotNull,
    );
  });

  testWidgets('leaving the person ignores a late people workspace response', (tester) async {
    final state = _BridgeState();
    final harness = await _open(tester, _client(state));
    final hold = Completer<void>();
    state.holdPeopleWorkspace = hold;
    await _reveal(tester, find.byKey(const ValueKey('person-task-remove-edge-ask')));
    await tester.tap(find.byKey(const ValueKey('person-task-remove-edge-ask')));
    await tester.pump();
    await tester.pump();
    expect(find.byKey(const ValueKey('person-task-tile-edge-ask')), findsNothing);

    await _reveal(tester, find.text('Join'));
    await tester.tap(find.text('Join'));
    await tester.pumpAndSettle();
    expect(harness.graph.mode, GraphWorkspaceMode.tasks);
    expect(harness.graph.rootId, 'task-join');

    hold.complete();
    await tester.pumpAndSettle();
    expect(harness.graph.mode, GraphWorkspaceMode.tasks);
    expect(harness.graph.rootId, 'task-join');
    expect(find.byKey(const ValueKey('person-task-tile-edge-wait')), findsNothing);
  });

  testWidgets('a pending reconciliation follows the latest person after a switch', (
    tester,
  ) async {
    final state = _BridgeState();
    final harness = await _open(tester, _client(state));
    final holdA = Completer<void>();
    state.holdPeopleWorkspace = holdA;
    await _reveal(tester, find.byKey(const ValueKey('person-task-remove-edge-ask')));
    await tester.tap(find.byKey(const ValueKey('person-task-remove-edge-ask')));
    await tester.pump();
    await tester.pump();
    expect(find.byKey(const ValueKey('person-task-tile-edge-ask')), findsNothing);
    expect(state.peopleWorkspaceInFlight, 1);

    await harness.graph.reRoot('person-bob');
    await tester.pumpAndSettle();
    expect(harness.graph.rootId, 'person-bob');
    expect(find.text('Bob'), findsWidgets);
    expect(find.byKey(const ValueKey('person-task-tile-edge-bob-ship')), findsOneWidget);
    expect(state.peopleWorkspaceInFlight, 1);
    state.maxPeopleWorkspaceInFlight = state.peopleWorkspaceInFlight;

    final bobGetsBeforeMutation = state.peopleWorkspaceRoots
        .where((root) => root == 'person-bob')
        .length;
    await _reveal(tester, find.byKey(const ValueKey('person-task-remove-edge-bob-ship')));
    await tester.tap(find.byKey(const ValueKey('person-task-remove-edge-bob-ship')));
    await tester.pump();
    await tester.pump();
    expect(find.byKey(const ValueKey('person-task-tile-edge-bob-ship')), findsNothing);
    expect(find.byKey(const ValueKey('person-task-tile-edge-ask')), findsNothing);
    expect(state.peopleWorkspaceInFlight, 1);
    expect(state.maxPeopleWorkspaceInFlight, 1);
    expect(
      state.peopleWorkspaceRoots.where((root) => root == 'person-bob').length,
      bobGetsBeforeMutation,
    );

    holdA.complete();
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-task-tile-edge-bob-ship')), findsNothing);
    expect(find.byKey(const ValueKey('person-task-tile-edge-ask')), findsNothing);
    expect(
      state.peopleWorkspaceRoots.where((root) => root == 'person-bob').length,
      bobGetsBeforeMutation + 1,
    );
    expect(state.maxPeopleWorkspaceInFlight, 1);
  });

  testWidgets('switching person without a newer mutation skips follow-up reconciliation', (
    tester,
  ) async {
    final state = _BridgeState();
    final harness = await _open(tester, _client(state));
    final holdA = Completer<void>();
    state.holdPeopleWorkspace = holdA;
    await _reveal(tester, find.byKey(const ValueKey('person-task-remove-edge-ask')));
    await tester.tap(find.byKey(const ValueKey('person-task-remove-edge-ask')));
    await tester.pump();
    await tester.pump();

    await harness.graph.reRoot('person-bob');
    await tester.pumpAndSettle();
    final bobGets = state.peopleWorkspaceRoots.where((root) => root == 'person-bob').length;
    final totalGets = state.peopleWorkspaceGets;

    holdA.complete();
    await tester.pumpAndSettle();
    expect(state.peopleWorkspaceGets, totalGets);
    expect(
      state.peopleWorkspaceRoots.where((root) => root == 'person-bob').length,
      bobGets,
    );
    expect(find.byKey(const ValueKey('person-task-tile-edge-bob-ship')), findsOneWidget);
  });

  testWidgets('re-rooting adopts controller person truth without a duplicate detail fetch', (
    tester,
  ) async {
    final state = _BridgeState();
    final harness = await _open(tester, _client(state));
    final bobGetsBefore = state.peopleWorkspaceRoots
        .where((root) => root == 'person-bob')
        .length;

    await harness.graph.reRoot('person-bob');
    await tester.pumpAndSettle();

    expect(harness.graph.rootId, 'person-bob');
    expect(find.byKey(const ValueKey('person-task-tile-edge-bob-ship')), findsOneWidget);
    expect(
      state.peopleWorkspaceRoots.where((root) => root == 'person-bob').length,
      bobGetsBefore + 1,
    );
  });

  testWidgets('non-root person selection still fetches rooted person truth', (tester) async {
    final state = _BridgeState();
    await _openOverview(tester, _client(state));
    final before = state.peopleWorkspaceGets;

    await tester.tap(find.text('Ada').first);
    await tester.pumpAndSettle();

    expect(state.peopleWorkspaceGets, greaterThan(before));
    expect(state.peopleWorkspaceRoots, contains('person-ada'));
    expect(find.byKey(const ValueKey('person-task-tile-edge-ask')), findsOneWidget);
  });

  testWidgets('a delayed detail load cannot restore rows after a newer actor mutation', (
    tester,
  ) async {
    final state = _BridgeState();
    final harness = await _openOverview(tester, _client(state));
    final holdDetail = Completer<void>();
    state.holdPeopleWorkspace = holdDetail;

    await tester.tap(find.text('Bob').first);
    await tester.pump();
    await tester.pump();
    expect(state.peopleWorkspaceInFlight, 1);

    await harness.graph.reRoot('person-bob');
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-task-tile-edge-bob-ship')), findsOneWidget);

    await _reveal(tester, find.byKey(const ValueKey('person-task-remove-edge-bob-ship')));
    await tester.tap(find.byKey(const ValueKey('person-task-remove-edge-bob-ship')));
    await tester.pump();
    await tester.pump();
    expect(find.byKey(const ValueKey('person-task-tile-edge-bob-ship')), findsNothing);

    holdDetail.complete();
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-task-tile-edge-bob-ship')), findsNothing);
    expect(harness.graph.rootId, 'person-bob');
  });

  testWidgets('a delayed detail load for another person cannot alter the current card', (
    tester,
  ) async {
    final state = _BridgeState();
    final harness = await _openOverview(tester, _client(state));
    final holdAda = Completer<void>();
    state.holdPeopleWorkspace = holdAda;

    await tester.tap(find.text('Ada').first);
    await tester.pump();
    await tester.pump();
    expect(state.peopleWorkspaceInFlight, 1);

    await harness.graph.reRoot('person-bob');
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-task-tile-edge-bob-ship')), findsOneWidget);
    expect(find.byKey(const ValueKey('person-task-tile-edge-ask')), findsNothing);

    holdAda.complete();
    await tester.pumpAndSettle();
    expect(harness.graph.rootId, 'person-bob');
    expect(find.byKey(const ValueKey('person-task-tile-edge-bob-ship')), findsOneWidget);
    expect(find.byKey(const ValueKey('person-task-tile-edge-ask')), findsNothing);
  });

  testWidgets('local actor patch keeps the authoritative linked-task count', (tester) async {
    final state = _BridgeState()
      ..linkedTaskCountOverride = 9
      ..rebuildPeopleWorkspaceAfterHold = true;
    await _open(tester, _client(state));
    expect(find.text('Связанные задачи · 9'), findsWidgets);

    final hold = Completer<void>();
    state.holdPeopleWorkspace = hold;
    await _reveal(tester, find.byKey(const ValueKey('person-task-remove-edge-ask')));
    await tester.tap(find.byKey(const ValueKey('person-task-remove-edge-ask')));
    await tester.pump();
    await tester.pump();
    expect(find.byKey(const ValueKey('person-task-tile-edge-ask')), findsNothing);
    expect(find.text('Связанные задачи · 9'), findsWidgets);
    expect(find.text('Связанные задачи · 2'), findsNothing);
    expect(find.text('Связанные задачи · 1'), findsNothing);

    state.linkedTaskCountOverride = 8;
    hold.complete();
    await tester.pumpAndSettle();
    expect(find.text('Связанные задачи · 8'), findsWidgets);
    expect(find.byKey(const ValueKey('person-task-tile-edge-wait')), findsOneWidget);
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
  final profilePaths = <String>[];
  Completer<void>? holdActorMutation;
  Completer<void>? holdPeopleWorkspace;
  bool failNextActorMutation = false;
  bool failNextPeopleWorkspace = false;
  int peopleWorkspaceGets = 0;
  int peopleWorkspaceInFlight = 0;
  int maxPeopleWorkspaceInFlight = 0;
  final peopleWorkspaceRoots = <String?>[];
  int? linkedTaskCountOverride;
  bool rebuildPeopleWorkspaceAfterHold = false;
  final rows = <Map<String, dynamic>>[
    _row('edge-ask', 'task-ask', 'Ask', 'requested_by'),
    _row('edge-wait', 'task-ask', 'Ask', 'waiting_on'),
    _row('edge-join', 'task-join', 'Join', 'involves', state: 'proposed', origin: 'agent'),
  ];
  final bobRows = <Map<String, dynamic>>[
    _row('edge-bob-ship', 'task-ship', 'Ship report', 'involves'),
  ];

  List<Map<String, dynamic>> rowsFor(String? root) {
    return root == 'person-bob' ? bobRows : rows;
  }

  int linkedTaskCount(String? root) {
    if (root == 'person-bob') {
      return bobRows.map((row) => row['task_id']).toSet().length;
    }
    return linkedTaskCountOverride ??
        rows.map((row) => row['task_id']).toSet().length;
  }
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

Future<GraphTestHarness> _openOverview(WidgetTester tester, MockClient client) async {
  tester.view.physicalSize = const Size(1280, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final harness = GraphTestHarness(client);
  harness.configure();
  await openGraph(tester, harness);
  await tester.tap(find.text('Люди'));
  await tester.pumpAndSettle();
  return harness;
}

Future<GraphTestHarness> _open(WidgetTester tester, MockClient client) async {
  final harness = await _openOverview(tester, client);
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
      if (request.url.queryParameters['q'] == 'dup') {
        return jsonUtf8Response([
          graphObjectJson(id: 'course-work', title: 'Обучение', kind: 'task', status: 'open'),
          graphObjectJson(id: 'course-academic', title: 'обучение', kind: 'task', status: 'open'),
          graphObjectJson(id: 'course-orphan', title: '  Обучение', kind: 'task', status: 'open'),
          graphObjectJson(
            id: 'course-direction',
            title: 'Обучение',
            kind: 'task',
            status: 'open',
            completionMode: 'ongoing',
          ),
          graphObjectJson(id: 'course-unique', title: 'Уникальная', kind: 'task', status: 'open'),
        ]);
      }
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
      final personId = body['person_id'] as String? ?? 'person-ada';
      final list = personId == 'person-bob' ? state.bobRows : state.rows;
      state.calls.add('POST ${request.url.path} $role');
      final existing = list.where((row) => row['task_id'] == taskId && row['role'] == role);
      final created = existing.isEmpty;
      final edgeId = created
          ? (taskId == 'task-ship'
              ? (personId == 'person-bob' ? 'edge-bob-ship' : 'edge-ship')
              : 'edge-$taskId-$role')
          : existing.first['edge_id'] as String;
      if (created) {
        final title = taskId == 'task-ship' ? 'Ship report' : 'Ask';
        list.add(_row(edgeId, taskId, title, role));
      }
      return jsonUtf8Response({
        'edge': _edge(edgeId, taskId, role, personId: personId),
        'created': created,
        'changed': created,
      });
    }
    if (request.url.path == '/tasks/course-work/profile') {
      state.profilePaths.add(request.url.path);
      return jsonUtf8Response(_profile('course-work', _parent('main', 'Основная работа', 'confirmed')));
    }
    if (request.url.path == '/tasks/course-academic/profile') {
      state.profilePaths.add(request.url.path);
      return jsonUtf8Response(
        _profile('course-academic', _parent('study', 'Академическая деятельность', 'confirmed')),
      );
    }
    if (request.url.path == '/tasks/course-orphan/profile') {
      state.profilePaths.add(request.url.path);
      return jsonUtf8Response(_profile('course-orphan', _parent('hidden', 'Нельзя', 'proposed')));
    }
    if (request.url.path == '/tasks/course-direction/profile') {
      state.profilePaths.add(request.url.path);
      return jsonUtf8Response(
        _profile('course-direction', _parent('direction', 'Направление', 'confirmed')),
      );
    }
    if (request.method == 'DELETE' && request.url.path.startsWith('/tasks/') && request.url.path.contains('/actors/')) {
      if (state.failNextActorMutation) {
        state.failNextActorMutation = false;
        state.calls.add('DELETE ${request.url.path} failed');
        return jsonUtf8Response(
          {'detail': 'Не удалось изменить участие'},
          statusCode: 500,
        );
      }
      final hold = state.holdActorMutation;
      if (hold != null) {
        await hold.future;
      }
      state.calls.add('DELETE ${request.url.path}');
      final edgeId = request.url.path.split('/').last;
      Map<String, dynamic>? row;
      var personId = 'person-ada';
      for (final item in state.rows) {
        if (item['edge_id'] == edgeId) {
          row = item;
          break;
        }
      }
      if (row == null) {
        for (final item in state.bobRows) {
          if (item['edge_id'] == edgeId) {
            row = item;
            personId = 'person-bob';
            break;
          }
        }
      }
      state.rows.removeWhere((item) => item['edge_id'] == edgeId);
      state.bobRows.removeWhere((item) => item['edge_id'] == edgeId);
      return jsonUtf8Response({
        'edge': _edge(
          edgeId,
          row?['task_id'] as String? ?? 'task-ask',
          row?['role'] as String? ?? 'requested_by',
          state: 'rejected',
          personId: personId,
        ),
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
      state.peopleWorkspaceGets += 1;
      state.peopleWorkspaceRoots.add(root);
      state.peopleWorkspaceInFlight += 1;
      if (state.peopleWorkspaceInFlight > state.maxPeopleWorkspaceInFlight) {
        state.maxPeopleWorkspaceInFlight = state.peopleWorkspaceInFlight;
      }
      if (state.failNextPeopleWorkspace) {
        state.failNextPeopleWorkspace = false;
        state.peopleWorkspaceInFlight -= 1;
        return jsonUtf8Response({'detail': 'later'}, statusCode: 500);
      }
      final hold = state.holdPeopleWorkspace;
      if (hold != null) {
        state.holdPeopleWorkspace = null;
        final body = state.rebuildPeopleWorkspaceAfterHold
            ? null
            : jsonDecode(jsonEncode(_workspace(state, root))) as Map<String, dynamic>;
        await hold.future;
        state.peopleWorkspaceInFlight -= 1;
        return jsonUtf8Response(
          body ?? _workspace(state, root),
        );
      }
      state.peopleWorkspaceInFlight -= 1;
      return jsonUtf8Response(_workspace(state, root));
    }
    return http.Response('{}', 404);
  });
}

Map<String, dynamic> _edge(
  String id,
  String taskId,
  String role, {
  String state = 'confirmed',
  String personId = 'person-ada',
}) {
  return {
    'id': id,
    'source_id': taskId,
    'target_id': personId,
    'type': role,
    'origin': 'user',
    'state': state,
    'metadata': <String, dynamic>{},
    'created_at': '2026-09-29T00:00:00Z',
    'updated_at': '2026-09-29T00:00:00Z',
  };
}

Map<String, dynamic> _personJson(
  String personId,
  String title,
  List<Map<String, dynamic>> involvement,
  int openTaskCount, {
  required bool includeInvolvement,
}) {
  return {
    'person_id': personId,
    'title': title,
    'salience_score': 1,
    'identities': const [],
    'routes': const [],
    'identity_conflict': false,
    'open_task_count': openTaskCount,
    'recent_communication_count': 0,
    'task_involvement': includeInvolvement ? involvement : <Map<String, dynamic>>[],
    'recent_communications': const [],
    'salience': null,
    'consolidations': const [],
  };
}

Map<String, dynamic> _workspace(_BridgeState state, String? root) {
  if (root == 'person-bob') {
    return {
      'root_id': root,
      'seed_ids': ['person-bob'],
      'nodes': [graphObjectJson(id: 'person-bob', title: 'Bob', kind: 'person')],
      'edges': [],
      'truncated': false,
      'people': [
        _personJson(
          'person-bob',
          'Bob',
          state.bobRows,
          state.linkedTaskCount(root),
          includeInvolvement: true,
        ),
      ],
      'promotion_candidates': <Map<String, dynamic>>[],
      'promotion_candidates_truncated': false,
      'promotion_suppressions': <Map<String, dynamic>>[],
    };
  }
  return {
    'root_id': root,
    'seed_ids': root == null ? ['person-ada', 'person-bob'] : ['person-ada'],
    'nodes': [
      graphObjectJson(id: 'person-ada', title: 'Ada', kind: 'person'),
      if (root == null) graphObjectJson(id: 'person-bob', title: 'Bob', kind: 'person'),
    ],
    'edges': [],
    'truncated': false,
    'people': [
      _personJson(
        'person-ada',
        'Ada',
        state.rows,
        state.linkedTaskCount('person-ada'),
        includeInvolvement: root != null,
      ),
      if (root == null)
        _personJson(
          'person-bob',
          'Bob',
          state.bobRows,
          state.linkedTaskCount('person-bob'),
          includeInvolvement: false,
        ),
    ],
    'promotion_candidates': <Map<String, dynamic>>[],
    'promotion_candidates_truncated': false,
    'promotion_suppressions': <Map<String, dynamic>>[],
  };
}

Map<String, dynamic> _profile(String taskId, Map<String, dynamic>? parent) {
  return {
    'task': graphObjectJson(id: taskId, title: 'Обучение'),
    'requested_by': const [],
    'delegated_to': const [],
    'waiting_on': const [],
    'involves': const [],
    'depends_on': const [],
    'dependent_tasks': const [],
    if (parent != null) 'parent_task': parent,
    'child_tasks': const [],
    'evidence': const [],
  };
}

Map<String, dynamic> _parent(String id, String title, String state) {
  return {
    'edge_id': 'edge-$id',
    'object_id': id,
    'title': title,
    'kind': 'task',
    'edge_state': state,
    'edge_origin': 'user',
  };
}
