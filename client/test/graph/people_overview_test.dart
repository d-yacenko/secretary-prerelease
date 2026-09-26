import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/graph/graph_layout.dart';
import 'package:personal_secretary/graph/people_overview.dart';

import 'graph_test_harness.dart';

void main() {
  test('People overview visual order follows seed_ids', () {
    final nodes = [
      _person('person-a', 'Anna'),
      _person('person-b', 'Boris'),
      _person('person-c', 'Cara'),
    ];
    final projected = projectPeopleOverview(
      nodes: nodes,
      seedIds: const ['person-c', 'person-a', 'person-b'],
      rootId: null,
    );
    expect(projected['person-c']!.dx, lessThan(projected['person-a']!.dx));
    expect(projected['person-a']!.dx, lessThan(projected['person-b']!.dx));
    expect(projected['person-c']!.dy, projected['person-a']!.dy);
  });

  test('repeated People overview projection is identical', () {
    final nodes = [
      _person('person-a', 'Anna'),
      _person('person-b', 'Boris'),
    ];
    const seeds = ['person-b', 'person-a'];
    final first = projectPeopleOverview(
      nodes: nodes,
      seedIds: seeds,
      rootId: null,
    );
    final second = projectPeopleOverview(
      nodes: nodes,
      seedIds: seeds,
      rootId: null,
    );
    expect(second, first);
  });

  test('Person missing from seed_ids follows ranked seeds by title then id', () {
    final nodes = [
      _person('person-z', 'Zoya'),
      _person('person-m', 'Mira'),
      _person('person-a2', 'Anna'),
      _person('person-a1', 'Anna'),
    ];
    final projected = projectPeopleOverview(
      nodes: nodes,
      seedIds: const ['person-z'],
      rootId: null,
    );
    final order = projected.entries.toList()
      ..sort((a, b) {
        final byY = a.value.dy.compareTo(b.value.dy);
        if (byY != 0) {
          return byY;
        }
        return a.value.dx.compareTo(b.value.dx);
      });
    expect(order.map((entry) => entry.key).toList(), [
      'person-z',
      'person-a1',
      'person-a2',
      'person-m',
    ]);
  });

  test('overview projection does not rewrite a canonical position map', () {
    final nodes = [
      _person('person-a', 'Anna'),
      _person('person-c', 'Cara'),
    ];
    final canonical = GraphLayout.computePositions(
      nodes: nodes,
      edges: const [],
      rootId: null,
      existing: const {},
      freshRoot: true,
    );
    final before = Map<String, Offset>.from(canonical);
    projectPeopleOverview(
      nodes: nodes,
      seedIds: const ['person-c', 'person-a'],
      rootId: null,
    );
    expect(canonical, before);
    expect(before['person-a']!.dx, lessThan(before['person-c']!.dx));
  });

  test('Task nodes are not placed by the People overview projection', () {
    final projected = projectPeopleOverview(
      nodes: [
        _person('person-b', 'Boris'),
        SecretaryObject.fromJson(
          graphObjectJson(id: 'task-a', title: 'Task', kind: 'task'),
        ),
      ],
      seedIds: const ['task-a', 'person-b'],
      rootId: null,
    );
    expect(projected.keys, ['person-b']);
  });

  test('rooted People overview projection adds no positions', () {
    final projected = projectPeopleOverview(
      nodes: [_person('person-a', 'Anna'), _person('person-b', 'Boris')],
      seedIds: const ['person-b', 'person-a'],
      rootId: 'person-a',
    );
    expect(projected, isEmpty);
  });

  testWidgets('People cards show grounded cues and keep canonical positions', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = GraphTestHarness(
      MockClient((request) async {
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
          final body = graphWorkspaceJson(
            nodes: [
              graphObjectJson(id: 'task-a', title: 'Alpha task'),
              graphObjectJson(id: 'task-b', title: 'Beta task'),
            ],
          );
          body['seed_ids'] = ['task-b', 'task-a'];
          return jsonUtf8Response(body);
        }
        if (request.url.path == '/graph/people-workspace') {
          final root = request.url.queryParameters['root_id'];
          if (root == 'person-c') {
            return jsonUtf8Response(
              _workspace(
                rootId: 'person-c',
                seedIds: const ['person-c'],
                people: [
                  _card(
                    'person-c',
                    'Cara',
                    conflict: true,
                    openTasks: 3,
                    messages: 7,
                    identities: [
                      _identity('gmail', 'cara@gmail.com', 'effective'),
                    ],
                  ),
                ],
                nodes: [
                  graphObjectJson(id: 'person-c', title: 'Cara', kind: 'person'),
                  graphObjectJson(id: 'task-linked', title: 'Linked task', kind: 'task'),
                  graphObjectJson(id: 'mail-1', title: 'Hello Cara', kind: 'email'),
                ],
                edges: [
                  _edge('e1', 'person-c', 'task-linked'),
                  _edge('e2', 'person-c', 'mail-1'),
                ],
              ),
            );
          }
          return jsonUtf8Response(
            _workspace(
              seedIds: const ['person-c', 'person-a'],
              people: [
                _card(
                  'person-c',
                  'Cara',
                  conflict: true,
                  openTasks: 3,
                  messages: 7,
                  salience: 4242,
                  identities: [
                    _identity('gmail', 'cara@gmail.com', 'effective'),
                    _identity('telegram', 'cara-tg', 'effective'),
                    _identity('yandex', 'cara@yandex.ru', 'effective'),
                    _identity('email', 'old@example.com', 'rejected'),
                    _identity('upload', 'candidate@example.com', 'candidate'),
                  ],
                ),
                _card('person-a', 'Anna', openTasks: 1, messages: 2),
              ],
              nodes: [
                graphObjectJson(id: 'person-c', title: 'Cara', kind: 'person'),
                graphObjectJson(id: 'person-a', title: 'Anna', kind: 'person'),
                graphObjectJson(id: 'person-plain', title: 'Plain', kind: 'person'),
              ],
            ),
          );
        }
        if (request.url.path.endsWith('/identity-correction')) {
          return jsonUtf8Response({
            'person_id': 'person-c',
            'evidence_id': 'evidence-1',
            'evidence_type': 'user_rejected',
            'state': 'active',
          });
        }
        return http.Response('{}', 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);

    expect(harness.graph.positions['task-a']!.dx, lessThan(harness.graph.positions['task-b']!.dx));
    final taskA = tester.getTopLeft(find.byKey(const Key('graph_node_task-a')));
    final taskB = tester.getTopLeft(find.byKey(const Key('graph_node_task-b')));
    expect(taskB.dx < taskA.dx, isFalse);

    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();

    final canonical = Map<String, Offset>.from(harness.graph.positions);
    expect(canonical['person-a']!.dx, lessThan(canonical['person-c']!.dx));
    expect(canonical['person-c']!.dx, lessThan(canonical['person-plain']!.dx));
    expect(
      tester.getTopLeft(find.byKey(const Key('graph_node_person-c'))).dx,
      lessThan(tester.getTopLeft(find.byKey(const Key('graph_node_person-a'))).dx),
    );
    expect(harness.graph.positions, canonical);
    expect(find.text('4242'), findsNothing);
    expect(find.text('Cara'), findsWidgets);
    expect(find.text('Человек'), findsWidgets);
    expect(find.text('Задач: 3 · сообщений: 7'), findsOneWidget);
    expect(find.text('Задач: 1 · сообщений: 2'), findsOneWidget);
    expect(find.byKey(const Key('person-activity-footer-person-plain')), findsNothing);
    expect(find.byIcon(Icons.person_outline), findsWidgets);
    final cues = tester.widget<Text>(find.byKey(const Key('person-provider-cues-person-c')));
    expect(cues.data, 'Gmail · Telegram');
    expect(find.textContaining('Яндекс'), findsNothing);
    expect(find.textContaining('old@example.com'), findsNothing);
    expect(find.byKey(const Key('person-identity-conflict-person-c')), findsOneWidget);

    final firstCara = tester.getTopLeft(find.byKey(const Key('graph_node_person-c')));
    await harness.graph.loadOverview();
    await tester.pumpAndSettle();
    expect(tester.getTopLeft(find.byKey(const Key('graph_node_person-c'))), firstCara);
    expect(harness.graph.positions, canonical);

    await tester.tap(find.text('Cara').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('В центр'));
    await tester.pumpAndSettle();
    expect(harness.graph.rootId, 'person-c');
    expect(find.text('Linked task'), findsOneWidget);
    expect(find.text('Hello Cara'), findsOneWidget);
    expect(find.byKey(const Key('person-activity-footer-task-linked')), findsNothing);
    expect(find.byKey(const Key('person-activity-footer-mail-1')), findsNothing);
    expect(harness.graph.positions['person-c'], isNot(harness.graph.positions['task-linked']));
    expect(find.text('Известные контакты'), findsOneWidget);
    expect(find.text('Маршруты'), findsOneWidget);
    expect(find.text('Открытые задачи: 3'), findsOneWidget);
    expect(find.text('Недавние коммуникации: 7'), findsOneWidget);
    expect(find.text('Отклонить'), findsWidgets);
    await tester.tap(find.text('Отклонить').first);
    await tester.pumpAndSettle();
    expect(find.text('Известные контакты'), findsOneWidget);
    expect(harness.graph.rootId, 'person-c');
  });
}

SecretaryObject _person(String id, String title) {
  return SecretaryObject.fromJson(
    graphObjectJson(id: id, title: title, kind: 'person'),
  );
}

Map<String, dynamic> _identity(String provider, String value, String state) {
  return {
    'provider': provider,
    'identity_type': 'handle',
    'display_value': value,
    'realm': '',
    'canonical_value': value,
    'state': state,
    'confirmable': state == 'candidate',
  };
}

Map<String, dynamic> _card(
  String id,
  String title, {
  bool conflict = false,
  int openTasks = 0,
  int messages = 0,
  int salience = 1,
  List<Map<String, dynamic>>? identities,
}) {
  return {
    'person_id': id,
    'title': title,
    'salience_score': salience,
    'identities': identities ??
        [
          _identity('gmail', '$id@example.com', 'effective'),
        ],
    'routes': [
      {'provider': 'gmail', 'label': 'Письмо $title', 'route_key': 'gmail:$id'},
    ],
    'identity_conflict': conflict,
    'open_task_count': openTasks,
    'recent_communication_count': messages,
  };
}

Map<String, dynamic> _edge(String id, String source, String target) {
  return {
    'id': id,
    'source_id': source,
    'target_id': target,
    'type': 'related_to',
    'origin': 'user',
    'state': 'confirmed',
    'metadata': {},
    'created_at': '2026-01-01T00:00:00Z',
    'updated_at': '2026-01-01T00:00:00Z',
  };
}

Map<String, dynamic> _workspace({
  String? rootId,
  required List<String> seedIds,
  required List<Map<String, dynamic>> people,
  required List<Map<String, dynamic>> nodes,
  List<Map<String, dynamic>> edges = const [],
}) {
  return {
    ...graphWorkspaceJson(rootId: rootId, nodes: nodes, edges: edges),
    'seed_ids': seedIds,
    'people': people.where((person) => person['person_id'] != 'skip').toList(),
  };
}
