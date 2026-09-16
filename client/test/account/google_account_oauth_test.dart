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
import 'package:url_launcher_platform_interface/link.dart';
import 'package:url_launcher_platform_interface/url_launcher_platform_interface.dart';

import 'account_test_helpers.dart';

const _baseUrl = 'https://secretary.example';
const _token = 'opaque-test-token';

Map<String, dynamic> _connectionsJson({
  bool googleConnected = true,
  bool gmailAvailable = true,
  bool calendarAvailable = true,
  bool driveAvailable = false,
  List<Map<String, dynamic>> mattermost = const [],
}) {
  return {
    'google': {
      'connected': googleConnected,
      'email': 'alice@gmail.com',
      'gmail_available': gmailAvailable,
      'calendar_available': calendarAvailable,
      'drive_available': driveAvailable,
    },
    'yandex_mail': {'connected': false, 'email': null},
    'yandex_calendar': {'connected': false, 'email': null},
    'mattermost': mattermost,
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

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('Google OAuth API models', () {
    test('GoogleConnection parses drive_available', () {
      final google = GoogleConnection.fromJson({
        'connected': true,
        'email': 'alice@gmail.com',
        'gmail_available': true,
        'calendar_available': true,
        'drive_available': true,
      });
      expect(google.driveAvailable, isTrue);
    });

    test('googleOAuthButtonLabel reflects connection state', () {
      expect(
        googleOAuthButtonLabel(
          GoogleConnection(
            connected: false,
            gmailAvailable: false,
            calendarAvailable: false,
            driveAvailable: false,
          ),
        ),
        'Подключить Google',
      );
      expect(
        googleOAuthButtonLabel(
          GoogleConnection(
            connected: true,
            gmailAvailable: true,
            calendarAvailable: true,
            driveAvailable: false,
          ),
        ),
        'Разрешить Google Drive',
      );
      expect(
        googleOAuthButtonLabel(
          GoogleConnection(
            connected: true,
            gmailAvailable: true,
            calendarAvailable: true,
            driveAvailable: true,
          ),
        ),
        'Переподключить Google',
      );
    });
  });

  group('Account Google OAuth UI', () {
    test('connections json with drive available parses', () {
      final connections = Connections.fromJson(_connectionsJson(driveAvailable: true));
      expect(connections.google.driveAvailable, isTrue);
    });

    test('mock client returns connections', () async {
      final mock = MockClient((request) async {
        if (request.url.path.endsWith('/connections')) {
          return http.Response(
            jsonEncode(_connectionsJson(driveAvailable: true)),
            200,
          );
        }
        return http.Response('{}', 404);
      });
      final apiClient = SecretaryApiClient(httpClient: mock);
      apiClient.configure(baseUrl: _baseUrl, token: _token);
      final connections = await apiClient.getConnections();
      expect(connections.google.driveAvailable, isTrue);
    });

    late _RecordingUrlLauncher launcher;

    setUp(() {
      launcher = _RecordingUrlLauncher();
      UrlLauncherPlatform.instance = launcher;
    });

    testWidgets('shows Google Drive availability', (tester) async {
      final apiClient = buildAccountApiClient();
      apiClient.configure(baseUrl: _baseUrl, token: _token);

      await pumpAccountReady(
        tester,
        buildAccountScreen(
          apiClient: apiClient,
          authController: _buildAuth(apiClient),
          connectionsJson: _connectionsJson(driveAvailable: true),
        ),
      );

      expect(find.text('Google Drive доступен: подключено'), findsOneWidget);
      expect(find.text('Gmail доступен: подключено'), findsOneWidget);
      expect(find.text('Google Календарь доступен: подключено'), findsOneWidget);
    });

    testWidgets('missing Drive scope shows allow button', (tester) async {
      final apiClient = buildAccountApiClient();
      apiClient.configure(baseUrl: _baseUrl, token: _token);

      await _pumpAccountReady(
        tester,
        buildAccountScreen(
          apiClient: apiClient,
          authController: _buildAuth(apiClient),
        ),
      );

      expect(find.text('Google Drive доступен: не подключено'), findsOneWidget);
      expect(find.text('Разрешить Google Drive'), findsOneWidget);
    });

    testWidgets('button requests authorization URL and launches Google URL', (tester) async {
      String? authPath;
      final mock = MockClient((request) async {
        if (request.url.path.endsWith('/connections')) {
          return http.Response(jsonEncode(_connectionsJson()), 200);
        }
        if (request.url.path.endsWith('/auth/google/authorization-url')) {
          authPath = request.url.path;
          expect(request.method, 'POST');
          return http.Response(
            jsonEncode({
              'authorization_url':
                  'https://accounts.google.com/o/oauth2/v2/auth?scope=drive',
            }),
            200,
          );
        }
        if (isAccountSettingsRequest(request.url)) {
          return http.Response(jsonEncode(accountSettingsJson()), 200);
        }
        return http.Response('{}', 404);
      });
      final apiClient = buildAccountApiClient(
        connectionsJson: _connectionsJson(),
        httpClient: mock,
      );
      apiClient.configure(baseUrl: _baseUrl, token: _token);

      await _pumpAccountReady(
        tester,
        buildAccountScreen(
          apiClient: apiClient,
          authController: _buildAuth(apiClient),
        ),
      );

      await tapAccountText(tester, 'Разрешить Google Drive');
      for (var i = 0; i < 40; i++) {
        await tester.pump(const Duration(milliseconds: 50));
        if (authPath != null) {
          break;
        }
      }

      expect(authPath, isNotNull);
      expect(authPath!.contains('/auth/google/start'), isFalse);
      expect(launcher.lastUrl, contains('accounts.google.com'));
      expect(launcher.lastMode, PreferredLaunchMode.externalApplication);
    });

    testWidgets('resume refreshes connections', (tester) async {
      int connectionsCalls = 0;
      final mock = MockClient((request) async {
        if (request.url.path.endsWith('/connections')) {
          connectionsCalls += 1;
          final driveAvailable = connectionsCalls >= 2;
          return http.Response(
            jsonEncode(_connectionsJson(driveAvailable: driveAvailable)),
            200,
          );
        }
        if (isAccountSettingsRequest(request.url)) {
          return http.Response(jsonEncode(accountSettingsJson()), 200);
        }
        return http.Response('{}', 404);
      });
      final apiClient = SecretaryApiClient(httpClient: mock);
      apiClient.configure(baseUrl: _baseUrl, token: _token);

      await _pumpAccountReady(
        tester,
        AccountScreen(
          apiClient: apiClient,
          authController: _buildAuth(apiClient),
          initialSettings: UserSettings.fromJson(accountSettingsJson()),
        ),
      );

      expect(find.text('Google Drive доступен: не подключено'), findsOneWidget);

      final binding = tester.binding;
      binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
      binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
      binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pump();
      for (var i = 0; i < 40; i++) {
        await tester.pump(const Duration(milliseconds: 50));
        if (find.text('Google Drive доступен: подключено').evaluate().isNotEmpty) {
          break;
        }
      }

      expect(connectionsCalls, greaterThanOrEqualTo(2));
      expect(find.text('Google Drive доступен: подключено'), findsOneWidget);
    });
  });
}
