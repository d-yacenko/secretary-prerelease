import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/account/account_screen.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/ui/object_presentation.dart';
import 'package:personal_secretary/ui/provider_icon.dart';
import 'package:url_launcher_platform_interface/link.dart';
import 'package:url_launcher_platform_interface/url_launcher_platform_interface.dart';

import 'account_test_helpers.dart';

Map<String, dynamic> _teamsJson({
  bool configured = true,
  bool connected = false,
  bool reconnectRequired = false,
  String? displayName,
  String? upn,
  String? tenantId,
}) {
  return {
    'configured': configured,
    'connected': connected,
    'reconnect_required': reconnectRequired,
    'display_name': displayName,
    'upn': upn,
    'tenant_id': tenantId,
  };
}

class _RecordingUrlLauncher extends UrlLauncherPlatform {
  String? lastUrl;
  PreferredLaunchMode? lastMode;

  @override
  LinkDelegate? get linkDelegate => null;

  @override
  Future<bool> launchUrl(String url, LaunchOptions options) async {
    lastUrl = url;
    lastMode = options.mode;
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

  test('Connections.fromJson defaults teams when omitted', () {
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
    expect(connections.teams.configured, isFalse);
    expect(connections.teams.connected, isFalse);
  });

  test('safe teams connection fields only', () {
    final connection = TeamsConnection.fromJson(
      _teamsJson(
        connected: true,
        displayName: 'Ada',
        upn: 'ada@contoso.com',
        tenantId: 'tenant-1',
      ),
    );
    expect(connection.configured, isTrue);
    expect(connection.connected, isTrue);
    expect(connection.displayName, 'Ada');
    expect(connection.upn, 'ada@contoso.com');
    expect(connection.tenantId, 'tenant-1');
    expect(connection.reconnectRequired, isFalse);
  });

  test('teams provider presentation', () {
    expect(providerLabel('teams'), 'Microsoft Teams');
    expect(providerCompactGlyph('teams'), 'Ms');
    expect(providerSourceMark('teams'), ProviderSourceMark.teams);
  });

  test('send_message approval label shows Teams compose identity', () {
    final action = PendingAction(
      toolName: 'send_message',
      arguments: {
        'provider': 'teams',
        'mode': 'reply',
        'body': 'Да, это действительно обидно',
        'route': {
          'chat_display_title': 'Petrushin',
        },
      },
    );
    expect(action.displayLabel, contains('Microsoft Teams'));
    expect(action.displayLabel, contains('Petrushin'));
    expect(action.displayLabel, contains('Ответ'));
    expect(action.displayLabel, contains('Да, это действительно обидно'));
  });

  testWidgets('unconfigured teams hides connect button', (tester) async {
    await pumpAccountReady(
      tester,
      buildAccountScreen(
        apiClient: buildAccountApiClient(),
        authController: _buildAuth(buildAccountApiClient()),
      ),
    );
    expect(find.textContaining('Microsoft Teams не настроен'), findsWidgets);
    expect(find.byKey(const Key('teams_connect_button')), findsNothing);
  });

  testWidgets('configured teams launches organizations OAuth URL', (tester) async {
    final launcher = _RecordingUrlLauncher();
    UrlLauncherPlatform.instance = launcher;
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path.endsWith('/connections')) {
          return http.Response(
            jsonEncode(accountConnectionsJson(teams: _teamsJson())),
            200,
          );
        }
        if (request.url.path.endsWith('/auth/teams/authorization-url')) {
          expect(request.method, 'POST');
          return http.Response(
            jsonEncode({
              'authorization_url':
                  'https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize?client_id=abc',
            }),
            200,
          );
        }
        if (isAccountSettingsRequest(request.url)) {
          return http.Response(jsonEncode(accountSettingsJson()), 200);
        }
        if (isAccountSourcePreferencesRequest(request.url)) {
          return http.Response(jsonEncode(accountSourcePreferencesJson()), 200);
        }
        if (isAccountIdentityRequest(request.url)) {
          return http.Response(jsonEncode(accountIdentityJson()), 200);
        }
        if (isAccountSemanticContextRequest(request.url)) {
          return http.Response(jsonEncode(accountSemanticContextJson()), 200);
        }
        return http.Response('{}', 404);
      }),
    );
    client.configure(baseUrl: 'https://secretary.example', token: 'opaque-test-token');
    await pumpAccountReady(
      tester,
      buildAccountScreen(
        apiClient: client,
        authController: _buildAuth(client),
        connectionsJson: accountConnectionsJson(teams: _teamsJson()),
      ),
    );
    expect(find.byKey(const Key('teams_connect_button')), findsOneWidget);
    await tester.ensureVisible(find.byKey(const Key('teams_connect_button')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('teams_connect_button')));
    for (var i = 0; i < 40; i++) {
      await tester.pump(const Duration(milliseconds: 50));
      if (launcher.lastUrl != null) {
        break;
      }
    }
    expect(
      launcher.lastUrl,
      contains('login.microsoftonline.com/organizations'),
    );
    expect(launcher.lastMode, PreferredLaunchMode.externalApplication);
  });

  test('reconnect required tells the user to reconnect', () {
    final connection = TeamsConnection.fromJson(
      _teamsJson(connected: true, reconnectRequired: true),
    );
    expect(connection.reconnectRequired, isTrue);
    expect(
      teamsConnectionLabel(connection),
      'Microsoft Teams: требуется повторное подключение',
    );
    expect(teamsSetupHelpText(connection), contains('Переподключите'));
    expect(teamsConnectButtonLabel(connection), 'Переподключить Microsoft Teams');
  });

  testWidgets('connected teams disconnect confirms and calls API', (tester) async {
    var disconnectCalled = false;
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path.endsWith('/connections')) {
          return http.Response(
            jsonEncode(
              accountConnectionsJson(
                teams: _teamsJson(
                  connected: true,
                  displayName: 'Ada',
                  upn: 'ada@contoso.com',
                ),
              ),
            ),
            200,
          );
        }
        if (request.url.path.endsWith('/auth/teams/disconnect')) {
          expect(request.method, 'POST');
          disconnectCalled = true;
          return http.Response(jsonEncode({'status': 'disconnected'}), 200);
        }
        if (isAccountSettingsRequest(request.url)) {
          return http.Response(jsonEncode(accountSettingsJson()), 200);
        }
        if (isAccountSourcePreferencesRequest(request.url)) {
          return http.Response(jsonEncode(accountSourcePreferencesJson()), 200);
        }
        if (isAccountIdentityRequest(request.url)) {
          return http.Response(jsonEncode(accountIdentityJson()), 200);
        }
        if (isAccountSemanticContextRequest(request.url)) {
          return http.Response(jsonEncode(accountSemanticContextJson()), 200);
        }
        return http.Response('{}', 404);
      }),
    );
    client.configure(baseUrl: 'https://secretary.example', token: 'opaque-test-token');
    await pumpAccountReady(
      tester,
      buildAccountScreen(
        apiClient: client,
        authController: _buildAuth(client),
        connectionsJson: accountConnectionsJson(
          teams: _teamsJson(
            connected: true,
            displayName: 'Ada',
            upn: 'ada@contoso.com',
          ),
        ),
      ),
    );
    expect(find.byKey(const Key('teams_disconnect_button')), findsOneWidget);
    await tester.ensureVisible(find.byKey(const Key('teams_disconnect_button')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('teams_disconnect_button')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('teams_disconnect_dialog')), findsOneWidget);
    expect(disconnectCalled, isFalse);
    await tester.tap(find.byKey(const Key('teams_disconnect_confirm')));
    await tester.pumpAndSettle();
    expect(disconnectCalled, isTrue);
  });
}
