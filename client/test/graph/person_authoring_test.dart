import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/graph/person_context_visual.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets('overview selection is usable before rooted hydration', (
    tester,
  ) async {
    final gate = Completer<void>();
    final harness = await _openPeople(
      tester,
      rootedGate: {'person-a': gate},
      people: [
        _person('person-a', 'Ада', role: 'директор', context: 'Arenadata'),
      ],
    );
    await tester.tap(find.byKey(const Key('graph_node_person-a')));
    await tester.pump();

    expect(find.byKey(const ValueKey('person-detail-loading')), findsNothing);
    expect(find.text('Ада'), findsWidgets);
    expect(find.byKey(const ValueKey('person-rename')), findsOneWidget);
    expect(find.byKey(const ValueKey('person-role-add')), findsOneWidget);
    expect(find.text('директор · Arenadata'), findsWidgets);
    expect(
      find.byKey(const ValueKey('person-detail-task-loading')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('person-detail-flow-loading')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('person-detail-candidates-loading')),
      findsOneWidget,
    );
    expect(find.text('Нет участия в текущих задачах'), findsNothing);
    expect(find.text('Нет недавних коммуникаций'), findsNothing);
    expect(find.text('Нет кандидатов'), findsNothing);
    expect(find.text('Задача Ады'), findsNothing);
    expect(harness.graph.rootId, isNull);

    gate.complete();
    await tester.pumpAndSettle();
    expect(find.text('Ада'), findsWidgets);
    expect(find.text('Задача Ады'), findsOneWidget);
    expect(find.text('Письмо Ады'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('person-detail-task-loading')),
      findsNothing,
    );
    expect(find.byKey(const ValueKey('person-detail-loading')), findsNothing);
    expect(harness.graph.selectedObjectId, 'person-a');
  });

  testWidgets('rooted failure keeps the overview summary and offers retry', (
    tester,
  ) async {
    var failures = 1;
    final harness = await _openPeople(
      tester,
      people: [
        _person('person-a', 'Ада', role: 'директор', context: 'Arenadata'),
      ],
      failRooted: () {
        if (failures > 0) {
          failures -= 1;
          return true;
        }
        return false;
      },
    );
    await tester.tap(find.byKey(const Key('graph_node_person-a')));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('person-detail-loading')), findsNothing);
    expect(
      find.byKey(const ValueKey('person-detail-hydration-error')),
      findsOneWidget,
    );
    expect(
      find.text('Не удалось загрузить подробности · Повторить'),
      findsOneWidget,
    );
    expect(find.text('Ада'), findsWidgets);
    expect(find.byKey(const ValueKey('person-role-add')), findsOneWidget);
    expect(find.text('директор · Arenadata'), findsWidgets);
    expect(harness.graph.rootId, isNull);

    await tester.tap(
      find.byKey(const ValueKey('person-detail-hydration-retry')),
    );
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('person-detail-hydration-error')),
      findsNothing,
    );
    expect(find.text('Задача Ады'), findsOneWidget);
  });

  testWidgets('selecting another person rejects the stale rooted response', (
    tester,
  ) async {
    final gates = {
      'person-a': Completer<void>(),
      'person-b': Completer<void>(),
    };
    final harness = await _openPeople(
      tester,
      rootedGate: gates,
      people: [
        _person('person-a', 'Ада', role: 'директор'),
        _person('person-b', 'Борис', role: 'студент'),
      ],
    );
    harness.graph.selectObject('person-a');
    await tester.pump();
    harness.graph.selectObject('person-b');
    await tester.pump();
    gates['person-a']!.complete();
    await tester.pump();

    expect(find.text('Задача Ады'), findsNothing);
    expect(find.text('Борис'), findsWidgets);
    expect(find.text('студент'), findsWidgets);
    expect(find.byKey(const ValueKey('person-detail-loading')), findsNothing);

    gates['person-b']!.complete();
    await tester.pumpAndSettle();
    expect(find.text('Задача Бориса'), findsOneWidget);
    expect(find.text('Задача Ады'), findsNothing);
  });

  testWidgets(
    'role assign and retract patch locally without a workspace refresh',
    (tester) async {
      final rooted = <String>[];
      final overviews = <int>[0];
      await _openPeople(
        tester,
        people: [
          _person('person-a', 'Ада', role: 'директор', context: 'Arenadata'),
        ],
        onWorkspace: (root) {
          if (root == null) {
            overviews[0] += 1;
          } else {
            rooted.add(root);
          }
        },
      );
      await tester.tap(find.byKey(const Key('graph_node_person-a')));
      await tester.pumpAndSettle();
      expect(rooted, ['person-a']);
      final overviewCount = overviews[0];

      await tester.tap(find.byKey(const ValueKey('person-role-add')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const ValueKey('person-role-input')),
        'куратор',
      );
      await tester.enterText(
        find.byKey(const ValueKey('person-role-context')),
        'SRE Arenadata',
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('person-role-create')));
      await tester.pumpAndSettle();

      expect(find.text('куратор · SRE Arenadata'), findsWidgets);
      expect(find.text('директор · Arenadata'), findsWidgets);
      expect(
        find.descendant(
          of: find.byKey(const Key('graph_node_person-a')),
          matching: find.textContaining('куратор'),
        ),
        findsOneWidget,
      );
      expect(rooted, ['person-a']);
      expect(overviews[0], overviewCount);

      await tester.tap(
        find.byKey(const ValueKey('person-role-retract-role-директор')),
      );
      await tester.pumpAndSettle();
      expect(find.text('директор · Arenadata'), findsNothing);
      expect(find.text('куратор · SRE Arenadata'), findsWidgets);
      expect(rooted, ['person-a']);
      expect(overviews[0], overviewCount);
    },
  );

  testWidgets(
    'role failure keeps the previous list and a later rooted read cannot restore it',
    (tester) async {
      final gate = Completer<void>();
      var failAssign = true;
      final rooted = <String>[];
      await _openPeople(
        tester,
        rootedGate: {'person-a': gate},
        people: [
          _person('person-a', 'Ада', role: 'директор', context: 'Arenadata'),
        ],
        failAssign: () => failAssign,
        onWorkspace: (root) {
          if (root != null) {
            rooted.add(root);
          }
        },
      );
      await tester.tap(find.byKey(const Key('graph_node_person-a')));
      await tester.pump();

      await tester.tap(find.byKey(const ValueKey('person-role-add')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const ValueKey('person-role-input')),
        'куратор',
      );
      await tester.enterText(
        find.byKey(const ValueKey('person-role-context')),
        'SRE Arenadata',
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('person-role-create')));
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('person-role-error')), findsOneWidget);
      expect(find.textContaining('pool timeout'), findsOneWidget);
      expect(find.byKey(const ValueKey('person-role-input')), findsOneWidget);
      expect(find.text('директор · Arenadata'), findsWidgets);
      expect(find.text('куратор · SRE Arenadata'), findsNothing);

      failAssign = false;
      await tester.tap(find.byKey(const ValueKey('person-role-create')));
      await tester.pumpAndSettle();
      expect(find.text('куратор · SRE Arenadata'), findsWidgets);

      gate.complete();
      await tester.pumpAndSettle();
      expect(find.text('куратор · SRE Arenadata'), findsWidgets);
      expect(find.text('Письмо Ады'), findsOneWidget);
      expect(rooted, ['person-a']);
    },
  );

  testWidgets('two quick role changes do not start extra rooted reads', (
    tester,
  ) async {
    final rooted = <String>[];
    await _openPeople(
      tester,
      people: [_person('person-a', 'Ада')],
      onWorkspace: (root) {
        if (root != null) {
          rooted.add(root);
        }
      },
    );
    await tester.tap(find.byKey(const Key('graph_node_person-a')));
    await tester.pumpAndSettle();

    for (final role in ['куратор', 'оппонент']) {
      await tester.tap(find.byKey(const ValueKey('person-role-add')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const ValueKey('person-role-input')),
        role,
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('person-role-create')));
      await tester.pumpAndSettle();
    }

    expect(find.text('куратор'), findsWidgets);
    expect(find.text('оппонент'), findsWidgets);
    expect(rooted, ['person-a']);
  });

  testWidgets(
    'compact cards tint by context and keep selection conflict and bookmark',
    (tester) async {
      await _openPeople(
        tester,
        people: [
          _person('person-plain', 'Без контекста'),
          _person(
            'person-a',
            'Ада',
            role: 'SRE',
            context: 'SRE Arenadata',
            conflict: true,
          ),
          _person(
            'person-b',
            'Борис',
            role: 'директор',
            context: 'УЦ группы компании Arenadata',
          ),
        ],
        bookmarkId: 'person-a',
      );
      await tester.pumpAndSettle();

      final scheme = Theme.of(
        tester.element(find.byKey(const Key('graph_node_person-plain'))),
      ).colorScheme;
      Color cardColor(String id) {
        final materials = tester.widgetList<Material>(
          find.descendant(
            of: find.byKey(Key('graph_node_$id')),
            matching: find.byType(Material),
          ),
        );
        return materials.first.color!;
      }

      expect(cardColor('person-plain'), scheme.surface);
      final ada = personContextVisual([
        _assignment('person-a', 'SRE', 'SRE Arenadata'),
      ]);
      final boris = personContextVisual([
        _assignment('person-b', 'директор', 'УЦ группы компании Arenadata'),
      ]);
      expect(ada.familyKey, boris.familyKey);
      expect(ada.familyKey, 'arenadata');
      expect(cardColor('person-a'), contextCardColor(scheme, ada));
      expect(cardColor('person-b'), contextCardColor(scheme, boris));
      expect(cardColor('person-a'), isNot(cardColor('person-b')));
      expect(find.text('УЦ группы компании Arenadata'), findsNothing);
      expect(
        find.byKey(const Key('person-identity-conflict-person-a')),
        findsOneWidget,
      );
      expect(find.byKey(const Key('object_bookmark_tab')), findsWidgets);

      await tester.tap(find.byKey(const Key('graph_node_person-a')));
      await tester.pumpAndSettle();
      expect(cardColor('person-a'), scheme.primaryContainer);
      final selected = tester.widget<Container>(
        find
            .descendant(
              of: find.byKey(const Key('graph_node_person-a')),
              matching: find.byType(Container),
            )
            .first,
      );
      final border = selected.decoration! as BoxDecoration;
      expect(border.border!.top.width, 2);
      expect(border.border!.top.color, scheme.primary);
    },
  );

  testWidgets(
    'rapid selection keeps one rooted hydration and the latest person',
    (tester) async {
      final gates = {
        for (var index = 1; index <= 8; index++)
          'person-$index': Completer<void>(),
      };
      final flight = _Flight();
      final harness = await _openPeople(
        tester,
        rootedGate: gates,
        onRootedFlight: flight.record,
        people: [
          for (var index = 1; index <= 8; index++)
            _person('person-$index', 'П$index', role: 'р$index'),
        ],
      );
      for (var index = 1; index <= 8; index++) {
        harness.graph.selectObject('person-$index');
        await tester.pump();
      }

      expect(flight.started, ['person-1']);
      expect(flight.peak, 1);
      expect(flight.inFlight, 1);
      expect(harness.graph.selectedObjectId, 'person-8');
      expect(find.byKey(const ValueKey('person-detail-loading')), findsNothing);
    expect(find.text('П8'), findsWidgets);
    expect(find.text('р8'), findsWidgets);
      expect(find.byKey(const ValueKey('person-role-add')), findsOneWidget);

      gates['person-1']!.complete();
      await tester.pump();
      await tester.pump();

      expect(flight.started, ['person-1', 'person-8']);
      expect(flight.inFlight, 1);
      expect(flight.peak, 1);
    expect(find.text('Задача П1'), findsNothing);
    expect(find.text('П8'), findsWidgets);

      gates['person-8']!.complete();
      await tester.pumpAndSettle();
      expect(flight.inFlight, 0);
      expect(flight.started, ['person-1', 'person-8']);
    expect(find.text('Задача П8'), findsOneWidget);
    expect(find.text('Задача П1'), findsNothing);
    expect(find.text('Письмо П8'), findsOneWidget);
    },
  );

  testWidgets(
    'returning to the active person does not start a second hydration',
    (tester) async {
      final gates = {
        'person-a': Completer<void>(),
        'person-b': Completer<void>(),
      };
      final flight = _Flight();
      final harness = await _openPeople(
        tester,
        rootedGate: gates,
        onRootedFlight: flight.record,
        people: [
          _person('person-a', 'Ада', role: 'директор'),
          _person('person-b', 'Борис', role: 'студент'),
        ],
      );
      harness.graph.selectObject('person-a');
      await tester.pump();
      harness.graph.selectObject('person-b');
      await tester.pump();
      harness.graph.selectObject('person-a');
      await tester.pump();
      expect(flight.started, ['person-a']);
      expect(flight.inFlight, 1);

      gates['person-a']!.complete();
      await tester.pumpAndSettle();
      expect(flight.started, ['person-a']);
      expect(flight.inFlight, 0);
      expect(find.text('Задача Ады'), findsOneWidget);
      expect(find.text('Задача Бориса'), findsNothing);
    },
  );

  testWidgets('a stale hydration failure does not mark the newer person', (
    tester,
  ) async {
    final gates = {
      'person-a': Completer<void>(),
      'person-c': Completer<void>(),
    };
    final flight = _Flight();
    final harness = await _openPeople(
      tester,
      rootedGate: gates,
      onRootedFlight: flight.record,
      failRootIds: {'person-a'},
      people: [
        _person('person-a', 'Ада', role: 'директор'),
        _person('person-b', 'Борис', role: 'студент'),
        _person('person-c', 'Вера', role: 'куратор'),
      ],
    );
    harness.graph.selectObject('person-a');
    await tester.pump();
    harness.graph.selectObject('person-b');
    await tester.pump();
    harness.graph.selectObject('person-c');
    await tester.pump();
    expect(flight.started, ['person-a']);
    expect(flight.inFlight, 1);

    gates['person-a']!.complete();
    await tester.pump();
    await tester.pump();

    expect(flight.started, ['person-a', 'person-c']);
    expect(
      find.byKey(const ValueKey('person-detail-hydration-error')),
      findsNothing,
    );
    expect(find.text('Вера'), findsWidgets);
    expect(find.text('куратор'), findsWidgets);

    gates['person-c']!.complete();
    await tester.pumpAndSettle();
    expect(find.text('Задача Вера'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('person-detail-hydration-error')),
      findsNothing,
    );
    expect(flight.started, ['person-a', 'person-c']);
  });

  testWidgets('hydration retry stays single-flight', (tester) async {
    final flight = _Flight();
    var failures = 1;
    final gates = <String, Completer<void>>{};
    await _openPeople(
      tester,
      onRootedFlight: flight.record,
      rootedGate: gates,
      failRooted: () {
        if (failures > 0) {
          failures -= 1;
          return true;
        }
        return false;
      },
      people: [_person('person-a', 'Ада', role: 'директор')],
    );
    await tester.tap(find.byKey(const Key('graph_node_person-a')));
    await tester.pumpAndSettle();
    expect(flight.started, ['person-a']);
    expect(flight.inFlight, 0);
    expect(
      find.byKey(const ValueKey('person-detail-hydration-error')),
      findsOneWidget,
    );

    gates['person-a'] = Completer<void>();
    await tester.tap(
      find.byKey(const ValueKey('person-detail-hydration-retry')),
    );
    await tester.pump();
    await tester.tap(
      find.byKey(const ValueKey('person-detail-hydration-retry')),
    );
    await tester.pump();
    expect(flight.started, ['person-a', 'person-a']);
    expect(flight.inFlight, 1);
    expect(flight.peak, 1);

    gates['person-a']!.complete();
    await tester.pumpAndSettle();
    expect(flight.inFlight, 0);
    expect(flight.started, ['person-a', 'person-a']);
    expect(find.text('Задача Ады'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('person-detail-hydration-error')),
      findsNothing,
    );
  });

  testWidgets(
    'a pending person already rooted on the controller is not fetched again',
    (tester) async {
      final gates = {
        'person-a': Completer<void>(),
        'person-b': Completer<void>(),
      };
      final flight = _Flight();
      final harness = await _openPeople(
        tester,
        rootedGate: gates,
        onRootedFlight: flight.record,
        people: [
          _person('person-a', 'Ада', role: 'директор'),
          _person('person-b', 'Борис', role: 'студент'),
        ],
      );
      harness.graph.selectObject('person-a');
      await tester.pump();
      harness.graph.selectObject('person-b');
      await tester.pump();
      expect(flight.started, ['person-a']);
      harness.graph.rootId = 'person-b';

      gates['person-a']!.complete();
      await tester.pump();
      await tester.pump();
      expect(flight.started, ['person-a']);
      expect(flight.inFlight, 0);
      expect(find.text('Задача Ады'), findsNothing);
      expect(find.text('Борис'), findsWidgets);
    },
  );
}

class _Flight {
  final started = <String>[];
  var inFlight = 0;
  var peak = 0;

  void record(String rootId, {required bool active}) {
    if (active) {
      started.add(rootId);
      inFlight += 1;
      if (inFlight > peak) {
        peak = inFlight;
      }
      return;
    }
    inFlight -= 1;
  }
}

Future<GraphTestHarness> _openPeople(
  WidgetTester tester, {
  required List<Map<String, dynamic>> people,
  Map<String, Completer<void>> rootedGate = const {},
  bool Function()? failRooted,
  Set<String> failRootIds = const {},
  bool Function()? failAssign,
  void Function(String? rootId)? onWorkspace,
  void Function(String rootId, {required bool active})? onRootedFlight,
  String? bookmarkId,
}) async {
  tester.view.physicalSize = const Size(1280, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final harness = GraphTestHarness(
    MockClient((request) async {
      if (request.url.path == '/notifications') {
        return jsonUtf8Response({'notifications': []});
      }
      if (request.url.path == '/today') {
        return jsonUtf8Response({
          'date': '2026-10-16',
          'timezone': 'Europe/Amsterdam',
          'day_start': '2026-10-16T00:00:00+02:00',
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
            nodes: [graphObjectJson(id: 'task-1', title: 'Graph task')],
          ),
        );
      }
      if (request.url.path == '/graph/task-layout') {
        return jsonUtf8Response({
          'algorithm_version': 1,
          'revision': 1,
          'centers': [
            {'task_id': 'task-1', 'x': 120, 'y': 80},
          ],
        });
      }
      if (request.url.path == '/graph/task-layout/topology') {
        return jsonUtf8Response({
          'algorithm_version': 1,
          'active_task_ids': ['task-1'],
        });
      }
      if (request.url.path == '/object-bookmarks/by-objects') {
        return jsonUtf8Response({
          'objects': {
            if (bookmarkId != null) bookmarkId: {'color': 'red'},
          },
        });
      }
      if (request.url.path == '/graph/person-role-terms') {
        return jsonUtf8Response({
          'terms': <Map<String, dynamic>>[],
          'exact_match_term_id': null,
        });
      }
      if (request.url.path == '/graph/people-workspace') {
        final root = request.url.queryParameters['root_id'];
        onWorkspace?.call(root);
        if (root != null) {
          onRootedFlight?.call(root, active: true);
          try {
            final gate = rootedGate[root];
            if (gate != null && !gate.isCompleted) {
              await gate.future;
            }
            if (failRootIds.contains(root) || (failRooted?.call() ?? false)) {
              return http.Response('{}', 500);
            }
          } finally {
            onRootedFlight?.call(root, active: false);
          }
        }
        final visible = root == null
            ? people
            : people.where((item) => item['person_id'] == root).toList();
        return jsonUtf8Response({
          ...graphWorkspaceJson(
            rootId: root,
            nodes: [
              for (final person in visible)
                graphObjectJson(
                  id: person['person_id'] as String,
                  title: person['title'] as String,
                  kind: 'person',
                ),
            ],
          ),
          'window_index': 0,
          'window_count': 1,
          'has_previous_window': false,
          'has_next_window': false,
          'people': [
            for (final person in visible)
              root == null ? person : _rootedPerson(person),
          ],
        });
      }
      if (request.method == 'POST' && request.url.path.contains('/roles')) {
        if (failAssign?.call() ?? false) {
          return http.Response(
            jsonEncode({'detail': 'pool timeout'}),
            500,
            headers: {'content-type': 'application/json'},
          );
        }
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        final personId =
            request.url.pathSegments[request.url.pathSegments.length - 2];
        final role = body['role'] as String;
        return jsonUtf8Response({
          'id': 'role-$role',
          'person_id': personId,
          'role_term_id': 'term-$role',
          'role_display_text': role,
          'context': body['context'],
          'origin': 'user',
          'state': 'active',
        });
      }
      if (request.method == 'DELETE' && request.url.path.contains('/roles/')) {
        final segments = request.url.pathSegments;
        return jsonUtf8Response({
          'id': segments.last,
          'person_id': segments[segments.length - 3],
          'role_term_id': 'term',
          'role_display_text': 'директор',
          'context': 'Arenadata',
          'origin': 'user',
          'state': 'retracted',
        });
      }
      return http.Response('{}', 404);
    }),
  );
  harness.configure();
  await openGraph(tester, harness);
  await tester.tap(find.text('Люди'));
  await tester.pumpAndSettle();
  return harness;
}

PersonRoleAssignment _assignment(String personId, String text, String context) {
  return PersonRoleAssignment(
    id: 'role-$text',
    personId: personId,
    roleTermId: 'term',
    roleDisplayText: text,
    context: context,
    origin: 'user',
    state: 'active',
  );
}

Map<String, dynamic> _person(
  String id,
  String title, {
  String? role,
  String? context,
  bool conflict = false,
}) {
  return {
    'person_id': id,
    'title': title,
    'salience_score': 1,
    'identities': const [],
    'routes': const [],
    'identity_conflict': conflict,
    'open_task_count': 1,
    'recent_communication_count': 1,
    'landscape_task_ids': const <String>[],
    'landscape_task_ids_complete': true,
    'task_involvement': const [],
    'recent_communications': const [],
    'role_assignments': [
      if (role != null)
        {
          'id': 'role-$role',
          'person_id': id,
          'role_term_id': 'term-$role',
          'role_display_text': role,
          'context': context,
          'origin': 'user',
          'state': 'active',
        },
    ],
  };
}

String _ruName(String title) {
  return switch (title) {
    'Борис' => 'Бориса',
    'Ада' => 'Ады',
    _ => title,
  };
}

Map<String, dynamic> _rootedPerson(Map<String, dynamic> overview) {
  final id = overview['person_id'] as String;
  final title = overview['title'] as String;
  return {
    ...overview,
    'task_involvement': [
      {
        'task_id': 'task-$id',
        'title': 'Задача ${_ruName(title)}',
        'role': 'involves',
        'edge_state': 'confirmed',
        'edge_origin': 'user',
      },
    ],
    'recent_communications': [
      {
        'object_id': 'flow-$id',
        'kind': 'email',
        'title': 'Письмо ${_ruName(title)}',
      },
    ],
  };
}
