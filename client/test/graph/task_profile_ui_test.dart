import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/graph/graph_workspace_controller.dart';
import 'package:personal_secretary/graph/task_profile_section.dart';

import 'graph_test_harness.dart';

Map<String, dynamic> _edgeJson({
  required String id,
  String type = 'waiting_on',
  String origin = 'user',
  String state = 'confirmed',
}) {
  return {
    'id': id,
    'source_id': 'task-1',
    'target_id': 'other',
    'type': type,
    'origin': origin,
    'state': state,
    'confidence': null,
    'metadata': {},
    'created_at': '2026-01-01T00:00:00Z',
    'updated_at': '2026-01-01T00:00:00Z',
  };
}

Map<String, dynamic> _actorJson({
  required String edgeId,
  required String personId,
  required String title,
  required String state,
  required String origin,
  double? confidence,
  String? cue,
}) {
  return {
    'edge_id': edgeId,
    'person_id': personId,
    'title': title,
    'contact_cue': cue,
    'edge_state': state,
    'edge_origin': origin,
    'edge_confidence': confidence,
  };
}

Map<String, dynamic> _linkJson({
  required String edgeId,
  required String objectId,
  required String title,
  required String kind,
  required String state,
  required String origin,
}) {
  return {
    'edge_id': edgeId,
    'object_id': objectId,
    'title': title,
    'kind': kind,
    'edge_state': state,
    'edge_origin': origin,
    'edge_confidence': 0.4,
  };
}

Map<String, dynamic> profileJson({
  String taskId = 'task-1',
  String title = 'Graph task',
  List<Map<String, dynamic>> requestedBy = const [],
  List<Map<String, dynamic>> waitingOn = const [],
  List<Map<String, dynamic>> dependsOn = const [],
  List<Map<String, dynamic>> dependentTasks = const [],
  List<Map<String, dynamic>> evidence = const [],
}) {
  return {
    'task': graphObjectJson(id: taskId, title: title),
    'status': 'open',
    'start_at': null,
    'due_at': '2026-09-01T00:00:00Z',
    'planned_start_at': null,
    'planned_end_at': null,
    'requested_by': requestedBy,
    'delegated_to': const [],
    'waiting_on': waitingOn,
    'involves': const [],
    'depends_on': dependsOn,
    'dependent_tasks': dependentTasks,
    'evidence': evidence,
  };
}

MockClient _graphClient({
  required Future<http.Response> Function(http.Request request) onProfile,
  Future<http.Response> Function(http.Request request)? onOther,
}) {
  return MockClient((request) async {
    if (request.url.path == '/notifications') {
      return jsonUtf8Response({'notifications': []});
    }
    if (request.url.path == '/today') {
      return jsonUtf8Response({
        'date': '2026-08-28',
        'timezone': 'Europe/Amsterdam',
        'day_start': '2026-08-28T08:00:00+02:00',
        'tasks': [],
        'calendar_events': [],
        'notifications': [],
      });
    }
    if (request.url.path == '/graph/workspace' ||
        request.url.path == '/graph/people-workspace') {
      if (request.url.queryParameters['q'] != null && onOther != null) {
        return onOther(request);
      }
      final root = request.url.queryParameters['root_id'];
      if (root == 'person-1') {
        return jsonUtf8Response(
          graphWorkspaceJson(
            rootId: 'person-1',
            nodes: [
              graphObjectJson(id: 'person-1', title: 'Ольга', kind: 'person'),
            ],
          ),
        );
      }
      if (root == 'task-2') {
        return jsonUtf8Response(
          graphWorkspaceJson(
            rootId: 'task-2',
            nodes: [graphObjectJson(id: 'task-2', title: 'Блокер')],
          ),
        );
      }
      return jsonUtf8Response(
        graphWorkspaceJson(
          nodes: [
            graphObjectJson(id: 'task-1', title: 'Graph task'),
            graphObjectJson(id: 'task-2', title: 'Другая задача'),
          ],
        ),
      );
    }
    if (request.url.path.endsWith('/profile')) {
      return onProfile(request);
    }
    if (onOther != null) {
      return onOther(request);
    }
    return jsonUtf8Response({}, statusCode: 404);
  });
}

Future<void> useDesktop(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1280, 800);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

Future<void> showTask(WidgetTester tester, GraphTestHarness harness, String id) async {
  harness.graph.selectObject(id);
  await tester.pumpAndSettle();
  final header = find.text('Профиль задачи');
  expect(header, findsOneWidget);
  await tester.ensureVisible(header);
  await tester.pumpAndSettle();
}

void main() {
  test('Task Profile decodes actor, dependency, and evidence provenance', () {
    final profile = TaskProfile.fromJson(
      profileJson(
        requestedBy: [
          _actorJson(
            edgeId: 'edge-ask',
            personId: 'person-1',
            title: 'Ольга',
            state: 'proposed',
            origin: 'agent',
            confidence: 0.8,
            cue: 'olga@example.com',
          ),
        ],
        dependsOn: [
          _linkJson(
            edgeId: 'edge-dep',
            objectId: 'task-2',
            title: 'Блокер',
            kind: 'task',
            state: 'confirmed',
            origin: 'user',
          ),
        ],
        evidence: [
          _linkJson(
            edgeId: 'edge-mail',
            objectId: 'mail-1',
            title: 'Письмо',
            kind: 'email',
            state: 'proposed',
            origin: 'agent',
          ),
        ],
      ),
    );
    expect(profile.requestedBy.single.edgeState, 'proposed');
    expect(profile.requestedBy.single.edgeOrigin, 'agent');
    expect(profile.requestedBy.single.edgeConfidence, 0.8);
    expect(profile.requestedBy.single.contactCue, 'olga@example.com');
    expect(profile.dependsOn.single.edgeState, 'confirmed');
    expect(profile.dependsOn.single.edgeOrigin, 'user');
    expect(profile.evidence.single.kind, 'email');
    expect(profile.evidence.single.edgeConfidence, 0.4);
  });

  test('self-dependency is rejected before a request', () {
    expect(canAttachTaskDependency('task-1', 'task-1'), isFalse);
    expect(canAttachTaskDependency('task-1', 'task-2'), isTrue);
  });

  testWidgets('selecting a task loads profile and skips empty groups', (tester) async {
    await useDesktop(tester);
    final paths = <String>[];
    final harness = GraphTestHarness(
      _graphClient(
        onProfile: (request) async {
          paths.add('${request.method} ${request.url.path}');
          return jsonUtf8Response(
            profileJson(
              waitingOn: [
                _actorJson(
                  edgeId: 'edge-wait',
                  personId: 'person-1',
                  title: 'Нина',
                  state: 'confirmed',
                  origin: 'user',
                ),
              ],
            ),
          );
        },
      ),
    );
    harness.configure();
    await openGraph(tester, harness);
    await showTask(tester, harness, 'task-1');

    expect(paths, contains('GET /tasks/task-1/profile'));
    expect(find.text('Ждём'), findsOneWidget);
    expect(find.text('Нина'), findsOneWidget);
    expect(find.text('Запросил'), findsNothing);
    expect(find.text('Поручено'), findsNothing);
    expect(find.text('Участвует'), findsNothing);
    expect(find.text('Зависит от'), findsNothing);
    expect(find.text('От неё зависят'), findsNothing);
    expect(find.text('Основание'), findsNothing);
    expect(find.text('Спросить секретаря'), findsOneWidget);
    expect(find.text('В работе'), findsNothing);

    await tester.ensureVisible(find.text('Нина'));
    await tester.tap(find.text('Нина'));
    await tester.pumpAndSettle();
    expect(harness.graph.mode, GraphWorkspaceMode.people);
    expect(harness.graph.rootId, 'person-1');
    expect(find.text('Профиль задачи'), findsNothing);
  });

  testWidgets('a late profile does not replace the newly selected task', (tester) async {
    await useDesktop(tester);
    final first = Completer<http.Response>();
    final harness = GraphTestHarness(
      _graphClient(
        onProfile: (request) async {
          if (request.url.path == '/tasks/task-1/profile') {
            return first.future;
          }
          return jsonUtf8Response(
            profileJson(
              taskId: 'task-2',
              title: 'Другая задача',
              waitingOn: [
                _actorJson(
                  edgeId: 'edge-new',
                  personId: 'person-2',
                  title: 'Новый человек',
                  state: 'confirmed',
                  origin: 'user',
                ),
              ],
            ),
          );
        },
      ),
    );
    harness.configure();
    await openGraph(tester, harness);
    harness.graph.selectObject('task-1');
    await tester.pump();
    harness.graph.selectObject('task-2');
    await tester.pumpAndSettle();
    expect(find.text('Новый человек'), findsOneWidget);

    first.complete(
      jsonUtf8Response(
        profileJson(
          waitingOn: [
            _actorJson(
              edgeId: 'edge-old',
              personId: 'person-1',
              title: 'Старый человек',
              state: 'confirmed',
              origin: 'user',
            ),
          ],
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Старый человек'), findsNothing);
    expect(find.text('Новый человек'), findsOneWidget);
    expect(harness.graph.selectedObjectId, 'task-2');
  });

  testWidgets('proposed role is confirmed or rejected through relation decision', (tester) async {
    await useDesktop(tester);
    final decisions = <String>[];
    var proposed = true;
    final harness = GraphTestHarness(
      _graphClient(
        onProfile: (request) async {
          return jsonUtf8Response(
            profileJson(
              requestedBy: proposed
                  ? [
                      _actorJson(
                        edgeId: 'edge-ask',
                        personId: 'person-1',
                        title: 'Ольга',
                        state: 'proposed',
                        origin: 'agent',
                        confidence: 0.7,
                      ),
                    ]
                  : [
                      _actorJson(
                        edgeId: 'edge-ask',
                        personId: 'person-1',
                        title: 'Ольга',
                        state: 'confirmed',
                        origin: 'user',
                      ),
                    ],
            ),
          );
        },
        onOther: (request) async {
          if (request.method == 'POST' &&
              request.url.path == '/relations/edge-ask/decision') {
            final body = jsonDecode(request.body) as Map<String, dynamic>;
            decisions.add(body['decision'] as String);
            if (body['decision'] == 'reject') {
              proposed = false;
            } else {
              proposed = false;
            }
            return jsonUtf8Response({'edge': _edgeJson(id: 'edge-ask', state: 'confirmed')});
          }
          return jsonUtf8Response({}, statusCode: 404);
        },
      ),
    );
    harness.configure();
    await openGraph(tester, harness);
    await showTask(tester, harness, 'task-1');
    expect(find.text('Предложено секретарём'), findsOneWidget);
    expect(find.text('Запросил'), findsOneWidget);

    await tester.ensureVisible(find.byTooltip('Подтвердить'));
    await tester.tap(find.byTooltip('Подтвердить'));
    await tester.pumpAndSettle();
    expect(decisions, ['confirm']);
    expect(find.text('Предложено секретарём'), findsNothing);
    expect(find.text('Ольга'), findsOneWidget);
  });

  testWidgets('rejecting a proposal reloads a profile without that role', (tester) async {
    await useDesktop(tester);
    var visible = true;
    final harness = GraphTestHarness(
      _graphClient(
        onProfile: (request) async {
          return jsonUtf8Response(
            profileJson(
              requestedBy: visible
                  ? [
                      _actorJson(
                        edgeId: 'edge-ask',
                        personId: 'person-1',
                        title: 'Ольга',
                        state: 'proposed',
                        origin: 'agent',
                      ),
                    ]
                  : const [],
            ),
          );
        },
        onOther: (request) async {
          if (request.url.path == '/relations/edge-ask/decision') {
            visible = false;
            return jsonUtf8Response({
              'edge': _edgeJson(id: 'edge-ask', state: 'rejected'),
            });
          }
          return jsonUtf8Response({}, statusCode: 404);
        },
      ),
    );
    harness.configure();
    await openGraph(tester, harness);
    await showTask(tester, harness, 'task-1');
    await tester.ensureVisible(find.byTooltip('Отклонить'));
    await tester.tap(find.byTooltip('Отклонить'));
    await tester.pumpAndSettle();
    expect(find.text('Ольга'), findsNothing);
    expect(find.text('Запросил'), findsNothing);
  });

  testWidgets('adding and removing a person role uses the canonical endpoints', (tester) async {
    await useDesktop(tester);
    final calls = <String>[];
    var waiting = <Map<String, dynamic>>[];
    final harness = GraphTestHarness(
      _graphClient(
        onProfile: (request) async {
          calls.add('GET ${request.url.path}');
          return jsonUtf8Response(profileJson(waitingOn: waiting));
        },
        onOther: (request) async {
          calls.add('${request.method} ${request.url.path} ${request.body}');
          if (request.url.path == '/graph/people-workspace' &&
              request.url.queryParameters['q'] == 'Нина') {
            return jsonUtf8Response(
              graphWorkspaceJson(
                nodes: [
                  graphObjectJson(id: 'person-1', title: 'Нина', kind: 'person'),
                ],
              ),
            );
          }
          if (request.method == 'POST' && request.url.path == '/tasks/task-1/actors') {
            final body = jsonDecode(request.body) as Map<String, dynamic>;
            expect(body['person_id'], 'person-1');
            expect(body['role'], 'waiting_on');
            waiting = [
              _actorJson(
                edgeId: 'edge-wait',
                personId: 'person-1',
                title: 'Нина',
                state: 'confirmed',
                origin: 'user',
              ),
            ];
            return jsonUtf8Response({
              'edge': _edgeJson(id: 'edge-wait'),
              'created': waiting.length == 1,
              'changed': false,
            });
          }
          if (request.method == 'DELETE' &&
              request.url.path == '/tasks/task-1/actors/edge-wait') {
            waiting = [];
            return jsonUtf8Response({
              'edge': _edgeJson(id: 'edge-wait', state: 'rejected'),
              'created': false,
              'changed': true,
            });
          }
          return jsonUtf8Response({}, statusCode: 404);
        },
      ),
    );
    harness.configure();
    await openGraph(tester, harness);
    await showTask(tester, harness, 'task-1');
    await tester.ensureVisible(find.text('Добавить человека'));
    await tester.tap(find.text('Добавить человека'));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, 'Поиск человека'), 'Нина');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Нина').last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Добавить'));
    await tester.pumpAndSettle();
    expect(find.text('Ждём'), findsOneWidget);
    expect(find.text('Нина'), findsOneWidget);

    await tester.tap(find.text('Добавить человека'));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, 'Поиск человека'), 'Нина');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Нина').last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Добавить'));
    await tester.pumpAndSettle();
    expect(find.text('Нина'), findsOneWidget);

    await tester.tap(find.byTooltip('Убрать роль'));
    await tester.pumpAndSettle();
    expect(find.text('Нина'), findsNothing);
    expect(
      calls.where((call) => call.startsWith('DELETE /tasks/task-1/actors/edge-wait')),
      isNotEmpty,
    );
  });

  testWidgets('dependency add skips the current task and removal uses the edge id',
      (tester) async {
    await useDesktop(tester);
    final calls = <String>[];
    var dependencies = <Map<String, dynamic>>[];
    final harness = GraphTestHarness(
      _graphClient(
        onProfile: (request) async {
          return jsonUtf8Response(profileJson(dependsOn: dependencies));
        },
        onOther: (request) async {
          calls.add('${request.method} ${request.url.path}');
          if (request.url.path == '/search') {
            return jsonUtf8Response([
              graphObjectJson(id: 'task-1', title: 'Graph task'),
              graphObjectJson(id: 'task-2', title: 'Блокер'),
            ]);
          }
          if (request.method == 'POST' &&
              request.url.path == '/tasks/task-1/dependencies') {
            final body = jsonDecode(request.body) as Map<String, dynamic>;
            expect(body['depends_on_task_id'], 'task-2');
            dependencies = [
              _linkJson(
                edgeId: 'edge-dep',
                objectId: 'task-2',
                title: 'Блокер',
                kind: 'task',
                state: 'confirmed',
                origin: 'user',
              ),
            ];
            return jsonUtf8Response({
              'edge': _edgeJson(id: 'edge-dep', type: 'depends_on'),
              'created': true,
              'changed': false,
            });
          }
          if (request.method == 'DELETE' &&
              request.url.path == '/tasks/task-1/dependencies/edge-dep') {
            dependencies = [];
            return jsonUtf8Response({
              'edge': _edgeJson(id: 'edge-dep', type: 'depends_on', state: 'rejected'),
              'created': false,
              'changed': true,
            });
          }
          return jsonUtf8Response({}, statusCode: 404);
        },
      ),
    );
    harness.configure();
    await openGraph(tester, harness);
    await showTask(tester, harness, 'task-1');
    await tester.ensureVisible(find.text('Добавить зависимость'));
    await tester.tap(find.text('Добавить зависимость'));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, 'Поиск задачи'), 'блок');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    expect(find.widgetWithText(ListTile, 'Graph task'), findsNothing);
    await tester.tap(find.widgetWithText(ListTile, 'Блокер'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Добавить'));
    await tester.pumpAndSettle();
    expect(find.text('Зависит от'), findsOneWidget);
    expect(
      calls.where((call) => call == 'POST /tasks/task-1/dependencies').length,
      1,
    );

    await tester.tap(find.byTooltip('Убрать зависимость'));
    await tester.pumpAndSettle();
    expect(calls, contains('DELETE /tasks/task-1/dependencies/edge-dep'));
    expect(find.text('Блокер'), findsNothing);
  });

  testWidgets('evidence opens through object navigation and people mode stays separate',
      (tester) async {
    await useDesktop(tester);
    final harness = GraphTestHarness(
      _graphClient(
        onProfile: (request) async {
          if (request.url.path != '/tasks/task-1/profile') {
            return jsonUtf8Response({}, statusCode: 404);
          }
          return jsonUtf8Response(
            profileJson(
              evidence: [
                _linkJson(
                  edgeId: 'edge-mail',
                  objectId: 'mail-1',
                  title: 'Письмо основания',
                  kind: 'email',
                  state: 'confirmed',
                  origin: 'user',
                ),
              ],
              dependentTasks: [
                _linkJson(
                  edgeId: 'edge-down',
                  objectId: 'task-2',
                  title: 'Следующая',
                  kind: 'task',
                  state: 'confirmed',
                  origin: 'user',
                ),
              ],
            ),
          );
        },
        onOther: (request) async {
          if (request.url.path == '/objects/mail-1') {
            return jsonUtf8Response(
              graphObjectJson(id: 'mail-1', title: 'Письмо основания', kind: 'email'),
            );
          }
          if (request.url.path == '/objects/mail-1/neighbors') {
            return jsonUtf8Response({'object_id': 'mail-1', 'neighbors': []});
          }
          if (request.url.path == '/objects/mail-1/context') {
            return jsonUtf8Response({
              'object': graphObjectJson(
                id: 'mail-1',
                title: 'Письмо основания',
                kind: 'email',
              ),
              'edges': [],
              'neighbors': [],
            });
          }
          return jsonUtf8Response({}, statusCode: 404);
        },
      ),
    );
    harness.configure();
    await openGraph(tester, harness);
    await showTask(tester, harness, 'task-1');
    expect(find.text('Основание'), findsOneWidget);
    expect(find.text('От неё зависят'), findsOneWidget);
    await tester.tap(find.text('Следующая'));
    await tester.pumpAndSettle();
    expect(harness.graph.rootId, 'task-2');
    expect(harness.graph.mode, GraphWorkspaceMode.tasks);
    await harness.graph.loadOverview();
    await tester.pumpAndSettle();
    await showTask(tester, harness, 'task-1');
    await tester.tap(find.text('Письмо основания'));
    await tester.pumpAndSettle();
    expect(find.text('Подробности'), findsWidgets);

    await tester.pageBack();
    await tester.pumpAndSettle();
    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    expect(find.text('Профиль задачи'), findsNothing);
    expect(find.text('Добавить человека'), findsNothing);
  });
}
