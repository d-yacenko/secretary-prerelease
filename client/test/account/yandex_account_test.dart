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

const _baseUrl = 'https://secretary.example';
const _token = 'opaque-test-token';
const _mailPassword = 'sk-testPhase28bD2MailSecret';
const _calendarPassword = 'sk-testPhase28bD2CalendarSecret';

Map<String, dynamic> _connectionsJson({
  bool yandexMailConnected = false,
  bool yandexCalendarConnected = false,
  String? yandexMailEmail,
  String? yandexCalendarEmail,
}) {
  return {
    'google': {
      'connected': false,
      'email': null,
      'gmail_available': false,
      'calendar_available': false,
      'drive_available': false,
    },
    'yandex_mail': {
      'connected': yandexMailConnected,
      'email': yandexMailEmail,
    },
    'yandex_calendar': {
      'connected': yandexCalendarConnected,
      'email': yandexCalendarEmail,
    },
    'mattermost': [],
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
  group('Yandex API models', () {
    test('yandexConnectButtonLabel reflects connection state', () {
      final disconnected = Connections.fromJson(_connectionsJson());
      expect(yandexConnectButtonLabel(disconnected), 'Подключить Яндекс');

      final connected = Connections.fromJson(
        _connectionsJson(
          yandexMailConnected: true,
          yandexMailEmail: 'user@yandex.ru',
        ),
      );
      expect(yandexConnectButtonLabel(connected), 'Обновить данные Яндекса');
    });

    test('YandexConnectResult does not expose app password fields', () {
      final result = YandexConnectResult.fromJson({
        'status': 'connected',
        'account_id': 'acc-1',
        'email': 'user@yandex.ru',
      });
      expect(result.email, 'user@yandex.ru');
      expect(result.accountId, 'acc-1');
    });
  });

  group('Account Yandex UX', () {
    testWidgets('disconnected Yandex shows connect button', (tester) async {
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.url.path.endsWith('/connections')) {
            return http.Response(jsonEncode(_connectionsJson()), 200);
          }
          if (isAccountSettingsRequest(request.url)) {
            return http.Response(jsonEncode(accountSettingsJson()), 200);
          }
          return http.Response('{}', 404);
        }),
      );
      client.configure(baseUrl: _baseUrl, token: _token);

      await _pumpAccountReady(
        tester,
        buildAccountScreen(
            apiClient: client, authController: _buildAuth(client)),
      );

      expect(find.text('Подключить Яндекс'), findsOneWidget);
    });

    testWidgets('dialog has separate mail and calendar password fields',
        (tester) async {
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.url.path.endsWith('/connections')) {
            return http.Response(jsonEncode(_connectionsJson()), 200);
          }
          if (isAccountSettingsRequest(request.url)) {
            return http.Response(jsonEncode(accountSettingsJson()), 200);
          }
          return http.Response('{}', 404);
        }),
      );
      client.configure(baseUrl: _baseUrl, token: _token);

      await _pumpAccountReady(
        tester,
        AccountScreen(apiClient: client, authController: _buildAuth(client)),
      );
      await tapAccountText(tester, 'Подключить Яндекс');
      await tester.pumpAndSettle();

      expect(find.widgetWithText(TextField, 'Email'), findsOneWidget);
      expect(
        find.text(
            'Яндекс Почта и Календарь используют разные пароли приложения.'),
        findsOneWidget,
      );
      final mailField = tester.widget<TextField>(
        find.byKey(const Key('yandex_mail_app_password')),
      );
      final calendarField = tester.widget<TextField>(
        find.byKey(const Key('yandex_calendar_app_password')),
      );
      expect(mailField.obscureText, isTrue);
      expect(calendarField.obscureText, isTrue);
      expect(find.text('Яндекс Почта'), findsOneWidget);
      expect(find.text('Яндекс Календарь'), findsOneWidget);
    });

    testWidgets('both services send distinct passwords to each endpoint',
        (tester) async {
      int mailCalls = 0;
      int calendarCalls = 0;
      String? mailBody;
      String? calendarBody;

      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.url.path.endsWith('/connections')) {
            return http.Response(
              jsonEncode(_connectionsJson()),
              200,
            );
          }
          if (request.url.path.endsWith('/connectors/yandex/mail/connect')) {
            mailCalls += 1;
            mailBody = request.body;
            return http.Response(
              jsonEncode({
                'status': 'connected',
                'account_id': 'mail-1',
                'email': 'user@yandex.ru',
              }),
              200,
            );
          }
          if (request.url.path
              .endsWith('/connectors/yandex/calendar/connect')) {
            calendarCalls += 1;
            calendarBody = request.body;
            return http.Response(
              jsonEncode({
                'status': 'connected',
                'account_id': 'cal-1',
                'email': 'user@yandex.ru',
                'caldav_host': 'caldav.yandex.ru',
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

      await _pumpAccountReady(
        tester,
        AccountScreen(apiClient: client, authController: _buildAuth(client)),
      );
      await tapAccountText(tester, 'Подключить Яндекс');
      await tester.pumpAndSettle();

      await tester.enterText(
          find.widgetWithText(TextField, 'Email'), 'user@yandex.ru');
      await tester.enterText(
          find.byKey(const Key('yandex_mail_app_password')), _mailPassword);
      await tester.enterText(
        find.byKey(const Key('yandex_calendar_app_password')),
        _calendarPassword,
      );
      await tester.tap(find.widgetWithText(FilledButton, 'Подключить'));
      await tester.pumpAndSettle();

      expect(mailCalls, 1);
      expect(calendarCalls, 1);
      final mailDecoded = jsonDecode(mailBody!) as Map<String, dynamic>;
      final calendarDecoded = jsonDecode(calendarBody!) as Map<String, dynamic>;
      expect(mailDecoded['app_password'], _mailPassword);
      expect(calendarDecoded['app_password'], _calendarPassword);
      expect(mailDecoded['app_password'], isNot(_calendarPassword));
      expect(find.textContaining(_mailPassword), findsNothing);
      expect(find.textContaining(_calendarPassword), findsNothing);
    });

    testWidgets('mail-only update does not call calendar connect',
        (tester) async {
      int calendarCalls = 0;
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.url.path.endsWith('/connections')) {
            return http.Response(jsonEncode(_connectionsJson()), 200);
          }
          if (request.url.path
              .endsWith('/connectors/yandex/calendar/connect')) {
            calendarCalls += 1;
            return http.Response('{}', 200);
          }
          if (request.url.path.endsWith('/connectors/yandex/mail/connect')) {
            return http.Response(
              jsonEncode({
                'status': 'connected',
                'account_id': 'mail-1',
                'email': 'user@yandex.ru',
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

      await _pumpAccountReady(
        tester,
        AccountScreen(apiClient: client, authController: _buildAuth(client)),
      );
      await tapAccountText(tester, 'Подключить Яндекс');
      await tester.pumpAndSettle();

      await tester.tap(find.text('Яндекс Календарь'));
      await tester.pumpAndSettle();
      await tester.enterText(
          find.widgetWithText(TextField, 'Email'), 'user@yandex.ru');
      await tester.enterText(
          find.byKey(const Key('yandex_mail_app_password')), _mailPassword);
      await tester.tap(find.widgetWithText(FilledButton, 'Подключить'));
      await tester.pumpAndSettle();

      expect(calendarCalls, 0);
    });

    testWidgets('calendar-only update does not call mail connect',
        (tester) async {
      int mailCalls = 0;
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.url.path.endsWith('/connections')) {
            return http.Response(jsonEncode(_connectionsJson()), 200);
          }
          if (request.url.path.endsWith('/connectors/yandex/mail/connect')) {
            mailCalls += 1;
            return http.Response('{}', 200);
          }
          if (request.url.path
              .endsWith('/connectors/yandex/calendar/connect')) {
            return http.Response(
              jsonEncode({
                'status': 'connected',
                'account_id': 'cal-1',
                'email': 'user@yandex.ru',
                'caldav_host': 'caldav.yandex.ru',
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

      await _pumpAccountReady(
        tester,
        AccountScreen(apiClient: client, authController: _buildAuth(client)),
      );
      await tapAccountText(tester, 'Подключить Яндекс');
      await tester.pumpAndSettle();

      await tester.tap(find.text('Яндекс Почта'));
      await tester.pumpAndSettle();
      await tester.enterText(
          find.widgetWithText(TextField, 'Email'), 'user@yandex.ru');
      await tester.enterText(
        find.byKey(const Key('yandex_calendar_app_password')),
        _calendarPassword,
      );
      await tester.tap(find.widgetWithText(FilledButton, 'Подключить'));
      await tester.pumpAndSettle();

      expect(mailCalls, 0);
    });

    testWidgets('calendar failure does not erase mail connection state',
        (tester) async {
      int connectionsCalls = 0;
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.url.path.endsWith('/connections')) {
            connectionsCalls += 1;
            final mailConnected = connectionsCalls >= 2;
            return http.Response(
              jsonEncode(_connectionsJson(
                yandexMailConnected: mailConnected,
                yandexMailEmail: mailConnected ? 'user@yandex.ru' : null,
              )),
              200,
            );
          }
          if (request.url.path.endsWith('/connectors/yandex/mail/connect')) {
            return http.Response(
              jsonEncode({
                'status': 'connected',
                'account_id': 'mail-1',
                'email': 'user@yandex.ru',
              }),
              200,
            );
          }
          if (request.url.path
              .endsWith('/connectors/yandex/calendar/connect')) {
            return http.Response(
                jsonEncode({'detail': 'calendar unauthorized'}), 401);
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
      await tapAccountText(tester, 'Подключить Яндекс');
      await tester.pumpAndSettle();

      await tester.enterText(
          find.widgetWithText(TextField, 'Email'), 'user@yandex.ru');
      await tester.enterText(
          find.byKey(const Key('yandex_mail_app_password')), _mailPassword);
      await tester.enterText(
        find.byKey(const Key('yandex_calendar_app_password')),
        _calendarPassword,
      );
      await tester.tap(find.widgetWithText(FilledButton, 'Подключить'));
      for (var i = 0; i < 40; i++) {
        await tester.pump(const Duration(milliseconds: 50));
        if (find.textContaining('Яндекс Календарь').evaluate().length > 1) {
          break;
        }
      }

      expect(auth.status, AuthStatus.authenticated);
      expect(find.textContaining('Не удалось подключить Яндекс Календарь'),
          findsOneWidget);
      expect(find.text('Яндекс Почта: подключено (user@yandex.ru)'),
          findsOneWidget);
      expect(connectionsCalls, greaterThanOrEqualTo(2));
    });

    testWidgets('password controllers cleared after submit error',
        (tester) async {
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.url.path.endsWith('/connections')) {
            return http.Response(jsonEncode(_connectionsJson()), 200);
          }
          if (request.url.path.endsWith('/connectors/yandex/mail/connect')) {
            return http.Response(jsonEncode({'detail': 'mail failed'}), 400);
          }
          if (request.url.path
              .endsWith('/connectors/yandex/calendar/connect')) {
            return http.Response(
                jsonEncode({'detail': 'calendar failed'}), 400);
          }
          if (isAccountSettingsRequest(request.url)) {
            return http.Response(jsonEncode(accountSettingsJson()), 200);
          }
          return http.Response('{}', 404);
        }),
      );
      client.configure(baseUrl: _baseUrl, token: _token);

      await _pumpAccountReady(
        tester,
        AccountScreen(apiClient: client, authController: _buildAuth(client)),
      );
      await tapAccountText(tester, 'Подключить Яндекс');
      await tester.pumpAndSettle();

      await tester.enterText(
          find.widgetWithText(TextField, 'Email'), 'user@yandex.ru');
      await tester.enterText(
          find.byKey(const Key('yandex_mail_app_password')), _mailPassword);
      await tester.enterText(
        find.byKey(const Key('yandex_calendar_app_password')),
        _calendarPassword,
      );
      await tester.tap(find.widgetWithText(FilledButton, 'Подключить'));
      for (var i = 0; i < 40; i++) {
        await tester.pump(const Duration(milliseconds: 50));
        if (find
            .textContaining('Не удалось подключить')
            .evaluate()
            .isNotEmpty) {
          break;
        }
      }

      final mailField = tester.widget<TextField>(
        find.byKey(const Key('yandex_mail_app_password')),
      );
      final calendarField = tester.widget<TextField>(
        find.byKey(const Key('yandex_calendar_app_password')),
      );
      expect(mailField.controller?.text, isEmpty);
      expect(calendarField.controller?.text, isEmpty);
      expect(find.textContaining(_mailPassword), findsNothing);
      expect(find.textContaining(_calendarPassword), findsNothing);
    });
  });
}
