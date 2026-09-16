import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/tasks/task_management_actions.dart';

SecretaryObject taskObject({
  String id = 'task-1',
  String title = 'Original title',
  String? body = 'Body text',
  String? dueAt,
  String? plannedStartAt,
  String? plannedEndAt,
  String status = 'open',
}) {
  return SecretaryObject(
    id: id,
    kind: 'task',
    title: title,
    body: body,
    metadata: {},
    origin: 'user',
    state: 'confirmed',
    status: status,
    dueAt: dueAt,
    plannedStartAt: plannedStartAt,
    plannedEndAt: plannedEndAt,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  );
}

Map<String, dynamic> taskJson(SecretaryObject task) {
  return {
    'id': task.id,
    'kind': task.kind,
    'title': task.title,
    'body': task.body,
    'provider': null,
    'external_id': null,
    'canonical_uri': null,
    'status': task.status,
    'start_at': null,
    'due_at': task.dueAt,
    'planned_start_at': task.plannedStartAt,
    'planned_end_at': task.plannedEndAt,
    'metadata': {},
    'origin': task.origin,
    'state': task.state,
    'confidence': null,
    'created_at': task.createdAt,
    'updated_at': task.updatedAt,
  };
}

Widget buildActions({
  required MockClient mock,
  required SecretaryObject task,
  ValueChanged<SecretaryObject>? onUpdated,
}) {
  final apiClient = SecretaryApiClient(httpClient: mock);
  apiClient.configure(baseUrl: 'https://example.com', token: 'token');
  final auth = AuthController(
    apiClient: apiClient,
    tokenStore: FakeTokenStore(),
    serverUrlStore: FakeServerUrlStore(),
  );
  auth.status = AuthStatus.authenticated;
  SecretaryObject current = task;
  return MaterialApp(
    home: Scaffold(
      body: TaskManagementActions(
        task: current,
        apiClient: apiClient,
        authController: auth,
        onTaskUpdated: (updated) {
          current = updated;
          onUpdated?.call(updated);
        },
      ),
    ),
  );
}

void main() {
  testWidgets('title edit sends PATCH', (tester) async {
    String? patchBody;
    final task = taskObject();
    await tester.pumpWidget(
      buildActions(
        task: task,
        mock: MockClient((request) async {
          if (request.method == 'PATCH') {
            patchBody = request.body;
            return http.Response(
              jsonEncode({
                'object': taskJson(taskObject(title: 'Renamed')),
              }),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
      ),
    );

    await tester.tap(find.text('Редактировать'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, 'Renamed');
    await tester.tap(find.text('Сохранить'));
    await tester.pumpAndSettle();

    expect(patchBody, isNotNull);
    final payload = jsonDecode(patchBody!) as Map<String, dynamic>;
    expect(payload['title'], 'Renamed');
    expect(payload.containsKey('status'), isFalse);
  });

  testWidgets('body clear sends null body', (tester) async {
    String? patchBody;
    await tester.pumpWidget(
      buildActions(
        task: taskObject(),
        mock: MockClient((request) async {
          if (request.method == 'PATCH') {
            patchBody = request.body;
            return http.Response(
              jsonEncode({'object': taskJson(taskObject(body: null))}),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
      ),
    );

    await tester.tap(find.text('Редактировать'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Очистить описание'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Сохранить'));
    await tester.pumpAndSettle();

    final payload = jsonDecode(patchBody!) as Map<String, dynamic>;
    expect(payload['body'], isNull);
  });

  testWidgets('clear due date sends due_at null', (tester) async {
    String? patchBody;
    await tester.pumpWidget(
      buildActions(
        task: taskObject(dueAt: '2026-10-01T12:00:00Z'),
        mock: MockClient((request) async {
          if (request.method == 'PATCH') {
            patchBody = request.body;
            return http.Response(
              jsonEncode({'object': taskJson(taskObject(dueAt: null))}),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
      ),
    );

    await tester.tap(find.text('Редактировать'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Очистить срок'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Сохранить'));
    await tester.pumpAndSettle();

    final payload = jsonDecode(patchBody!) as Map<String, dynamic>;
    expect(payload['due_at'], isNull);
  });

  testWidgets('untouched due date omitted from PATCH', (tester) async {
    int patchCalls = 0;
    await tester.pumpWidget(
      buildActions(
        task: taskObject(title: 'Same', body: 'Body text'),
        mock: MockClient((request) async {
          if (request.method == 'PATCH') {
            patchCalls += 1;
            return http.Response(
              jsonEncode({'object': taskJson(taskObject(title: 'Same'))}),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
      ),
    );

    await tester.tap(find.text('Редактировать'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Сохранить'));
    await tester.pumpAndSettle();

    expect(patchCalls, 0);
  });

  testWidgets('status change sends POST status', (tester) async {
    String? path;
    Map<String, dynamic>? body;
    await tester.pumpWidget(
      buildActions(
        task: taskObject(status: 'open'),
        mock: MockClient((request) async {
          if (request.method == 'POST' && request.url.path.endsWith('/status')) {
            path = request.url.path;
            body = jsonDecode(request.body) as Map<String, dynamic>;
            return http.Response(
              jsonEncode({
                'object': taskJson(taskObject(status: 'in_progress')),
                'changed': true,
                'previous_status': 'open',
                'new_status': 'in_progress',
              }),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
      ),
    );

    await tester.tap(find.text('Статус'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('В работе'));
    await tester.pumpAndSettle();

    expect(path, '/tasks/task-1/status');
    expect(body, {'status': 'in_progress'});
  });

  testWidgets('delete cancel sends no DELETE', (tester) async {
    int deleteCalls = 0;
    await tester.pumpWidget(
      buildActions(
        task: taskObject(),
        mock: MockClient((request) async {
          if (request.method == 'DELETE') {
            deleteCalls += 1;
          }
          return http.Response('{}', 404);
        }),
      ),
    );

    await tester.tap(find.text('Удалить'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Отмена'));
    await tester.pumpAndSettle();

    expect(deleteCalls, 0);
  });

  testWidgets('delete confirm sends DELETE /tasks/{id}', (tester) async {
    String? path;
    await tester.pumpWidget(
      buildActions(
        task: taskObject(),
        mock: MockClient((request) async {
          if (request.method == 'DELETE') {
            path = request.url.path;
            return http.Response(
              jsonEncode({
                'object': taskJson(taskObject(status: 'deleted')),
                'changed': true,
                'previous_status': 'open',
                'new_status': 'deleted',
              }),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
      ),
    );

    await tester.tap(find.text('Удалить'));
    await tester.pumpAndSettle();
    await tester.tap(
      find.descendant(
        of: find.byType(AlertDialog),
        matching: find.widgetWithText(FilledButton, 'Удалить'),
      ),
    );
    await tester.pumpAndSettle();

    expect(path, '/tasks/task-1');
  });

  testWidgets('server error keeps task unchanged', (tester) async {
    SecretaryObject? updated;
    await tester.pumpWidget(
      buildActions(
        task: taskObject(),
        onUpdated: (value) => updated = value,
        mock: MockClient((request) async {
          if (request.method == 'PATCH') {
            return http.Response('bad', 500);
          }
          return http.Response('{}', 404);
        }),
      ),
    );

    await tester.tap(find.text('Редактировать'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, 'Broken');
    await tester.tap(find.text('Сохранить'));
    await tester.pumpAndSettle();

    expect(updated, isNull);
    expect(find.textContaining('500'), findsOneWidget);
  });

  testWidgets('set due date sends UTC ISO due_at', (tester) async {
    tester.binding.platformDispatcher.localeTestValue = const Locale('en', 'US');
    addTearDown(() {
      tester.binding.platformDispatcher.clearLocaleTestValue();
    });

    String? patchBody;
    await tester.pumpWidget(
      buildActions(
        task: taskObject(),
        mock: MockClient((request) async {
          if (request.method == 'PATCH') {
            patchBody = request.body;
            return http.Response(
              jsonEncode({'object': taskJson(taskObject(dueAt: '2026-10-15T14:30:00Z'))}),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
      ),
    );

    await tester.tap(find.text('Редактировать'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Установить срок'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('15'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Сохранить'));
    await tester.pumpAndSettle();

    final payload = jsonDecode(patchBody!) as Map<String, dynamic>;
    expect(payload['due_at'], isNotNull);
    expect(payload['due_at'], isA<String>());
    expect(payload['due_at'].toString().contains('T'), isTrue);
  });

  testWidgets('change existing due date sends updated UTC due_at', (tester) async {
    tester.binding.platformDispatcher.localeTestValue = const Locale('en', 'US');
    addTearDown(() {
      tester.binding.platformDispatcher.clearLocaleTestValue();
    });

    String? patchBody;
    await tester.pumpWidget(
      buildActions(
        task: taskObject(dueAt: '2026-09-01T10:00:00Z'),
        mock: MockClient((request) async {
          if (request.method == 'PATCH') {
            patchBody = request.body;
            return http.Response(
              jsonEncode({'object': taskJson(taskObject(dueAt: '2026-09-01T11:00:00Z'))}),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
      ),
    );

    await tester.tap(find.text('Редактировать'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Установить срок'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('15'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Сохранить'));
    await tester.pumpAndSettle();

    final payload = jsonDecode(patchBody!) as Map<String, dynamic>;
    expect(payload['due_at'], isNotNull);
    expect(payload['due_at'], isNot('2026-09-01T10:00:00Z'));
  });

  testWidgets('set planned interval sends timezone-aware Object PATCH', (
    tester,
  ) async {
    tester.binding.platformDispatcher.localeTestValue = const Locale('en', 'US');
    addTearDown(() {
      tester.binding.platformDispatcher.clearLocaleTestValue();
    });

    String? path;
    String? patchBody;
    await tester.pumpWidget(
      buildActions(
        task: taskObject(),
        mock: MockClient((request) async {
          if (request.method == 'PATCH') {
            path = request.url.path;
            patchBody = request.body;
            return http.Response(
              jsonEncode(
                taskJson(
                  taskObject(
                    plannedStartAt: '2026-10-15T14:30:00Z',
                    plannedEndAt: '2026-10-15T15:30:00Z',
                  ),
                ),
              ),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
      ),
    );

    await tester.tap(find.text('Редактировать'));
    await tester.pumpAndSettle();
    expect(find.text('Запланированное время'), findsOneWidget);
    expect(find.text('Не задано'), findsOneWidget);
    await tester.tap(find.byKey(const Key('task_planned_interval_set')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('15'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Сохранить'));
    await tester.pumpAndSettle();

    expect(path, '/objects/task-1');
    final payload = jsonDecode(patchBody!) as Map<String, dynamic>;
    expect(payload['planned_start_at'], isA<String>());
    expect(payload['planned_end_at'], isA<String>());
    expect(payload['planned_start_at'].toString().contains('T'), isTrue);
    expect(payload.containsKey('due_at'), isFalse);
  });

  testWidgets('change planned interval sends updated instants', (tester) async {
    tester.binding.platformDispatcher.localeTestValue = const Locale('en', 'US');
    addTearDown(() {
      tester.binding.platformDispatcher.clearLocaleTestValue();
    });

    String? patchBody;
    await tester.pumpWidget(
      buildActions(
        task: taskObject(
          plannedStartAt: '2026-09-01T10:00:00Z',
          plannedEndAt: '2026-09-01T11:00:00Z',
        ),
        mock: MockClient((request) async {
          if (request.method == 'PATCH') {
            patchBody = request.body;
            return http.Response(
              jsonEncode(
                taskJson(
                  taskObject(
                    plannedStartAt: '2026-09-15T10:00:00Z',
                    plannedEndAt: '2026-09-15T11:00:00Z',
                  ),
                ),
              ),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
      ),
    );

    await tester.tap(find.text('Редактировать'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('task_planned_interval_set')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('15'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Сохранить'));
    await tester.pumpAndSettle();

    final payload = jsonDecode(patchBody!) as Map<String, dynamic>;
    expect(payload['planned_start_at'], isNot('2026-09-01T10:00:00Z'));
    expect(payload['planned_end_at'], isNotNull);
  });

  testWidgets('remove planned interval sends null pair', (tester) async {
    String? patchBody;
    await tester.pumpWidget(
      buildActions(
        task: taskObject(
          plannedStartAt: '2026-09-01T10:00:00Z',
          plannedEndAt: '2026-09-01T11:00:00Z',
        ),
        mock: MockClient((request) async {
          if (request.method == 'PATCH') {
            patchBody = request.body;
            return http.Response(
              jsonEncode(taskJson(taskObject())),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
      ),
    );

    await tester.tap(find.text('Редактировать'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('task_planned_interval_clear')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Сохранить'));
    await tester.pumpAndSettle();

    final payload = jsonDecode(patchBody!) as Map<String, dynamic>;
    expect(payload['planned_start_at'], isNull);
    expect(payload['planned_end_at'], isNull);
    expect(payload.containsKey('due_at'), isFalse);
  });
}
