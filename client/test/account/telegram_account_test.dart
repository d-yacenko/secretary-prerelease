import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/account/account_screen.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/ui/object_presentation.dart';
import 'package:personal_secretary/ui/provider_icon.dart';
import 'package:url_launcher_platform_interface/link.dart';
import 'package:url_launcher_platform_interface/url_launcher_platform_interface.dart';

import 'account_test_helpers.dart';

Map<String, dynamic> _telegramJson({
  bool configured = true,
  bool identityLinked = false,
  bool businessConnected = false,
  bool canReply = false,
  String? username,
  String? displayName,
  String? botUsername = 'secretary_bot',
}) {
  return {
    'configured': configured,
    'identity_linked': identityLinked,
    'business_connected': businessConnected,
    'can_reply': canReply,
    'telegram_username': username,
    'display_name': displayName,
    'bot_username': botUsername,
  };
}

class _RecordingUrlLauncher extends UrlLauncherPlatform {
  String? lastUrl;

  @override
  LinkDelegate? get linkDelegate => null;

  @override
  Future<bool> launchUrl(String url, LaunchOptions options) async {
    lastUrl = url;
    return true;
  }
}

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

  test('TelegramConnection parses safe status only', () {
    final connection = TelegramConnection.fromJson(_telegramJson(
      identityLinked: true,
      businessConnected: true,
      canReply: true,
      username: 'alice',
      displayName: 'Alice',
    ));
    expect(connection.configured, isTrue);
    expect(connection.identityLinked, isTrue);
    expect(connection.businessConnected, isTrue);
    expect(connection.canReply, isTrue);
    expect(connection.telegramUsername, 'alice');
    expect(connection.displayName, 'Alice');
    expect(connection.botUsername, 'secretary_bot');
  });

  test('Connections.fromJson defaults telegram when omitted', () {
    final connections = Connections.fromJson({
      'google': {
        'connected': false,
        'email': null,
        'gmail_available': false,
        'calendar_available': false,
        'drive_available': false,
      },
      'yandex_mail': {'connected': false, 'email': null},
      'yandex_calendar': {'connected': false, 'email': null},
      'mattermost': [],
    });
    expect(connections.telegram.configured, isFalse);
  });

  test('telegram connection labels distinguish states', () {
    expect(
      telegramConnectionLabel(TelegramConnection.unavailable()),
      contains('не настроен'),
    );
    expect(
      telegramConnectionLabel(
        TelegramConnection.fromJson(_telegramJson()),
      ),
      contains('не связан'),
    );
    expect(
      telegramConnectionLabel(
        TelegramConnection.fromJson(_telegramJson(identityLinked: true)),
      ),
      contains('Secretary Mode'),
    );
    expect(
      telegramConnectionLabel(
        TelegramConnection.fromJson(
          _telegramJson(identityLinked: true, businessConnected: true),
        ),
      ),
      contains('без права ответа'),
    );
    expect(
      telegramConnectionLabel(
        TelegramConnection.fromJson(
          _telegramJson(
            identityLinked: true,
            businessConnected: true,
            canReply: true,
          ),
        ),
      ),
      contains('можно отвечать'),
    );
    expect(
      telegramSetupHelpText(TelegramConnection.unavailable()),
      contains('mute'),
    );
  });

  test('telegram provider presentation uses local icon', () {
    expect(providerLabel('telegram'), 'Telegram');
    expect(providerCompactGlyph('telegram'), 'T');
    expect(providerSourceMark('telegram'), ProviderSourceMark.telegram);
  });

  testWidgets('unconfigured telegram hides link button', (tester) async {
    await pumpAccountReady(
      tester,
      buildAccountScreen(
        apiClient: buildAccountApiClient(),
        authController: _buildAuth(buildAccountApiClient()),
      ),
    );
    expect(find.textContaining('Telegram не настроен'), findsWidgets);
    expect(find.byKey(const Key('telegram_connect_button')), findsNothing);
  });

  testWidgets('configured telegram starts deep link on resume refresh',
      (tester) async {
    final launcher = _RecordingUrlLauncher();
    UrlLauncherPlatform.instance = launcher;
    var connectionsCalls = 0;
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path.endsWith('/connections')) {
          connectionsCalls += 1;
          return http.Response(
            jsonEncode(accountConnectionsJson(telegram: _telegramJson())),
            200,
          );
        }
        if (request.url.path.endsWith('/telegram/link')) {
          expect(request.method, 'POST');
          return http.Response(
            jsonEncode({
              'telegram_url': 'https://t.me/secretary_bot?start=abc_state',
              'expires_at': '2026-09-13T12:00:00Z',
            }),
            200,
          );
        }
        if (request.url.path.endsWith('/me/settings')) {
          return http.Response(jsonEncode(accountSettingsJson()), 200);
        }
        if (request.url.path.endsWith('/me/source-preferences')) {
          return http.Response(jsonEncode(accountSourcePreferencesJson()), 200);
        }
        if (request.url.path.endsWith('/me/identity')) {
          return http.Response(jsonEncode(accountIdentityJson()), 200);
        }
        if (request.url.path.endsWith('/me/semantic-context')) {
          return http.Response(jsonEncode(accountSemanticContextJson()), 200);
        }
        if (request.url.path.endsWith('/labels')) {
          return http.Response(jsonEncode({'labels': []}), 200);
        }
        return http.Response('{}', 404);
      }),
    );
    client.configure(baseUrl: 'https://secretary.example', token: 'tok');
    final auth = _buildAuth(client);
    await pumpAccountReady(
      tester,
      AccountScreen(apiClient: client, authController: auth),
    );
    expect(find.byKey(const Key('telegram_connect_button')), findsOneWidget);
    expect(find.textContaining('Секретарь получает только чаты'), findsOneWidget);
    await tester.tap(find.byKey(const Key('telegram_connect_button')));
    await tester.pumpAndSettle();
    expect(launcher.lastUrl, 'https://t.me/secretary_bot?start=abc_state');

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(connectionsCalls, greaterThan(1));
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
