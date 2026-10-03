import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/graph/person_roles_section.dart';

void main() {
  test('card summary shows two roles and hides ids', () {
    final summary = personRoleCardSummary([
      _role(id: '11111111-1111-1111-1111-111111111111', text: 'директор'),
      _role(id: '22222222-2222-2222-2222-222222222222', text: 'студент'),
      _role(id: '33333333-3333-3333-3333-333333333333', text: 'оппонент'),
    ]);
    expect(summary, 'директор · студент +1');
    expect(summary, isNot(contains('11111111')));
    expect(personRoleCardSummary(const []), isNull);
  });

  test('assignment label keeps context and parses the API shape', () {
    final role = PersonRoleAssignment.fromJson({
      'id': 'a1',
      'person_id': 'p1',
      'role_term_id': 't1',
      'role_display_text': 'Директор',
      'context': 'Arenadata',
      'origin': 'user',
      'state': 'active',
    });
    expect(role.personId, 'p1');
    expect(role.label, 'Директор · Arenadata');
    final term = PersonRoleTerm.fromJson({'id': 't1', 'display_text': 'Директор'});
    expect(term.displayText, 'Директор');
    final search = PersonRoleTermSearch.fromJson({
      'terms': [
        {'id': 't1', 'display_text': 'Директор'},
      ],
      'exact_match_term_id': 't1',
    });
    expect(search.exactMatchTermId, 't1');
    expect(search.terms.single.displayText, 'Директор');
    final person = PersonPresentation.fromJson({
      'person_id': 'p1',
      'title': 'Иван',
      'salience_score': 0,
      'identities': [],
      'routes': [],
      'identity_conflict': false,
      'open_task_count': 0,
      'recent_communication_count': 0,
      'role_assignments': [
        {
          'id': 'a1',
          'person_id': 'p1',
          'role_term_id': 't1',
          'role_display_text': 'Директор',
          'context': null,
          'origin': 'user',
          'state': 'active',
        },
      ],
    });
    expect(person.roleAssignments.single.personId, 'p1');
    expect(person.roleAssignments.single.roleDisplayText, 'Директор');
  });

  testWidgets('existing suggestion is selectable and a new role is explicit', (tester) async {
    final posts = <Map<String, dynamic>>[];
    final api = _api((request) async {
      if (request.url.path.endsWith('/graph/person-role-terms')) {
        final query = request.url.queryParameters['q'] ?? '';
        final key = query.trim().replaceAll(RegExp(r'\s+'), ' ').toLowerCase();
        final terms = switch (key) {
          'ген' => [
            {'id': 't-general', 'display_text': 'генеральный директор'},
          ],
          'директор' => [
            {'id': 't-director', 'display_text': 'Директор'},
          ],
          _ => <Map<String, String>>[],
        };
        return _json({
          'terms': terms,
          'exact_match_term_id': key == 'директор' ? 't-director' : null,
        });
      }
      if (request.method == 'POST') {
        posts.add(jsonDecode(request.body) as Map<String, dynamic>);
        return _json({
          'id': 'a-new',
          'person_id': 'p1',
          'role_term_id': 't-new',
          'role_display_text': 'оппонент',
          'context': null,
          'origin': 'user',
          'state': 'active',
        });
      }
      return _json({});
    });
    var refreshed = 0;
    await tester.pumpWidget(
      _harness(
        person: _person(),
        api: api,
        onChanged: () async => refreshed += 1,
      ),
    );
    expect(find.byKey(const ValueKey('person-role-empty')), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('person-role-add')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('person-role-input')), 'ген');
    await tester.pumpAndSettle();
    expect(find.text('генеральный директор'), findsOneWidget);
    expect(find.byKey(const ValueKey('person-role-create')), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('person-role-suggestion-t-general')));
    await tester.pumpAndSettle();
    expect(posts.single['role'], 'генеральный директор');
    expect(refreshed, 1);

    await tester.tap(find.byKey(const ValueKey('person-role-add')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('person-role-input')), 'Директор');
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-role-create')), findsNothing);
    expect(find.byKey(const ValueKey('person-role-suggestion-t-director')), findsOneWidget);

    await tester.enterText(find.byKey(const ValueKey('person-role-input')), 'оппонент');
    await tester.enterText(find.byKey(const ValueKey('person-role-context')), 'МГУ');
    await tester.pumpAndSettle();
    expect(find.text('Создать роль «оппонент»'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('person-role-create')));
    await tester.pumpAndSettle();
    expect(posts.last['role'], 'оппонент');
    expect(posts.last['context'], 'МГУ');
  });

  testWidgets('a pending query drops the previous create action', (tester) async {
    final gates = <String, Completer<void>>{};
    final api = _searchApi(gates);
    await tester.pumpWidget(_harness(person: _person(), api: api, onChanged: () async {}));
    await tester.tap(find.byKey(const ValueKey('person-role-add')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('person-role-input')), 'оппонент');
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-role-create')), findsOneWidget);
    gates['Директор'] = Completer<void>();
    await tester.enterText(find.byKey(const ValueKey('person-role-input')), 'Директор');
    await tester.pump();
    expect(find.byKey(const ValueKey('person-role-create')), findsNothing);
    gates['Директор']!.complete();
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-role-create')), findsNothing);
  });

  testWidgets('a pending query does not invent create before the server answers', (tester) async {
    final gates = <String, Completer<void>>{};
    final api = _searchApi(gates);
    await tester.pumpWidget(_harness(person: _person(), api: api, onChanged: () async {}));
    await tester.tap(find.byKey(const ValueKey('person-role-add')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('person-role-input')), 'Директор');
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-role-create')), findsNothing);
    gates['оппонент'] = Completer<void>();
    await tester.enterText(find.byKey(const ValueKey('person-role-input')), 'оппонент');
    await tester.pump();
    expect(find.byKey(const ValueKey('person-role-create')), findsNothing);
    gates['оппонент']!.complete();
    await tester.pumpAndSettle();
    expect(find.text('Создать роль «оппонент»'), findsOneWidget);
  });

  testWidgets('pending query hides the previous suggestions', (tester) async {
    final gates = <String, Completer<void>>{};
    final api = _searchApi(gates);
    await tester.pumpWidget(_harness(person: _person(), api: api, onChanged: () async {}));
    await tester.tap(find.byKey(const ValueKey('person-role-add')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('person-role-input')), 'ген');
    await tester.pumpAndSettle();
    expect(find.text('генеральный директор'), findsOneWidget);
    gates['оппонент'] = Completer<void>();
    await tester.enterText(find.byKey(const ValueKey('person-role-input')), 'оппонент');
    await tester.pump();
    expect(find.text('генеральный директор'), findsNothing);
    expect(find.byKey(const ValueKey('person-role-suggestion-t-opponent')), findsNothing);
    expect(find.byKey(const ValueKey('person-role-create')), findsNothing);
    gates['оппонент']!.complete();
    await tester.pumpAndSettle();
    expect(find.text('генеральный директор'), findsNothing);
    expect(find.byKey(const ValueKey('person-role-suggestion-t-opponent')), findsOneWidget);
  });

  testWidgets('stale search cannot flip a newer exact-match decision', (tester) async {
    final gates = <String, Completer<void>>{};
    final api = _api((request) async {
      final query = request.url.queryParameters['q'] ?? '';
      final gate = gates[query];
      if (gate != null) {
        await gate.future;
      }
      if (query == 'Директор') {
        return _json({
          'terms': [
            {'id': 't-director', 'display_text': 'Директор'},
          ],
          'exact_match_term_id': 't-director',
        });
      }
      if (query == 'ген') {
        return _json({
          'terms': [
            {'id': 't-general', 'display_text': 'генеральный директор'},
          ],
          'exact_match_term_id': null,
        });
      }
      return _json({'terms': <Map<String, String>>[], 'exact_match_term_id': null});
    });
    await tester.pumpWidget(_harness(person: _person(), api: api, onChanged: () async {}));
    await tester.tap(find.byKey(const ValueKey('person-role-add')));
    await tester.pumpAndSettle();
    gates['ген'] = Completer<void>();
    gates['Директор'] = Completer<void>();
    await tester.enterText(find.byKey(const ValueKey('person-role-input')), 'ген');
    await tester.pump();
    await tester.enterText(find.byKey(const ValueKey('person-role-input')), 'Директор');
    await tester.pump();
    gates['Директор']!.complete();
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-role-create')), findsNothing);
    expect(find.byKey(const ValueKey('person-role-suggestion-t-director')), findsOneWidget);
    gates['ген']!.complete();
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-role-create')), findsNothing);
    expect(find.byKey(const ValueKey('person-role-suggestion-t-director')), findsOneWidget);
    expect(find.byKey(const ValueKey('person-role-suggestion-t-general')), findsNothing);
  });

  testWidgets('a failed search does not restore the previous query', (tester) async {
    final api = _api((request) async {
      final query = request.url.queryParameters['q'] ?? '';
      if (query == 'ген') {
        return _json({
          'terms': [
            {'id': 't-general', 'display_text': 'генеральный директор'},
          ],
          'exact_match_term_id': null,
        });
      }
      return http.Response('{"detail":"down"}', 500);
    });
    await tester.pumpWidget(_harness(person: _person(), api: api, onChanged: () async {}));
    await tester.tap(find.byKey(const ValueKey('person-role-add')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('person-role-input')), 'ген');
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-role-suggestion-t-general')), findsOneWidget);
    expect(find.byKey(const ValueKey('person-role-create')), findsOneWidget);
    await tester.enterText(find.byKey(const ValueKey('person-role-input')), 'оппонент');
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('person-role-suggestion-t-general')), findsNothing);
    expect(find.byKey(const ValueKey('person-role-create')), findsNothing);
  });

  testWidgets('retract refreshes and multiple roles render', (tester) async {
    final api = _api((request) async {
      expect(request.method, 'DELETE');
      expect(request.url.path, endsWith('/graph/people/p1/roles/a1'));
      return _json({
        'id': 'a1',
        'person_id': 'p1',
        'role_term_id': 't1',
        'role_display_text': 'директор',
        'context': 'Arenadata',
        'origin': 'user',
        'state': 'retracted',
      });
    });
    var refreshed = 0;
    await tester.pumpWidget(
      _harness(
        person: _person(
          roles: [
            _role(id: 'a1', text: 'директор', context: 'Arenadata'),
            _role(id: 'a2', text: 'студент'),
          ],
        ),
        api: api,
        onChanged: () async => refreshed += 1,
      ),
    );
    expect(find.text('директор · Arenadata'), findsOneWidget);
    expect(find.text('студент'), findsOneWidget);
    expect(find.byKey(const ValueKey('person-role-empty')), findsNothing);
    await tester.tap(find.byKey(const ValueKey('person-role-retract-a1')));
    await tester.pumpAndSettle();
    expect(refreshed, 1);
  });
}

PersonRoleAssignment _role({required String id, required String text, String? context}) {
  return PersonRoleAssignment(
    id: id,
    personId: 'p1',
    roleTermId: 'term-$id',
    roleDisplayText: text,
    context: context,
    origin: 'user',
    state: 'active',
  );
}

PersonPresentation _person({List<PersonRoleAssignment> roles = const []}) {
  return PersonPresentation(
    personId: 'p1',
    title: 'Иван',
    salienceScore: 0,
    identities: const [],
    routes: const [],
    identityConflict: false,
    openTaskCount: 0,
    recentCommunicationCount: 0,
    roleAssignments: roles,
  );
}

SecretaryApiClient _searchApi(Map<String, Completer<void>> gates) {
  return _api((request) async {
    final query = request.url.queryParameters['q'] ?? '';
    final gate = gates[query];
    if (gate != null) {
      await gate.future;
    }
    final key = query.trim().replaceAll(RegExp(r'\s+'), ' ').toLowerCase();
    if (key == 'директор') {
      return _json({
        'terms': [
          {'id': 't-director', 'display_text': 'Директор'},
        ],
        'exact_match_term_id': 't-director',
      });
    }
    if (key == 'ген') {
      return _json({
        'terms': [
          {'id': 't-general', 'display_text': 'генеральный директор'},
        ],
        'exact_match_term_id': null,
      });
    }
    if (key == 'оппонент') {
      return _json({
        'terms': [
          {'id': 't-opponent', 'display_text': 'оппонент'},
        ],
        'exact_match_term_id': null,
      });
    }
    return _json({'terms': <Map<String, String>>[], 'exact_match_term_id': null});
  });
}

SecretaryApiClient _api(MockClientHandler handler) {
  final api = SecretaryApiClient(httpClient: MockClient(handler));
  api.configure(baseUrl: 'http://localhost:8000', token: 'token');
  return api;
}

http.Response _json(Object body) {
  return http.Response(
    jsonEncode(body),
    200,
    headers: {'content-type': 'application/json; charset=utf-8'},
  );
}

Widget _harness({
  required PersonPresentation person,
  required SecretaryApiClient api,
  required Future<void> Function() onChanged,
}) {
  return MaterialApp(
    home: Scaffold(
      body: PersonRolesSection(person: person, apiClient: api, onChanged: onChanged),
    ),
  );
}
