import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/account/account_labels_section.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';

import 'account_test_helpers.dart';

const _baseUrl = 'https://secretary.example';
const _token = 'opaque-test-token';

Map<String, dynamic> _label({
  String id = 'label-1',
  String title = 'Work',
  int count = 3,
  String? description,
}) {
  return {
    'id': id,
    'title': title,
    'object_count': count,
    'created_at': '2026-09-07T00:00:00Z',
    'updated_at': '2026-09-07T00:00:00Z',
    'description': description,
  };
}

AuthController _auth(SecretaryApiClient apiClient) {
  final auth = AuthController(
    apiClient: apiClient,
    tokenStore: FakeTokenStore(),
    serverUrlStore: FakeServerUrlStore(),
  );
  auth.status = AuthStatus.authenticated;
  return auth;
}

Future<void> _pumpSection(WidgetTester tester, MockClient mock) async {
  final apiClient = SecretaryApiClient(httpClient: mock);
  apiClient.configure(baseUrl: _baseUrl, token: _token);
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: AccountLabelsSection(
          apiClient: apiClient,
          authController: _auth(apiClient),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('Account shows labels section', (tester) async {
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path.endsWith('/labels')) {
          return http.Response(jsonEncode({'labels': [_label()]}), 200);
        }
        if (request.url.path.endsWith('/connections')) {
          return http.Response(jsonEncode(accountConnectionsJson()), 200);
        }
        if (isAccountSettingsRequest(request.url)) {
          return http.Response(jsonEncode(accountSettingsJson()), 200);
        }
        if (isAccountIdentityRequest(request.url)) {
          return http.Response(jsonEncode(accountIdentityJson()), 200);
        }
        if (isAccountSourcePreferencesRequest(request.url)) {
          return http.Response(jsonEncode(accountSourcePreferencesJson()), 200);
        }
        return http.Response('{}', 404);
      }),
    );
    client.configure(baseUrl: _baseUrl, token: _token);
    await pumpAccountReady(
      tester,
      buildAccountScreen(apiClient: client, authController: _auth(client)),
    );
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.byKey(const Key('account_labels_section')),
      400,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.byKey(const Key('account_labels_section')), findsOneWidget);
    expect(find.text('Метки'), findsWidgets);
    await tester.scrollUntilVisible(
      find.text('Work'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('Work'), findsOneWidget);
    expect(find.text('объектов: 3'), findsOneWidget);
  });

  testWidgets('loading then empty state', (tester) async {
    await _pumpSection(
      tester,
      MockClient((request) async {
        return http.Response(jsonEncode({'labels': []}), 200);
      }),
    );
    expect(find.text('Нет меток'), findsOneWidget);
  });

  testWidgets('error state', (tester) async {
    await _pumpSection(
      tester,
      MockClient((request) async {
        return http.Response('{"detail":"boom"}', 500);
      }),
    );
    expect(find.text('boom'), findsOneWidget);
    expect(find.text('Повторить'), findsOneWidget);
  });

  testWidgets('create label', (tester) async {
    var created = false;
    await _pumpSection(
      tester,
      MockClient((request) async {
        if (request.method == 'GET') {
          return http.Response(
            jsonEncode({'labels': created ? [_label()] : []}),
            200,
          );
        }
        created = true;
        return http.Response(
          jsonEncode({'label': _label(), 'created': true}),
          200,
        );
      }),
    );
    await tester.tap(find.byKey(const Key('account_create_label')));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(FilledButton, 'Создать'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('label_dialog_name')), '  Work  ');
    await tester.pump();
    await tester.tap(find.widgetWithText(FilledButton, 'Создать'));
    await tester.pumpAndSettle();
    expect(find.text('Work'), findsOneWidget);
  });

  testWidgets('created=false does not duplicate', (tester) async {
    await _pumpSection(
      tester,
      MockClient((request) async {
        if (request.method == 'GET') {
          return http.Response(jsonEncode({'labels': [_label()]}), 200);
        }
        return http.Response(
          jsonEncode({'label': _label(title: 'Work'), 'created': false}),
          200,
        );
      }),
    );
    await tester.tap(find.byKey(const Key('account_create_label')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('label_dialog_name')), 'work');
    await tester.tap(find.widgetWithText(FilledButton, 'Создать'));
    await tester.pumpAndSettle();
    expect(find.text('Work'), findsOneWidget);
  });

  testWidgets('rename label', (tester) async {
    await _pumpSection(
      tester,
      MockClient((request) async {
        if (request.method == 'GET') {
          return http.Response(jsonEncode({'labels': [_label()]}), 200);
        }
        expect(request.method, 'PATCH');
        return http.Response(
          jsonEncode({
            'label': _label(title: 'Office'),
            'changed': true,
          }),
          200,
        );
      }),
    );
    await tester.tap(find.byTooltip('Переименовать'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('label_dialog_name')), 'Office');
    await tester.tap(find.widgetWithText(FilledButton, 'Сохранить'));
    await tester.pumpAndSettle();
    expect(find.text('Office'), findsOneWidget);
  });

  testWidgets('rename conflict presentation', (tester) async {
    await _pumpSection(
      tester,
      MockClient((request) async {
        if (request.method == 'GET') {
          return http.Response(
            jsonEncode({
              'labels': [
                _label(),
                _label(id: 'label-2', title: 'Office', count: 0),
              ],
            }),
            200,
          );
        }
        return http.Response(
          '{"detail":"an active label with this name already exists"}',
          409,
        );
      }),
    );
    await tester.tap(find.byTooltip('Переименовать').first);
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('label_dialog_name')), 'Office');
    await tester.tap(find.widgetWithText(FilledButton, 'Сохранить'));
    await tester.pumpAndSettle();
    expect(find.text('Метка с таким именем уже существует.'), findsOneWidget);
  });

  testWidgets('delete confirmation removes label', (tester) async {
    var deleted = false;
    await _pumpSection(
      tester,
      MockClient((request) async {
        if (request.method == 'GET') {
          return http.Response(
            jsonEncode({'labels': deleted ? [] : [_label()]}),
            200,
          );
        }
        deleted = true;
        return http.Response(
          jsonEncode({'label': _label(), 'changed': true}),
          200,
        );
      }),
    );
    await tester.tap(find.byTooltip('Удалить'));
    await tester.pumpAndSettle();
    expect(
      find.textContaining('Метка будет удалена из Секретаря'),
      findsOneWidget,
    );
    expect(
      find.textContaining('Объекты и данные источников удалены не будут'),
      findsOneWidget,
    );
    await tester.tap(find.widgetWithText(FilledButton, 'Удалить'));
    await tester.pumpAndSettle();
    expect(find.text('Work'), findsNothing);
  });

  testWidgets('shows description under title', (tester) async {
    await _pumpSection(
      tester,
      MockClient((request) async {
        return http.Response(
          jsonEncode({
            'labels': [_label(description: 'commercial work')],
          }),
          200,
        );
      }),
    );
    expect(find.text('commercial work'), findsOneWidget);
  });

  testWidgets('create label with description', (tester) async {
    Map<String, dynamic>? createdBody;
    await _pumpSection(
      tester,
      MockClient((request) async {
        if (request.method == 'GET') {
          return http.Response(jsonEncode({'labels': []}), 200);
        }
        createdBody = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(
          jsonEncode({
            'label': _label(description: 'when to use'),
            'created': true,
          }),
          200,
        );
      }),
    );
    await tester.tap(find.byKey(const Key('account_create_label')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('label_dialog_name')), 'Work');
    await tester.enterText(
      find.byKey(const Key('label_dialog_description')),
      'when to use',
    );
    await tester.tap(find.widgetWithText(FilledButton, 'Создать'));
    await tester.pumpAndSettle();
    expect(createdBody?['name'], 'Work');
    expect(createdBody?['description'], 'when to use');
    expect(find.text('when to use'), findsOneWidget);
  });
}
