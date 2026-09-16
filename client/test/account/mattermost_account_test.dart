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

import 'account_test_helpers.dart';
import 'package:personal_secretary/ui/object_presentation.dart';

const _baseUrl = 'https://secretary.example';
const _token = 'opaque-test-token';
const _pat = 'mattermost-personal-access-token-secret';

Map<String, dynamic> _connectionsJson({
  List<Map<String, dynamic>> mattermost = const [],
}) {
  return {
    'google': {
      'connected': true,
      'email': 'alice@gmail.com',
      'gmail_available': true,
      'calendar_available': false,
    },
    'yandex_mail': {'connected': false, 'email': null},
    'yandex_calendar': {'connected': false, 'email': null},
    'mattermost': mattermost,
  };
}

Map<String, dynamic> _mattermostAccountJson({
  String accountId = 'mm-acc-1',
  String serverUrl = 'https://mm.example.com',
  String username = 'alice',
  String? displayName = 'Alice',
}) {
  return {
    'account_id': accountId,
    'server_url': serverUrl,
    'remote_user_id': 'remote-1',
    'username': username,
    'display_name': displayName,
    'email': 'alice@example.com',
  };
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

Future<void> _pumpAccountReady(WidgetTester tester, Widget child) async {
  await pumpAccountReady(tester, child);
}

void main() {
  group('Mattermost API models', () {
    test('Connections parses multiple Mattermost accounts', () {
      final connections = Connections.fromJson(
        _connectionsJson(
          mattermost: [
            _mattermostAccountJson(accountId: 'a1', username: 'alice'),
            _mattermostAccountJson(
              accountId: 'a2',
              serverUrl: 'https://mm2.example.com',
              username: 'bob',
              displayName: 'Bob',
            ),
          ],
        ),
      );
      expect(connections.mattermost.length, 2);
      expect(connections.mattermost[0].accountId, 'a1');
      expect(connections.mattermost[1].serverUrl, 'https://mm2.example.com');
      expect(connections.google.connected, isTrue);
    });

    test('MattermostConnectResult does not expose PAT fields', () {
      final result = MattermostConnectResult.fromJson({
        'status': 'connected',
        ..._mattermostAccountJson(),
      });
      expect(result.status, 'connected');
      expect(result.accountId, 'mm-acc-1');
      expect(result.username, 'alice');
      expect(result.serverUrl, 'https://mm.example.com');
    });

    test('mattermostConnectionLabel formats compact display', () {
      final label = mattermostConnectionLabel(
        MattermostConnection.fromJson(_mattermostAccountJson()),
      );
      expect(label, 'Mattermost: Alice @ mm.example.com');
    });
  });

  group('SecretaryApiClient Mattermost', () {
    test('connectMattermost sends correct request body', () async {
      Map<String, dynamic>? body;
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          body = jsonDecode(request.body) as Map<String, dynamic>;
          return http.Response(
            jsonEncode({
              'status': 'connected',
              ..._mattermostAccountJson(),
            }),
            200,
          );
        }),
      );
      client.configure(baseUrl: _baseUrl, token: _token);
      final result = await client.connectMattermost(
        serverUrl: 'https://mm.example.com',
        accessToken: _pat,
      );
      expect(body!['server_url'], 'https://mm.example.com');
      expect(body!['access_token'], _pat);
      expect(result.username, 'alice');
      expect(result.serverUrl, 'https://mm.example.com');
    });
  });

  group('Mattermost provider presentation', () {
    test('uses M glyph and Mattermost label', () {
      expect(providerLabel('mattermost'), 'Mattermost');
      expect(providerCompactGlyph('mattermost'), 'M');
    });
  });

  group('AccountScreen Mattermost UX', () {
    testWidgets('renders connected Mattermost account', (tester) async {
      final client = buildAccountApiClient();
      client.configure(baseUrl: _baseUrl, token: _token);
      final auth = _buildAuth(client);

      await _pumpAccountReady(
        tester,
        buildAccountScreen(
          apiClient: client,
          authController: auth,
          connectionsJson: accountConnectionsJson(
            mattermost: [_mattermostAccountJson()],
          ),
        ),
      );

      expect(find.textContaining('Mattermost: Alice @ mm.example.com'), findsOneWidget);
      expect(find.text('Подключить Mattermost'), findsOneWidget);
      expect(find.textContaining('Google: подключено'), findsOneWidget);
    });

    testWidgets('connect button opens server and obscured PAT form', (tester) async {
      final client = buildAccountApiClient();
      client.configure(baseUrl: _baseUrl, token: _token);
      final auth = _buildAuth(client);

      await _pumpAccountReady(
        tester,
        buildAccountScreen(apiClient: client, authController: auth),
      );

      await tapAccountText(tester, 'Подключить Mattermost');
      await tester.pumpAndSettle();

      expect(find.text('Подключить Mattermost'), findsWidgets);
      expect(find.widgetWithText(TextField, 'Server URL'), findsOneWidget);
      expect(find.widgetWithText(TextField, 'Personal Access Token'), findsOneWidget);
      final patField = tester.widget<TextField>(
        find.widgetWithText(TextField, 'Personal Access Token'),
      );
      expect(patField.obscureText, isTrue);
    });

    testWidgets('successful connect reloads connections', (tester) async {
      var connectionsCalls = 0;
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.url.path.endsWith('/connections')) {
            connectionsCalls += 1;
            final mattermost = connectionsCalls >= 2
                ? [_mattermostAccountJson()]
                : <Map<String, dynamic>>[];
            return http.Response(jsonEncode(_connectionsJson(mattermost: mattermost)), 200);
          }
          if (request.url.path.endsWith('/connectors/mattermost/connect')) {
            return http.Response(
              jsonEncode({
                'status': 'connected',
                ..._mattermostAccountJson(),
              }),
              200,
            );
          }
          if (isAccountSettingsRequest(request.url)) {
            return http.Response(jsonEncode(accountSettingsJson()), 200);
          }
          return http.Response('{}', 404);
        }),
      );
      client.configure(baseUrl: _baseUrl, token: _token);
      final auth = _buildAuth(client);

      await _pumpAccountReady(
        tester,
        AccountScreen(apiClient: client, authController: auth),
      );
      await tapAccountText(tester, 'Подключить Mattermost');
      await tester.pumpAndSettle();

      await tester.enterText(
        find.widgetWithText(TextField, 'Server URL'),
        'https://mm.example.com',
      );
      await tester.enterText(
        find.widgetWithText(TextField, 'Personal Access Token'),
        _pat,
      );
      await tester.tap(find.widgetWithText(FilledButton, 'Подключить'));
      await tester.pump();
      for (var i = 0; i < 40; i++) {
        await tester.pump(const Duration(milliseconds: 50));
        if (find.textContaining('Mattermost: Alice @ mm.example.com').evaluate().isNotEmpty) {
          break;
        }
      }

      expect(connectionsCalls, greaterThanOrEqualTo(2));
      expect(find.textContaining('Mattermost: Alice @ mm.example.com'), findsOneWidget);
      expect(find.textContaining(_pat), findsNothing);
    });

    testWidgets('failed connect shows sanitized error without PAT', (tester) async {
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.url.path.endsWith('/connections')) {
            return http.Response(jsonEncode(_connectionsJson()), 200);
          }
          if (request.url.path.endsWith('/connectors/mattermost/connect')) {
            return http.Response(
              jsonEncode({'detail': 'mattermost unauthorized'}),
              401,
              headers: {'content-type': 'application/json'},
            );
          }
          if (isAccountSettingsRequest(request.url)) {
            return http.Response(jsonEncode(accountSettingsJson()), 200);
          }
          return http.Response('{}', 404);
        }),
      );
      client.configure(baseUrl: _baseUrl, token: _token);
      final auth = _buildAuth(client);

      await _pumpAccountReady(
        tester,
        buildAccountScreen(apiClient: client, authController: auth),
      );
      await tapAccountText(tester, 'Подключить Mattermost');
      await tester.pumpAndSettle();

      await tester.enterText(
        find.widgetWithText(TextField, 'Server URL'),
        'https://mm.example.com',
      );
      await tester.enterText(
        find.widgetWithText(TextField, 'Personal Access Token'),
        _pat,
      );
      await tester.tap(find.widgetWithText(FilledButton, 'Подключить'));
      await tester.pump();
      for (var i = 0; i < 40; i++) {
        await tester.pump(const Duration(milliseconds: 50));
        if (find.textContaining('mattermost unauthorized').evaluate().isNotEmpty) {
          break;
        }
      }

      expect(find.textContaining('mattermost unauthorized'), findsOneWidget);
      expect(find.textContaining(_pat), findsNothing);
    });

    testWidgets('duplicate submit disabled while request active', (tester) async {
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.url.path.endsWith('/connections')) {
            return http.Response(jsonEncode(_connectionsJson()), 200);
          }
          if (request.url.path.endsWith('/connectors/mattermost/connect')) {
            await Future<void>.delayed(const Duration(milliseconds: 200));
            return http.Response(
              jsonEncode({
                'status': 'connected',
                ..._mattermostAccountJson(),
              }),
              200,
            );
          }
          if (isAccountSettingsRequest(request.url)) {
            return http.Response(jsonEncode(accountSettingsJson()), 200);
          }
          return http.Response('{}', 404);
        }),
      );
      client.configure(baseUrl: _baseUrl, token: _token);
      final auth = _buildAuth(client);

      await _pumpAccountReady(
        tester,
        buildAccountScreen(apiClient: client, authController: auth),
      );
      await tapAccountText(tester, 'Подключить Mattermost');
      await tester.pumpAndSettle();

      await tester.enterText(
        find.widgetWithText(TextField, 'Server URL'),
        'https://mm.example.com',
      );
      await tester.enterText(
        find.widgetWithText(TextField, 'Personal Access Token'),
        _pat,
      );

      final connectButton = find.widgetWithText(FilledButton, 'Подключить');
      await tester.tap(connectButton);
      await tester.pump();

      final disabledButton = tester.widget<FilledButton>(connectButton);
      expect(disabledButton.onPressed, isNull);
      expect(find.byType(CircularProgressIndicator), findsOneWidget);

      await tester.pumpAndSettle();
    });
  });
}
