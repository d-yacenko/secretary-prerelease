import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';

import 'account_test_helpers.dart';

AuthController _buildAuth(SecretaryApiClient apiClient) {
  final auth = AuthController(
    apiClient: apiClient,
    tokenStore: FakeTokenStore(),
    serverUrlStore: FakeServerUrlStore(),
  );
  auth.status = AuthStatus.authenticated;
  auth.user = UserMe(
    id: 'user-1',
    displayName: 'Alice',
    createdAt: '2026-01-01T00:00:00Z',
  );
  return auth;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('Account layout polish', () {
    testWidgets('renders four major section headings', (tester) async {
      final client = buildAccountApiClient();
      await pumpAccountReady(
        tester,
        buildAccountScreen(
            apiClient: client, authController: _buildAuth(client)),
      );

      expect(find.text('Профиль'), findsOneWidget);
      expect(find.text('ИИ'), findsOneWidget);
      expect(find.text('Подключения'), findsOneWidget);
      expect(find.text('Синхронизация'), findsOneWidget);
    });

    testWidgets('five source rows still render', (tester) async {
      final client = buildAccountApiClient();
      await pumpAccountReady(
        tester,
        buildAccountScreen(
            apiClient: client, authController: _buildAuth(client)),
      );

      expect(find.byKey(const Key('source-preference-gmail')), findsOneWidget);
      expect(
        find.byKey(const Key('source-preference-google_calendar')),
        findsOneWidget,
      );
      expect(find.byKey(const Key('source-preference-yandex_mail')), findsOneWidget);
      expect(
        find.byKey(const Key('source-preference-yandex_calendar')),
        findsOneWidget,
      );
      expect(find.byKey(const Key('source-preference-mattermost')), findsOneWidget);
    });

    testWidgets('1280x768 renders without overflow', (tester) async {
      final binding = tester.binding;
      binding.window.physicalSizeTestValue = const Size(1280, 768);
      binding.window.devicePixelRatioTestValue = 1.0;
      addTearDown(binding.window.clearPhysicalSizeTestValue);
      addTearDown(binding.window.clearDevicePixelRatioTestValue);

      final client = buildAccountApiClient();
      await tester.pumpWidget(
        MaterialApp(
          home: buildAccountScreen(
            apiClient: client,
            authController: _buildAuth(client),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(tester.takeException(), isNull);
    });

    testWidgets('390x800 renders without overflow', (tester) async {
      final binding = tester.binding;
      binding.window.physicalSizeTestValue = const Size(390, 800);
      binding.window.devicePixelRatioTestValue = 1.0;
      addTearDown(binding.window.clearPhysicalSizeTestValue);
      addTearDown(binding.window.clearDevicePixelRatioTestValue);

      final client = buildAccountApiClient();
      await tester.pumpWidget(
        MaterialApp(
          home: buildAccountScreen(
            apiClient: client,
            authController: _buildAuth(client),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(tester.takeException(), isNull);
    });

    testWidgets('disconnect control is at the bottom of Account', (tester) async {
      final client = buildAccountApiClient();
      await pumpAccountReady(
        tester,
        buildAccountScreen(
          apiClient: client,
          authController: _buildAuth(client),
        ),
      );
      await tester.scrollUntilVisible(
        find.byKey(const Key('client_disconnect_button')),
        400,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.text('Отключить этот клиент'), findsOneWidget);
      expect(find.text('Забыть токен / отключить клиент'), findsNothing);
    });
  });
}
