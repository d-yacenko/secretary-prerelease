import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_error.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'account_test_helpers.dart';

const _baseUrl = 'https://secretary.example';
const _token = 'opaque-test-token';

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

SecretaryApiClient _client(
  Map<String, dynamic> settingsJson, {
  List<Map<String, dynamic>>? patchBodies,
  Map<String, dynamic>? patchedSettingsJson,
}) {
  final client = SecretaryApiClient(
    httpClient: MockClient((request) async {
      if (request.url.path.endsWith('/connections')) {
        return http.Response(jsonEncode(accountConnectionsJson()), 200);
      }
      if (isAccountSettingsRequest(request.url)) {
        if (request.method == 'PATCH') {
          patchBodies?.add(jsonDecode(request.body) as Map<String, dynamic>);
          return http.Response(
            jsonEncode(patchedSettingsJson ?? settingsJson),
            200,
          );
        }
        return http.Response(jsonEncode(settingsJson), 200);
      }
      if (isAccountIdentityRequest(request.url)) {
        return http.Response(jsonEncode(accountIdentityJson()), 200);
      }
      if (isAccountSemanticContextRequest(request.url)) {
        return http.Response(jsonEncode(accountSemanticContextJson()), 200);
      }
      if (isAccountSourcePreferencesRequest(request.url)) {
        return http.Response(jsonEncode(accountSourcePreferencesJson()), 200);
      }
      return http.Response('{}', 404);
    }),
  );
  client.configure(baseUrl: _baseUrl, token: _token);
  return client;
}

Future<void> _scrollToLimitField(WidgetTester tester) async {
  final field = find.byKey(const Key('account_openai_daily_token_limit'));
  await tester.scrollUntilVisible(field, 200, scrollable: find.byType(Scrollable).first);
  await tester.pump();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  group('OpenAI daily token limit in Account', () {
    testWidgets('renders the current limit and today usage', (tester) async {
      final settingsJson = accountSettingsJson(
        openaiDailyTokenLimit: 500000,
        tokensUsedToday: 123456,
      );
      final client = _client(settingsJson);

      await pumpAccountReady(
        tester,
        buildAccountScreen(
          apiClient: client,
          authController: _buildAuth(client),
          settingsJson: settingsJson,
        ),
      );
      await _scrollToLimitField(tester);

      expect(
        find.widgetWithText(TextField, 'Дневной лимит OpenAI, токенов'),
        findsOneWidget,
      );
      final usage = tester.widget<Text>(
        find.byKey(const Key('account_openai_daily_budget_usage')),
      );
      expect(usage.data, 'Сегодня: 123\u00a0456 / 500\u00a0000 токенов');
      expect(
        find.byKey(const Key('account_openai_daily_budget_exhausted')),
        findsNothing,
      );
    });

    testWidgets('saving a new limit patches the settings API', (tester) async {
      final settingsJson = accountSettingsJson();
      final patchBodies = <Map<String, dynamic>>[];
      final client = _client(
        settingsJson,
        patchBodies: patchBodies,
        patchedSettingsJson: accountSettingsJson(openaiDailyTokenLimit: 250000),
      );

      await pumpAccountReady(
        tester,
        buildAccountScreen(
          apiClient: client,
          authController: _buildAuth(client),
          settingsJson: settingsJson,
        ),
      );
      await _scrollToLimitField(tester);

      await tester.enterText(
        find.byKey(const Key('account_openai_daily_token_limit')),
        '250000',
      );
      await tester.tap(
        find.byKey(const Key('account_openai_daily_token_limit_save')),
      );
      await tester.pumpAndSettle();

      expect(patchBodies, [
        {'openai_daily_token_limit': 250000},
      ]);
      expect(
        tester
            .widget<TextField>(
              find.byKey(const Key('account_openai_daily_token_limit')),
            )
            .controller
            ?.text,
        '250000',
      );
    });

    testWidgets('clearing the field disables the limit', (tester) async {
      final settingsJson = accountSettingsJson(openaiDailyTokenLimit: 250000);
      final patchBodies = <Map<String, dynamic>>[];
      final client = _client(
        settingsJson,
        patchBodies: patchBodies,
        patchedSettingsJson: accountSettingsJson(),
      );

      await pumpAccountReady(
        tester,
        buildAccountScreen(
          apiClient: client,
          authController: _buildAuth(client),
          settingsJson: settingsJson,
        ),
      );
      await _scrollToLimitField(tester);

      await tester.enterText(
        find.byKey(const Key('account_openai_daily_token_limit')),
        '',
      );
      await tester.tap(
        find.byKey(const Key('account_openai_daily_token_limit_save')),
      );
      await tester.pumpAndSettle();

      expect(patchBodies, [
        {'openai_daily_token_limit': null},
      ]);
    });

    testWidgets('exhausted budget is shown explicitly', (tester) async {
      final settingsJson = accountSettingsJson(
        openaiDailyTokenLimit: 1000,
        tokensUsedToday: 1200,
        budgetExhausted: true,
      );
      final client = _client(settingsJson);

      await pumpAccountReady(
        tester,
        buildAccountScreen(
          apiClient: client,
          authController: _buildAuth(client),
          settingsJson: settingsJson,
        ),
      );
      await _scrollToLimitField(tester);

      final message = tester.widget<Text>(
        find.byKey(const Key('account_openai_daily_budget_exhausted')),
      );
      expect(message.data, openAiDailyBudgetExhaustedMessage);
      final usage = tester.widget<Text>(
        find.byKey(const Key('account_openai_daily_budget_usage')),
      );
      expect(usage.data, 'Сегодня: 1\u00a0200 / 1\u00a0000 токенов');
    });
  });

  group('typed budget error rendering', () {
    test('budget code maps to a local message', () {
      final error = ServerException(
        'server text',
        openAiDailyBudgetExhaustedCode,
      );
      expect(
        localOpenAiDailyBudgetMessage(error),
        openAiDailyBudgetExhaustedMessage,
      );
    });

    test('other API errors keep their own message', () {
      expect(localOpenAiDailyBudgetMessage(ServerException('boom')), isNull);
    });
  });
}
