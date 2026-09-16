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
import 'package:shared_preferences/shared_preferences.dart';

import 'account_test_helpers.dart';

const _baseUrl = 'https://secretary.example';
const _token = 'opaque-test-token';

Map<String, dynamic> _preferenceResponseJson({
  String source = 'gmail',
  bool enabled = true,
  int syncIntervalSeconds = 300,
  int defaultSyncIntervalSeconds = 300,
  int minSyncIntervalSeconds = 60,
  int maxSyncIntervalSeconds = 86400,
  int historyDays = 30,
  int defaultHistoryDays = 30,
  int minHistoryDays = 1,
  int maxHistoryDays = 90,
}) {
  return {
    'source': source,
    'enabled': enabled,
    'sync_interval_seconds': syncIntervalSeconds,
    'default_sync_interval_seconds': defaultSyncIntervalSeconds,
    'min_sync_interval_seconds': minSyncIntervalSeconds,
    'max_sync_interval_seconds': maxSyncIntervalSeconds,
    'history_days': historyDays,
    'default_history_days': defaultHistoryDays,
    'min_history_days': minHistoryDays,
    'max_history_days': maxHistoryDays,
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

Finder _gmailSourceRowFinder() =>
    find.byKey(const Key('source-preference-gmail'));

Finder _gmailSwitchFinder() {
  return find.descendant(
    of: _gmailSourceRowFinder(),
    matching: find.byType(Switch),
  );
}

Finder _gmailCadenceDropdownFinder() {
  return find.descendant(
    of: _gmailSourceRowFinder(),
    matching: find.byWidgetPredicate(
      (widget) => widget is DropdownButton<int> && widget.key == null,
    ),
  );
}

Finder _gmailHistoryDropdownFinder() {
  return find.byKey(const Key('source-history-dropdown-gmail'));
}

Finder _mattermostSourceRowFinder() =>
    find.byKey(const Key('source-preference-mattermost'));

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  group('Account source preferences UI', () {
    testWidgets('renders Синхронизация and five source labels', (tester) async {
      final client = buildAccountApiClient();
      await pumpAccountReady(
        tester,
        buildAccountScreen(
            apiClient: client, authController: _buildAuth(client)),
      );

      expect(find.text('Синхронизация'), findsOneWidget);
      expect(find.byKey(const Key('source-preference-gmail')), findsOneWidget);
      expect(
        find.byKey(const Key('source-preference-google_calendar')),
        findsOneWidget,
      );
      expect(find.byKey(const Key('source-preference-yandex_mail')),
          findsOneWidget);
      expect(
        find.byKey(const Key('source-preference-yandex_calendar')),
        findsOneWidget,
      );
      expect(find.byKey(const Key('source-preference-mattermost')),
          findsOneWidget);
    });

    testWidgets('disconnected source remains visible with Не подключено',
        (tester) async {
      final client = buildAccountApiClient(
        connectionsJson: accountConnectionsJson(
          googleConnected: false,
          gmailAvailable: false,
          calendarAvailable: false,
        ),
      );
      await pumpAccountReady(
        tester,
        buildAccountScreen(
            apiClient: client, authController: _buildAuth(client)),
      );

      expect(find.text('Gmail'), findsOneWidget);
      expect(find.text('Не подключено'), findsWidgets);
    });

    testWidgets('Gmail OFF sends exactly enabled false', (tester) async {
      Map<String, dynamic>? capturedBody;
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.method == 'PATCH' &&
              request.url.path.endsWith('/me/source-preferences/gmail')) {
            capturedBody =
                jsonDecode(request.body as String) as Map<String, dynamic>;
            return http.Response(
              jsonEncode(_preferenceResponseJson(enabled: false)),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
      );
      client.configure(baseUrl: _baseUrl, token: _token);

      await pumpAccountReady(
        tester,
        buildAccountScreen(
            apiClient: client, authController: _buildAuth(client)),
      );

      await tester.tap(_gmailSwitchFinder());
      await tester.pump();
      for (var i = 0; i < 30; i++) {
        await tester.pump(const Duration(milliseconds: 50));
        if (capturedBody != null) {
          break;
        }
      }

      expect(capturedBody, {'enabled': false});
    });

    testWidgets('successful toggle updates UI', (tester) async {
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.method == 'PATCH' &&
              request.url.path.endsWith('/me/source-preferences/gmail')) {
            return http.Response(
              jsonEncode(_preferenceResponseJson(enabled: false)),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
      );
      client.configure(baseUrl: _baseUrl, token: _token);

      await pumpAccountReady(
        tester,
        buildAccountScreen(
            apiClient: client, authController: _buildAuth(client)),
      );

      await tester.tap(_gmailSwitchFinder());
      await tester.pumpAndSettle();

      expect(
        find.descendant(
          of: _gmailSourceRowFinder(),
          matching: find.byWidgetPredicate(
            (widget) => widget is Switch && widget.value == false,
          ),
        ),
        findsOneWidget,
      );
    });

    testWidgets('failed toggle preserves old value and shows error',
        (tester) async {
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.method == 'PATCH' &&
              request.url.path.endsWith('/me/source-preferences/gmail')) {
            return http.Response(jsonEncode({'detail': 'toggle failed'}), 422);
          }
          return http.Response('{}', 404);
        }),
      );
      client.configure(baseUrl: _baseUrl, token: _token);

      await pumpAccountReady(
        tester,
        buildAccountScreen(
            apiClient: client, authController: _buildAuth(client)),
      );

      await tester.tap(_gmailSwitchFinder());
      await tester.pumpAndSettle();

      expect(
        find.descendant(
          of: _gmailSourceRowFinder(),
          matching: find.byWidgetPredicate(
            (widget) => widget is Switch && widget.value == true,
          ),
        ),
        findsOneWidget,
      );
      expect(find.text('toggle failed'), findsOneWidget);
    });

    testWidgets('cadence PATCH does not include enabled', (tester) async {
      Map<String, dynamic>? capturedBody;
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.method == 'PATCH' &&
              request.url.path.endsWith('/me/source-preferences/gmail')) {
            capturedBody =
                jsonDecode(request.body as String) as Map<String, dynamic>;
            return http.Response(
              jsonEncode(_preferenceResponseJson(syncIntervalSeconds: 120)),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
      );
      client.configure(baseUrl: _baseUrl, token: _token);

      await pumpAccountReady(
        tester,
        buildAccountScreen(
          apiClient: client,
          authController: _buildAuth(client),
          sourcePreferencesJson: accountSourcePreferencesJson(),
        ),
      );

      await tester.tap(_gmailCadenceDropdownFinder());
      await tester.pumpAndSettle();
      await tester.tap(find.text('2 мин').last);
      await tester.pump();
      for (var i = 0; i < 30; i++) {
        await tester.pump(const Duration(milliseconds: 50));
        if (capturedBody != null) {
          break;
        }
      }

      expect(capturedBody, {'sync_interval_seconds': 120});
      expect(capturedBody!.containsKey('enabled'), isFalse);
    });

    testWidgets('reset sends explicit null fields', (tester) async {
      Map<String, dynamic>? capturedBody;
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.method == 'PATCH' &&
              request.url.path.endsWith('/me/source-preferences/gmail')) {
            capturedBody =
                jsonDecode(request.body as String) as Map<String, dynamic>;
            return http.Response(
              jsonEncode(_preferenceResponseJson()),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
      );
      client.configure(baseUrl: _baseUrl, token: _token);

      await pumpAccountReady(
        tester,
        buildAccountScreen(
            apiClient: client, authController: _buildAuth(client)),
      );

      await tester.tap(
        find.descendant(
          of: _gmailSourceRowFinder(),
          matching: find.text('По умолчанию'),
        ),
      );
      await tester.pump();
      for (var i = 0; i < 30; i++) {
        await tester.pump(const Duration(milliseconds: 50));
        if (capturedBody != null) {
          break;
        }
      }

      expect(capturedBody, {
        'enabled': null,
        'sync_interval_seconds': null,
        'history_days': null,
      });
    });

    testWidgets('Gmail saving does not disable Mattermost controls',
        (tester) async {
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.method == 'PATCH' &&
              request.url.path.endsWith('/me/source-preferences/gmail')) {
            await Future<void>.delayed(const Duration(milliseconds: 200));
            return http.Response(
              jsonEncode(_preferenceResponseJson(enabled: false)),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
      );
      client.configure(baseUrl: _baseUrl, token: _token);

      await pumpAccountReady(
        tester,
        buildAccountScreen(
            apiClient: client, authController: _buildAuth(client)),
      );

      await tester.tap(_gmailSwitchFinder());
      await tester.pump(const Duration(milliseconds: 50));

      final mattermostSwitch = find.descendant(
        of: _mattermostSourceRowFinder(),
        matching: find.byType(Switch),
      );
      expect(tester.widget<Switch>(mattermostSwitch).onChanged, isNotNull);

      await tester.pumpAndSettle();
    });

    testWidgets('auth failure uses existing logout handling', (tester) async {
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.method == 'PATCH' &&
              request.url.path.endsWith('/me/source-preferences/gmail')) {
            return http.Response(jsonEncode({'detail': 'Unauthorized'}), 401);
          }
          return http.Response('{}', 404);
        }),
      );
      client.configure(baseUrl: _baseUrl, token: _token);
      final auth = _buildAuth(client);

      await pumpAccountReady(
        tester,
        buildAccountScreen(apiClient: client, authController: auth),
      );

      await tester.tap(_gmailSwitchFinder());
      await tester.pumpAndSettle();

      expect(auth.status, AuthStatus.needsAuth);
    });

    testWidgets('every row exposes history control', (tester) async {
      final client = buildAccountApiClient();
      await pumpAccountReady(
        tester,
        buildAccountScreen(
            apiClient: client, authController: _buildAuth(client)),
      );

      for (final source in supportedSourcePreferenceKeys) {
        expect(
          find.byKey(Key('source-history-dropdown-$source')),
          findsOneWidget,
        );
      }
    });

    testWidgets('Gmail history current 30 displays 30 дней', (tester) async {
      final client = buildAccountApiClient();
      await pumpAccountReady(
        tester,
        buildAccountScreen(
            apiClient: client, authController: _buildAuth(client)),
      );

      expect(find.text('30 дней'), findsWidgets);
    });

    testWidgets('Gmail change 30 to 7 sends exact history PATCH',
        (tester) async {
      Map<String, dynamic>? capturedBody;
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.method == 'PATCH' &&
              request.url.path.endsWith('/me/source-preferences/gmail')) {
            capturedBody =
                jsonDecode(request.body as String) as Map<String, dynamic>;
            return http.Response(
              jsonEncode(_preferenceResponseJson(historyDays: 7)),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
      );
      client.configure(baseUrl: _baseUrl, token: _token);

      await pumpAccountReady(
        tester,
        buildAccountScreen(
            apiClient: client, authController: _buildAuth(client)),
      );

      await tester.tap(_gmailHistoryDropdownFinder());
      await tester.pumpAndSettle();
      await tester.tap(find.text('7 дней').last);
      await tester.pump();
      for (var i = 0; i < 30; i++) {
        await tester.pump(const Duration(milliseconds: 50));
        if (capturedBody != null) {
          break;
        }
      }

      expect(capturedBody, {'history_days': 7});
      expect(capturedBody!.containsKey('enabled'), isFalse);
      expect(capturedBody!.containsKey('sync_interval_seconds'), isFalse);
    });

    testWidgets('successful history PATCH updates displayed value',
        (tester) async {
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.method == 'PATCH' &&
              request.url.path.endsWith('/me/source-preferences/gmail')) {
            return http.Response(
              jsonEncode(_preferenceResponseJson(historyDays: 7)),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
      );
      client.configure(baseUrl: _baseUrl, token: _token);

      await pumpAccountReady(
        tester,
        buildAccountScreen(
            apiClient: client, authController: _buildAuth(client)),
      );

      await tester.tap(_gmailHistoryDropdownFinder());
      await tester.pumpAndSettle();
      await tester.tap(find.text('7 дней').last);
      await tester.pumpAndSettle();

      expect(find.text('7 дней'), findsWidgets);
    });

    testWidgets('failed history PATCH keeps previous value and shows error',
        (tester) async {
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.method == 'PATCH' &&
              request.url.path.endsWith('/me/source-preferences/gmail')) {
            return http.Response(jsonEncode({'detail': 'history failed'}), 422);
          }
          return http.Response('{}', 404);
        }),
      );
      client.configure(baseUrl: _baseUrl, token: _token);

      await pumpAccountReady(
        tester,
        buildAccountScreen(
            apiClient: client, authController: _buildAuth(client)),
      );

      await tester.tap(_gmailHistoryDropdownFinder());
      await tester.pumpAndSettle();
      await tester.tap(find.text('7 дней').last);
      await tester.pumpAndSettle();

      expect(find.text('30 дней'), findsWidgets);
      expect(find.text('history failed'), findsOneWidget);
    });

    testWidgets('server bounds filter history presets', (tester) async {
      final preferencesJson = accountSourcePreferencesJson(
        minHistoryDays: 10,
        maxHistoryDays: 45,
      );
      final client = buildAccountApiClient(sourcePreferencesJson: preferencesJson);
      await pumpAccountReady(
        tester,
        buildAccountScreen(
          apiClient: client,
          authController: _buildAuth(client),
          sourcePreferencesJson: preferencesJson,
        ),
      );

      await tester.tap(_gmailHistoryDropdownFinder());
      await tester.pumpAndSettle();

      expect(find.text('1 день'), findsNothing);
      expect(find.text('3 дня'), findsNothing);
      expect(find.text('60 дней'), findsNothing);
      expect(find.text('14 дней'), findsWidgets);
      expect(find.text('30 дней'), findsWidgets);
    });

    testWidgets('non-preset current value 21 displays correctly',
        (tester) async {
      final preferencesJson = {
        'preferences': [
          accountSourcePreferenceEntryJson(
            source: 'gmail',
            historyDays: 21,
            defaultHistoryDays: 30,
          ),
          accountSourcePreferenceEntryJson(source: 'google_calendar'),
          accountSourcePreferenceEntryJson(source: 'yandex_mail'),
          accountSourcePreferenceEntryJson(source: 'yandex_calendar'),
          accountSourcePreferenceEntryJson(
            source: 'mattermost',
            historyDays: 14,
            defaultHistoryDays: 14,
          ),
        ],
      };
      final client = buildAccountApiClient(sourcePreferencesJson: preferencesJson);
      await pumpAccountReady(
        tester,
        buildAccountScreen(
          apiClient: client,
          authController: _buildAuth(client),
          sourcePreferencesJson: preferencesJson,
        ),
      );

      expect(find.text('21 день'), findsWidgets);
    });

    testWidgets('server default rendered from default_history_days',
        (tester) async {
      final preferencesJson = {
        'preferences': [
          accountSourcePreferenceEntryJson(
            source: 'gmail',
            historyDays: 14,
            defaultHistoryDays: 30,
          ),
          accountSourcePreferenceEntryJson(source: 'google_calendar'),
          accountSourcePreferenceEntryJson(source: 'yandex_mail'),
          accountSourcePreferenceEntryJson(source: 'yandex_calendar'),
          accountSourcePreferenceEntryJson(
            source: 'mattermost',
            historyDays: 14,
            defaultHistoryDays: 14,
          ),
        ],
      };
      final client = buildAccountApiClient(sourcePreferencesJson: preferencesJson);
      await pumpAccountReady(
        tester,
        buildAccountScreen(
          apiClient: client,
          authController: _buildAuth(client),
          sourcePreferencesJson: preferencesJson,
        ),
      );

      expect(
        find.descendant(
          of: _gmailSourceRowFinder(),
          matching: find.text('По умолчанию: 30 дней'),
        ),
        findsOneWidget,
      );
    });

    testWidgets('disconnected source still shows history control',
        (tester) async {
      final client = buildAccountApiClient(
        connectionsJson: accountConnectionsJson(
          googleConnected: false,
          gmailAvailable: false,
        ),
      );
      await pumpAccountReady(
        tester,
        buildAccountScreen(
            apiClient: client, authController: _buildAuth(client)),
      );

      expect(_gmailHistoryDropdownFinder(), findsOneWidget);
    });

    testWidgets('Gmail saving disables Gmail history control', (tester) async {
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.method == 'PATCH' &&
              request.url.path.endsWith('/me/source-preferences/gmail')) {
            await Future<void>.delayed(const Duration(milliseconds: 200));
            return http.Response(
              jsonEncode(_preferenceResponseJson(enabled: false)),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
      );
      client.configure(baseUrl: _baseUrl, token: _token);

      await pumpAccountReady(
        tester,
        buildAccountScreen(
            apiClient: client, authController: _buildAuth(client)),
      );

      await tester.tap(_gmailSwitchFinder());
      await tester.pump(const Duration(milliseconds: 50));

      final historyDropdown = tester.widget<DropdownButton<int>>(
        _gmailHistoryDropdownFinder(),
      );
      expect(historyDropdown.onChanged, isNull);

      await tester.pumpAndSettle();
    });

    testWidgets('progressive history wording without completed coverage claim',
        (tester) async {
      final client = buildAccountApiClient();
      await pumpAccountReady(
        tester,
        buildAccountScreen(
            apiClient: client, authController: _buildAuth(client)),
      );

      expect(
        find.text(
          'Изменение глубины истории применяется постепенно при синхронизации.',
        ),
        findsOneWidget,
      );
      expect(find.textContaining('загружено'), findsNothing);
    });
  });
}
