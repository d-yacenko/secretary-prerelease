import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets('rooted identity review separates known and possible contacts', (tester) async {
    tester.view.physicalSize = const Size(1280, 1600);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var phase = 'review';
    final harness = GraphTestHarness(_client(phase: () => phase, onPhase: (next) => phase = next));
    harness.configure();
    await openGraph(tester, harness);
    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    expect(find.text('Возможные контакты'), findsNothing);
    expect(find.text('Отклонённые предложения'), findsNothing);
    expect(find.text('Подтвердить'), findsNothing);

    await tester.tap(find.text('Ada').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('В центр'));
    await tester.pumpAndSettle();

    expect(find.text('Известные контакты'), findsOneWidget);
    expect(find.text('Возможные контакты'), findsOneWidget);
    expect(find.text('Добавить email'), findsOneWidget);
    expect(find.text('Olga Volkova'), findsOneWidget);
    expect(find.textContaining('Email'), findsWidgets);
    expect(find.textContaining('ada@example.com'), findsOneWidget);
    expect(find.textContaining('Имя в источнике похоже на имя этого человека'), findsOneWidget);
    expect(find.text('Это не этот человек'), findsOneWidget);
    expect(find.text('Показаны не все возможные контакты'), findsOneWidget);
    expect(find.textContaining('конфликт'), findsOneWidget);
    expect(find.text('Подтвердить'), findsOneWidget);

    await tester.ensureVisible(find.text('Ada wrote'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Ada wrote'));
    await tester.pumpAndSettle();
    expect(find.text('Секретное тело'), findsOneWidget);

    Navigator.of(tester.element(find.text('Секретное тело'))).pop();
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Подтвердить'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Подтвердить'));
    await tester.pumpAndSettle();
    expect(phase, 'known');
    expect(find.text('ada@example.com'), findsWidgets);
    expect(find.text('Возможные контакты'), findsNothing);

    phase = 'review';
    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Ada').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('В центр'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Это не этот человек'));
    await tester.pumpAndSettle();
    expect(find.text('Возможные контакты'), findsNothing);
    expect(find.text('Отклонённые предложения'), findsOneWidget);
    expect(find.text('Вернуть'), findsOneWidget);

    await tester.tap(find.text('Вернуть'));
    await tester.pumpAndSettle();
    expect(find.text('Возможные контакты'), findsOneWidget);
    expect(find.text('Отклонённые предложения'), findsNothing);
  });

  testWidgets('empty candidate review stays quiet', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = GraphTestHarness(_client(phase: () => 'empty', onPhase: (_) {}));
    harness.configure();
    await openGraph(tester, harness);
    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Ada').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('В центр'));
    await tester.pumpAndSettle();
    expect(find.text('Известные контакты'), findsOneWidget);
    expect(find.text('Добавить email'), findsOneWidget);
    expect(find.text('Возможные контакты'), findsNothing);
    expect(find.text('Отклонённые предложения'), findsNothing);
  });
}

MockClient _client({required String Function() phase, required void Function(String next) onPhase}) {
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
      return jsonUtf8Response(
        graphWorkspaceJson(nodes: [graphObjectJson(id: 'task-home', title: 'Home')]),
      );
    }
    if (request.url.path == '/graph/people/person-ada/identity-correction') {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      onPhase(body['action'] == 'confirm'
          ? 'known'
          : body['action'] == 'reject'
              ? 'rejected'
              : 'review');
      return jsonUtf8Response({'person_id': 'person-ada'});
    }
    if (request.url.path == '/graph/people-workspace') {
      final root = request.url.queryParameters['root_id'];
      if (root == 'person-ada') {
        return jsonUtf8Response(_rooted(phase()));
      }
      return jsonUtf8Response(_overview());
    }
    if (request.url.path == '/objects/flow-ada') {
      return jsonUtf8Response(
        graphObjectJson(
          id: 'flow-ada',
          title: 'Ada wrote',
          kind: 'email',
          body: 'Секретное тело',
          provider: 'gmail',
        ),
      );
    }
    if (request.url.path == '/objects/flow-ada/neighbors') {
      return jsonUtf8Response({'object_id': 'flow-ada', 'neighbors': []});
    }
    if (request.url.path == '/objects/flow-ada/context') {
      return jsonUtf8Response({
        'object': graphObjectJson(
          id: 'flow-ada',
          title: 'Ada wrote',
          kind: 'email',
          body: 'Секретное тело',
          provider: 'gmail',
        ),
        'edges': [],
        'neighbors': [],
      });
    }
    if (request.url.path == '/objects/flow-ada/open-target') {
      return jsonUtf8Response({
        'available': false,
        'action': 'unavailable',
        'label': 'Открыть в источнике',
      });
    }
    if (request.url.path == '/objects/flow-ada/labels') {
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
    'people': [
      _person(
        rooted: false,
        candidates: const [],
        rejected: const [],
        identities: const [],
      ),
    ],
  };
}

Map<String, dynamic> _rooted(String phase) {
  final known = phase == 'known'
      ? [
          _identity('email', 'ada@example.com', 'effective', display: 'ada@example.com'),
        ]
      : [
          _identity('gmail', 'known@example.com', 'effective'),
        ];
  final candidates = phase == 'review'
      ? [
          _candidate(
            display: 'Olga Volkova',
            canonical: 'ada@example.com',
            confirmable: true,
            state: 'candidate',
            reasons: ['name_similarity'],
          ),
          _candidate(
            display: 'Other Person',
            canonical: 'owned@example.com',
            confirmable: false,
            state: 'conflicted',
            reasons: ['identity_conflict'],
          ),
        ]
      : phase == 'rejected'
          ? <Map<String, dynamic>>[]
          : <Map<String, dynamic>>[];
  final rejected = phase == 'rejected'
      ? [
          {
            'provider': 'email',
            'identity_type': 'email',
            'realm': '',
            'canonical_value': 'ada@example.com',
            'display_value': 'ada@example.com',
          },
        ]
      : <Map<String, dynamic>>[];
  return {
    'root_id': 'person-ada',
    'seed_ids': ['person-ada'],
    'nodes': [graphObjectJson(id: 'person-ada', title: 'Ada', kind: 'person')],
    'edges': [],
    'truncated': false,
    'people': [
      _person(
        rooted: true,
        candidates: phase == 'empty' ? const [] : candidates,
        rejected: rejected,
        identities: known,
        truncated: phase == 'review',
      ),
    ],
  };
}

Map<String, dynamic> _person({
  required bool rooted,
  required List<Map<String, dynamic>> candidates,
  required List<Map<String, dynamic>> rejected,
  required List<Map<String, dynamic>> identities,
  bool truncated = false,
}) {
  return {
    'person_id': 'person-ada',
    'title': 'Ada',
    'salience_score': 4,
    'identities': identities,
    'routes': const [],
    'identity_conflict': false,
    'open_task_count': 0,
    'recent_communication_count': 0,
    'task_involvement': const [],
    'recent_communications': const [],
    'salience': rooted
        ? {
            'score': 4,
            'tier': 'known',
            'components': const [],
            'truncated': false,
            'window_days': 90,
            'claims_object_importance': false,
          }
        : null,
    'identity_candidates': candidates,
    'identity_candidates_truncated': truncated,
    'rejected_identity_candidates': rejected,
  };
}

Map<String, dynamic> _identity(
  String provider,
  String value,
  String state, {
  String? display,
}) {
  return {
    'provider': provider,
    'identity_type': 'email',
    'display_value': display ?? value,
    'realm': '',
    'canonical_value': value,
    'state': state,
    'confirmable': false,
  };
}

Map<String, dynamic> _candidate({
  required String display,
  required String canonical,
  required bool confirmable,
  required String state,
  required List<String> reasons,
}) {
  return {
    'provider': 'email',
    'identity_type': 'email',
    'realm': '',
    'canonical_value': canonical,
    'display_value': display,
    'confirmable': confirmable,
    'state': state,
    'reasons': reasons,
    'assessment_resolution': null,
    'sources': confirmable
        ? [
            {
              'object_id': 'flow-ada',
              'kind': 'email',
              'provider': 'gmail',
              'title': 'Ada wrote',
              'occurred_at': '2026-09-01T12:00:00Z',
            },
          ]
        : const [],
  };
}
