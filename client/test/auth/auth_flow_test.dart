import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/app.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';

void main() {
  const baseUrl = 'https://secretary.example';
  const token = 'stored-token-value';

  String userMeJson() => jsonEncode({
        'id': 'user-1',
        'display_name': 'Alice',
        'created_at': '2026-01-01T00:00:00Z',
      });

  SecretaryApiClient buildApiClient(MockClient mock) {
    return SecretaryApiClient(httpClient: mock);
  }

  AuthController buildController({
    required SecretaryApiClient apiClient,
    required TokenStore tokenStore,
    required ServerUrlStore serverUrlStore,
  }) {
    return AuthController(
      apiClient: apiClient,
      tokenStore: tokenStore,
      serverUrlStore: serverUrlStore,
    );
  }

  testWidgets('no stored token shows auth setup', (tester) async {
    final tokenStore = FakeTokenStore();
    final serverUrlStore = FakeServerUrlStore();
    await serverUrlStore.writeServerUrl(baseUrl);

    final apiClient = buildApiClient(MockClient((request) async {
      return http.Response(userMeJson(), 200);
    }));
    final auth = buildController(
      apiClient: apiClient,
      tokenStore: tokenStore,
      serverUrlStore: serverUrlStore,
    );

    await tester.pumpWidget(PersonalSecretaryApp(authController: auth));
    await tester.pumpAndSettle();

    expect(find.text('Подключение к Secretary'), findsOneWidget);
    expect(find.text('Токен Bearer'), findsOneWidget);
  });

  testWidgets('valid token and successful /me reaches app shell', (tester) async {
    final tokenStore = FakeTokenStore();
    await tokenStore.writeToken(token);
    final serverUrlStore = FakeServerUrlStore();
    await serverUrlStore.writeServerUrl(baseUrl);

    final apiClient = buildApiClient(MockClient((request) async {
      if (request.url.path == '/inbox') {
        return http.Response(
          jsonEncode({
            'unresolved_notifications': [],
            'recent_source_objects': [],
            'source_sync_status': [],
          }),
          200,
        );
      }
      if (request.url.path == '/today') {
        return http.Response(
          jsonEncode({
            'date': '2026-08-28',
            'timezone': 'Europe/Amsterdam',
            'day_start': '2026-08-28T00:00:00+02:00',
            'tasks': [],
            'calendar_events': [],
            'notifications': [],
          }),
          200,
        );
      }
      return http.Response(userMeJson(), 200);
    }));
    final auth = buildController(
      apiClient: apiClient,
      tokenStore: tokenStore,
      serverUrlStore: serverUrlStore,
    );

    await tester.pumpWidget(PersonalSecretaryApp(authController: auth));
    await tester.pumpAndSettle();

    expect(find.text('Входящие'), findsWidgets);
    expect(find.text('Задача'), findsWidgets);
  });

  testWidgets('invalid token / 401 returns to auth setup', (tester) async {
    final tokenStore = FakeTokenStore();
    await tokenStore.writeToken(token);
    final serverUrlStore = FakeServerUrlStore();
    await serverUrlStore.writeServerUrl(baseUrl);

    final apiClient = buildApiClient(MockClient((request) async {
      return http.Response(jsonEncode({'detail': 'invalid token'}), 401);
    }));
    final auth = buildController(
      apiClient: apiClient,
      tokenStore: tokenStore,
      serverUrlStore: serverUrlStore,
    );

    await tester.pumpWidget(PersonalSecretaryApp(authController: auth));
    await tester.pumpAndSettle();

    expect(find.text('Подключение к Secretary'), findsOneWidget);
    expect(auth.status, AuthStatus.needsAuth);
  });

  test('temporary network error does not erase stored token', () async {
    final tokenStore = FakeTokenStore();
    await tokenStore.writeToken(token);
    final serverUrlStore = FakeServerUrlStore();
    await serverUrlStore.writeServerUrl(baseUrl);

    final apiClient = buildApiClient(MockClient((request) async {
      throw http.ClientException('connection refused');
    }));
    final auth = buildController(
      apiClient: apiClient,
      tokenStore: tokenStore,
      serverUrlStore: serverUrlStore,
    );

    await auth.initialize();
    expect(auth.status, AuthStatus.transientError);
    expect(await tokenStore.readToken(), token);
  });

  test('forget token removes local credential', () async {
    final tokenStore = FakeTokenStore();
    await tokenStore.writeToken(token);
    final serverUrlStore = FakeServerUrlStore();
    await serverUrlStore.writeServerUrl(baseUrl);

    final apiClient = buildApiClient(MockClient((request) async {
      return http.Response(userMeJson(), 200);
    }));
    final auth = buildController(
      apiClient: apiClient,
      tokenStore: tokenStore,
      serverUrlStore: serverUrlStore,
    );

    await auth.initialize();
    expect(auth.status, AuthStatus.authenticated);

    await auth.forgetToken();
    expect(await tokenStore.readToken(), isNull);
    expect(auth.status, AuthStatus.needsAuth);
  });
}
