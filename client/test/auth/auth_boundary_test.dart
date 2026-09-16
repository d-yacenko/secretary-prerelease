import 'dart:convert';

import 'package:flutter/material.dart';
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

  String userMeJson(String id, String name) => jsonEncode({
        'id': id,
        'display_name': name,
        'created_at': '2026-01-01T00:00:00Z',
      });

  AuthController buildAuth(MockClient mock, {
    required TokenStore tokenStore,
    required ServerUrlStore serverUrlStore,
  }) {
    return AuthController(
      apiClient: SecretaryApiClient(httpClient: mock),
      tokenStore: tokenStore,
      serverUrlStore: serverUrlStore,
    );
  }

  Future<void> pumpNarrowApp(
    WidgetTester tester,
    AuthController auth,
  ) async {
    tester.view.physicalSize = const Size(400, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(PersonalSecretaryApp(authController: auth));
    await tester.pumpAndSettle();
  }

  testWidgets('Capture 401 returns visible Auth Setup', (tester) async {
    final mock = MockClient((request) async {
      if (request.url.path.endsWith('/me')) {
        return http.Response(userMeJson('user-1', 'Alice'), 200);
      }
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
      if (request.url.path.endsWith('/capture/task')) {
        return http.Response(jsonEncode({'detail': 'invalid token'}), 401);
      }
      return http.Response('{}', 404);
    });

    final tokenStore = FakeTokenStore();
    await tokenStore.writeToken(token);
    final serverUrlStore = FakeServerUrlStore();
    await serverUrlStore.writeServerUrl(baseUrl);
    final auth = buildAuth(
      mock,
      tokenStore: tokenStore,
      serverUrlStore: serverUrlStore,
    );

    await pumpNarrowApp(tester, auth);

    await tester.tap(find.byType(FloatingActionButton));
    await tester.pumpAndSettle();

    expect(find.text('Создание задачи'), findsOneWidget);
    await tester.enterText(find.byType(TextField).first, 'do something');
    await tester.pump();
    await tester.tap(find.text('Создать задачу'));
    await tester.pump();
    await tester.pumpAndSettle();

    expect(find.text('Подключение к Secretary'), findsOneWidget);
    expect(find.text('Создание задачи'), findsNothing);
    expect(auth.status, AuthStatus.needsAuth);
    expect(auth.user, isNull);
  });

  testWidgets('Account /connections 401 returns visible Auth Setup', (tester) async {
    final mock = MockClient((request) async {
      if (request.url.path.endsWith('/me')) {
        return http.Response(userMeJson('user-1', 'Alice'), 200);
      }
      if (request.url.path.endsWith('/connections')) {
        return http.Response(jsonEncode({'detail': 'invalid token'}), 401);
      }
      return http.Response('{}', 404);
    });

    final tokenStore = FakeTokenStore();
    await tokenStore.writeToken(token);
    final serverUrlStore = FakeServerUrlStore();
    await serverUrlStore.writeServerUrl(baseUrl);
    final auth = buildAuth(
      mock,
      tokenStore: tokenStore,
      serverUrlStore: serverUrlStore,
    );

    await pumpNarrowApp(tester, auth);

    await tester.tap(find.byTooltip('Аккаунт'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));
    await tester.pumpAndSettle();

    expect(find.text('Подключение к Secretary'), findsOneWidget);
    expect(find.text('Аккаунт'), findsNothing);
    expect(auth.status, AuthStatus.needsAuth);
  });
}
