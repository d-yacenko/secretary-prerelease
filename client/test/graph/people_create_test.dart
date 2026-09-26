import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/graph/graph_workspace_screen.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets('Добавить человека is People-only and works on an empty workspace', (
    tester,
  ) async {
    await _openPeople(tester, _emptyPeople);
    expect(find.text('Добавить человека'), findsOneWidget);
    expect(find.text('Добавьте человека, чтобы начать.'), findsOneWidget);

    await tester.tap(find.text('Задачи'));
    await tester.pumpAndSettle();
    expect(find.text('Добавить человека'), findsNothing);
    expect(find.text('Graph task'), findsOneWidget);
  });

  testWidgets('blank name cannot submit and cancel sends no POST', (tester) async {
    final posts = <String>[];
    await _openPeople(tester, (request) async {
      if (request.method == 'POST' && request.url.path == '/graph/people') {
        posts.add(request.body);
      }
      return _emptyPeople(request);
    });
    await tester.tap(find.text('Добавить человека'));
    await tester.pumpAndSettle();
    expect(tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Добавить')).onPressed, isNull);

    await tester.enterText(_nameField, '   ');
    await tester.pump();
    expect(tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Добавить')).onPressed, isNull);

    await tester.tap(find.text('Отмена'));
    await tester.pumpAndSettle();
    expect(posts, isEmpty);
    expect(find.text('Имя'), findsNothing);
  });

  testWidgets('valid submit posts one trimmed title and reroots the created Person', (
    tester,
  ) async {
    final posts = <String>[];
    await _openPeople(tester, (request) async {
      if (request.method == 'POST' && request.url.path == '/graph/people') {
        posts.add(request.body);
        return jsonUtf8Response(graphObjectJson(id: 'person-new', title: 'Ada', kind: 'person'));
      }
      if (request.url.path == '/graph/people-workspace' &&
          request.url.queryParameters['root_id'] == 'person-new') {
        return jsonUtf8Response(
          _personWorkspace(personId: 'person-new', title: 'Ada', rootId: 'person-new'),
        );
      }
      return _emptyPeople(request);
    });
    await tester.tap(find.text('Добавить человека'));
    await tester.pumpAndSettle();
    await tester.enterText(_nameField, '  Ada  ');
    await tester.pump();
    await tester.tap(find.text('Добавить'));
    await tester.pumpAndSettle();

    expect(posts, ['{"title":"Ada"}']);
    expect(find.text('Ada'), findsWidgets);
    expect(find.text('Имя'), findsNothing);
  });

  testWidgets('in-flight submit cannot double-create', (tester) async {
    final gate = Completer<void>();
    var posts = 0;
    await _openPeople(tester, (request) async {
      if (request.method == 'POST' && request.url.path == '/graph/people') {
        posts += 1;
        await gate.future;
        return jsonUtf8Response(graphObjectJson(id: 'person-new', title: 'Ada', kind: 'person'));
      }
      return _emptyPeople(request);
    });
    await tester.tap(find.text('Добавить человека'));
    await tester.pumpAndSettle();
    await tester.enterText(_nameField, 'Ada');
    await tester.pump();
    await tester.tap(find.text('Добавить'));
    await tester.pump();
    expect(posts, 1);
    expect(tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Добавить')).onPressed, isNull);
    await tester.tap(find.text('Добавить'));
    await tester.pump();
    expect(posts, 1);
    gate.complete();
    await tester.pumpAndSettle();
  });

  testWidgets('server validation keeps the dialog and shows the error', (tester) async {
    await _openPeople(tester, (request) async {
      if (request.method == 'POST' && request.url.path == '/graph/people') {
        return http.Response(
          jsonEncode({'detail': 'person title is required'}),
          422,
          headers: {'content-type': 'application/json'},
        );
      }
      return _emptyPeople(request);
    });
    await tester.tap(find.text('Добавить человека'));
    await tester.pumpAndSettle();
    await tester.enterText(_nameField, 'Ada');
    await tester.pump();
    await tester.tap(find.text('Добавить'));
    await tester.pumpAndSettle();
    expect(find.text('person title is required'), findsOneWidget);
    expect(find.text('Имя'), findsOneWidget);
    expect(find.text('Добавить человека'), findsWidgets);
  });
}

final _nameField = find.descendant(
  of: find.byType(AlertDialog),
  matching: find.byType(TextField),
);

Future<void> _openPeople(
  WidgetTester tester,
  Future<http.Response> Function(http.Request request) handler,
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
        return jsonUtf8Response(
          graphWorkspaceJson(nodes: [graphObjectJson(id: 'task-1', title: 'Graph task')]),
        );
      }
      return handler(request);
    }),
  );
  harness.configure();
  await openGraph(tester, harness);
  await tester.tap(find.text('Люди'));
  await tester.pumpAndSettle();
}

Future<http.Response> _emptyPeople(http.Request request) async {
  if (request.url.path == '/graph/people-workspace') {
    return jsonUtf8Response({
      ...graphWorkspaceJson(nodes: []),
      'people': <Map<String, dynamic>>[],
    });
  }
  return http.Response('{}', 404);
}

Map<String, dynamic> _personWorkspace({
  required String personId,
  required String title,
  String? rootId,
}) {
  return {
    ...graphWorkspaceJson(
      rootId: rootId,
      nodes: [graphObjectJson(id: personId, title: title, kind: 'person')],
    ),
    'people': [
      {
        'person_id': personId,
        'title': title,
        'salience_score': 0,
        'identities': <Map<String, dynamic>>[],
        'routes': <Map<String, dynamic>>[],
        'identity_conflict': false,
        'open_task_count': 0,
        'recent_communication_count': 0,
      },
    ],
  };
}
