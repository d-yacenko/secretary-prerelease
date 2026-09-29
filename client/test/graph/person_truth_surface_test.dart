import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/graph/graph_workspace_controller.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets('rooted Person detail shows task, flow, and salience truth', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = GraphTestHarness(_client(empty: false));
    harness.configure();
    await openGraph(tester, harness);
    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Ada').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('В центр'));
    await tester.pumpAndSettle();

    expect(find.text('Известные контакты'), findsOneWidget);
    expect(find.text('Маршруты'), findsOneWidget);
    expect(find.textContaining('Просит выполнить'), findsOneWidget);
    expect(find.textContaining('Предложено секретарём'), findsOneWidget);
    expect(find.textContaining('Секретное тело'), findsNothing);
    expect(
      find.text('Сигнал активности и контекста, не оценка важности человека или сообщения.'),
      findsOneWidget,
    );
    expect(find.textContaining('Прямые диалоги: 8'), findsOneWidget);

    await tester.ensureVisible(find.text('Ask Ada'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Ask Ada'));
    await tester.pumpAndSettle();
    expect(harness.graph.mode, GraphWorkspaceMode.tasks);
    expect(harness.graph.rootId, 'task-ask');

    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Ada').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('В центр'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Hello Ada'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Hello Ada'));
    await tester.pumpAndSettle();
    expect(find.text('Секретное тело'), findsOneWidget);
  });

  testWidgets('rooted Person detail shows empty task and flow states', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = GraphTestHarness(_client(empty: true));
    harness.configure();
    await openGraph(tester, harness);
    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Ada').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('В центр'));
    await tester.pumpAndSettle();

    expect(find.text('Нет участия в текущих задачах'), findsOneWidget);
    expect(find.text('Нет недавних коммуникаций'), findsOneWidget);
    expect(find.text('Известные контакты'), findsOneWidget);
    expect(find.text('ada@example.com'), findsWidgets);
  });
}

MockClient _client({required bool empty}) {
  return MockClient((request) async {
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
      final root = request.url.queryParameters['root_id'];
      if (root == 'task-ask') {
        return jsonUtf8Response(
          graphWorkspaceJson(
            rootId: 'task-ask',
            nodes: [graphObjectJson(id: 'task-ask', title: 'Ask Ada')],
          ),
        );
      }
      return jsonUtf8Response(
        graphWorkspaceJson(nodes: [graphObjectJson(id: 'task-home', title: 'Home')]),
      );
    }
    if (request.url.path == '/graph/people-workspace') {
      final root = request.url.queryParameters['root_id'];
      if (root == 'person-ada') {
        return jsonUtf8Response(_rooted(empty: empty));
      }
      return jsonUtf8Response(_overview());
    }
    if (request.url.path == '/objects/flow-1') {
      return jsonUtf8Response(
        graphObjectJson(
          id: 'flow-1',
          title: 'Hello Ada',
          kind: 'email',
          body: 'Секретное тело',
          provider: 'gmail',
        ),
      );
    }
    if (request.url.path == '/objects/flow-1/neighbors') {
      return jsonUtf8Response({'object_id': 'flow-1', 'neighbors': []});
    }
    if (request.url.path == '/objects/flow-1/context') {
      return jsonUtf8Response({
        'object': graphObjectJson(
          id: 'flow-1',
          title: 'Hello Ada',
          kind: 'email',
          body: 'Секретное тело',
          provider: 'gmail',
        ),
        'edges': [],
        'neighbors': [],
      });
    }
    if (request.url.path == '/objects/flow-1/open-target') {
      return jsonUtf8Response({
        'available': false,
        'action': 'unavailable',
        'label': 'Открыть в источнике',
      });
    }
    if (request.url.path == '/objects/flow-1/labels') {
      return jsonUtf8Response({'labels': []});
    }
    return http.Response(jsonEncode({}), 404);
  });
}

Map<String, dynamic> _overview() {
  return {
    'root_id': null,
    'seed_ids': ['person-ada'],
    'nodes': [graphObjectJson(id: 'person-ada', title: 'Ada', kind: 'person')],
    'edges': [],
    'truncated': false,
    'people': [_person(empty: true, rooted: false)],
  };
}

Map<String, dynamic> _rooted({required bool empty}) {
  return {
    'root_id': 'person-ada',
    'seed_ids': ['person-ada'],
    'nodes': [graphObjectJson(id: 'person-ada', title: 'Ada', kind: 'person')],
    'edges': [],
    'truncated': false,
    'people': [_person(empty: empty, rooted: true)],
  };
}

Map<String, dynamic> _person({required bool empty, required bool rooted}) {
  return {
    'person_id': 'person-ada',
    'title': 'Ada',
    'salience_score': 12,
    'identities': [
      {
        'provider': 'gmail',
        'identity_type': 'email',
        'display_value': 'ada@example.com',
        'realm': '',
        'canonical_value': 'ada@example.com',
        'state': 'effective',
        'confirmable': false,
      },
    ],
    'routes': [
      {'provider': 'gmail', 'label': 'ada@example.com', 'route_key': 'email:ada@example.com'},
    ],
    'identity_conflict': false,
    'open_task_count': empty ? 0 : 2,
    'recent_communication_count': empty ? 0 : 1,
    'task_involvement': empty || !rooted
        ? []
        : [
            {
              'task_id': 'task-ask',
              'title': 'Ask Ada',
              'status': 'open',
              'completion_mode': 'finite',
              'due_at': '2026-09-02T10:00:00Z',
              'role': 'requested_by',
              'edge_state': 'confirmed',
              'edge_origin': 'user',
            },
            {
              'task_id': 'task-join',
              'title': 'Join Ada',
              'status': 'open',
              'completion_mode': 'finite',
              'due_at': null,
              'role': 'involves',
              'edge_state': 'proposed',
              'edge_origin': 'agent',
            },
          ],
    'recent_communications': empty || !rooted
        ? []
        : [
            {
              'object_id': 'flow-1',
              'kind': 'email',
              'provider': 'gmail',
              'title': 'Hello Ada',
              'occurred_at': '2026-09-01T12:00:00Z',
            },
          ],
    'salience': rooted
        ? {
            'score': 12,
            'tier': 'known',
            'components': [
              {'name': 'directness', 'value': 8},
            ],
            'truncated': false,
            'window_days': 90,
            'claims_object_importance': false,
          }
        : null,
  };
}
