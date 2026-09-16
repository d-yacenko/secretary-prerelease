import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/account/semantic_context_template.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';

import 'account_test_helpers.dart';

const _baseUrl = 'https://secretary.example';
const _token = 'opaque-test-token';

AuthController _auth(SecretaryApiClient apiClient) {
  final auth = AuthController(
    apiClient: apiClient,
    tokenStore: FakeTokenStore(),
    serverUrlStore: FakeServerUrlStore(),
  );
  auth.status = AuthStatus.authenticated;
  return auth;
}

void main() {
  testWidgets('loads and saves semantic context', (tester) async {
    String? saved;
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (isAccountSemanticContextRequest(request.url) &&
            request.method == 'PUT') {
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          saved = body['context_text'] as String;
          return http.Response.bytes(
            utf8.encode(jsonEncode(accountSemanticContextJson(contextText: saved!))),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        return http.Response('{}', 404);
      }),
    );
    client.configure(baseUrl: _baseUrl, token: _token);
    await pumpAccountReady(
      tester,
      buildAccountScreen(
        apiClient: client,
        authController: _auth(client),
        semanticContextJson: accountSemanticContextJson(
          contextText: 'Work: Acme',
        ),
      ),
    );
    await tester.scrollUntilVisible(
      find.byKey(const Key('account_semantic_context_section')),
      400,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('Контекст для Секретаря'), findsOneWidget);
    expect(find.textContaining(semanticContextExplanation.substring(0, 40)), findsOneWidget);
    final field = tester.widget<TextField>(
      find.byKey(const Key('semantic_context_text')),
    );
    expect(field.controller?.text, 'Work: Acme');
    await tester.enterText(
      find.byKey(const Key('semantic_context_text')),
      'Science: NLP',
    );
    await tester.tap(find.byKey(const Key('semantic_context_save')));
    await tester.pumpAndSettle();
    expect(saved, 'Science: NLP');
  });

  testWidgets('semantic context error state', (tester) async {
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (isAccountSemanticContextRequest(request.url)) {
          return http.Response('{"detail":"boom"}', 500);
        }
        return http.Response('{}', 404);
      }),
    );
    client.configure(baseUrl: _baseUrl, token: _token);
    await pumpAccountReady(
      tester,
      buildAccountScreen(
        apiClient: client,
        authController: _auth(client),
      ),
    );
    // initial context is empty via helper; force a save error.
    await tester.scrollUntilVisible(
      find.byKey(const Key('semantic_context_save')),
      400,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.byKey(const Key('semantic_context_save')));
    await tester.pumpAndSettle();
    expect(find.text('boom'), findsOneWidget);
  });
}
