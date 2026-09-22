import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/account/telegram_mtproto_account_section.dart';
import 'package:personal_secretary/ui/object_presentation.dart';
import 'package:personal_secretary/ui/provider_icon.dart';

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

  test('telegram provider presentation uses local icon', () {
    expect(providerLabel('telegram'), 'Telegram');
    expect(providerCompactGlyph('telegram'), 'T');
    expect(providerSourceMark('telegram'), ProviderSourceMark.telegram);
  });

  testWidgets('legacy telegram has no generic connection workflow', (tester) async {
    await pumpAccountReady(
      tester,
      buildAccountScreen(
        apiClient: buildAccountApiClient(),
        authController: _buildAuth(buildAccountApiClient()),
      ),
    );
    expect(find.byKey(const Key('telegram_connect_button')), findsNothing);
    expect(find.textContaining('Подключить Telegram'), findsNothing);
    expect(find.byType(TelegramMtprotoAccountSection), findsOneWidget);
  });

  testWidgets('configured legacy telegram has no actionable Bot workflow',
      (tester) async {
    await pumpAccountReady(
      tester,
      buildAccountScreen(
        apiClient: buildAccountApiClient(),
        authController: _buildAuth(buildAccountApiClient()),
      ),
    );
    expect(find.byKey(const Key('telegram_connect_button')), findsNothing);
    expect(find.textContaining('Секретарь получает только чаты'), findsNothing);
    expect(find.byType(TelegramMtprotoAccountSection), findsOneWidget);
  });

  test('send_message approval label shows telegram compose identity', () {
    final action = PendingAction(
      toolName: 'send_message',
      arguments: {
        'provider': 'telegram',
        'mode': 'compose',
        'body': 'Точное исходящее тело',
        'route': {
          'chat_display_name': 'Ivan',
          'chat_username': 'ivan',
        },
      },
    );
    expect(action.displayLabel, contains('Telegram'));
    expect(action.displayLabel, contains('Ivan'));
    expect(action.displayLabel, contains('Новое сообщение'));
    expect(action.displayLabel, contains('Точное исходящее тело'));
  });
}
