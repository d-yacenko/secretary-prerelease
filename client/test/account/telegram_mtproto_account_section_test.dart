import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/account/telegram_mtproto_account_section.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';

AuthController _auth(SecretaryApiClient client) {
  final auth = AuthController(
    apiClient: client,
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

Map<String, dynamic> _account() => {
  'id': 'account-1',
  'telegram_user_id': 12345,
  'username': 'alice',
  'display_name': 'Alice',
};

Map<String, dynamic> _connectedStatus() => {
  'configured': true,
  'connected': true,
  'account': _account(),
};

http.Response _scopeResponse(String path) {
  if (path.endsWith('/folders')) {
    return http.Response(
      jsonEncode({
        'folders': [
          {'folder_id': 1, 'name': 'Work'},
        ],
        'truncated': true,
      }),
      200,
    );
  }
  if (path.endsWith('/sync-folders')) {
    return http.Response(
      jsonEncode({
        'folders': [
          {'folder_id': 1, 'name': 'Work', 'ignore_muted': true},
        ],
        'ignore_muted': true,
      }),
      200,
    );
  }
  if (path.endsWith('/groups')) {
    return http.Response(
      jsonEncode({
        'groups': [
          {
            'peer_id': -100,
            'kind': 'supergroup',
            'title': 'Team',
            'username': 'team',
            'is_forum': false,
            'selected': true,
            'available': true,
          },
          {
            'peer_id': -101,
            'kind': 'group',
            'title': 'Unavailable',
            'username': null,
            'is_forum': false,
            'selected': false,
            'available': false,
          },
        ],
        'truncated': false,
      }),
      200,
    );
  }
  return http.Response('{}', 404);
}

Future<void> _pumpSection(
  WidgetTester tester,
  SecretaryApiClient client,
) async {
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(
          child: TelegramMtprotoAccountSection(
            apiClient: client,
            authController: _auth(client),
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('phone -> code -> password -> authorized clears secrets', (
    tester,
  ) async {
    var connected = false;
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        final path = request.url.path;
        if (path.endsWith('/status')) {
          return http.Response(
            jsonEncode({
              'configured': true,
              'connected': connected,
              'account': connected ? _account() : null,
            }),
            200,
          );
        }
        if (path.endsWith('/auth/start')) {
          return http.Response(
            jsonEncode({
              'challenge_id': 'challenge-1',
              'expires_at': '2026-09-18T10:00:00Z',
            }),
            200,
          );
        }
        if (path.endsWith('/auth/code')) {
          return http.Response(
            jsonEncode({'status': 'password_required', 'account': null}),
            200,
          );
        }
        if (path.endsWith('/auth/password')) {
          connected = true;
          return http.Response(jsonEncode(_account()), 200);
        }
        return _scopeResponse(path);
      }),
    );
    client.configure(baseUrl: 'https://secretary.example', token: 'token');
    await _pumpSection(tester, client);

    await tester.enterText(
      find.byKey(const Key('telegram_mtproto_phone')),
      '+70000000000',
    );
    await tester.tap(find.byKey(const Key('telegram_mtproto_start_auth')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('telegram_mtproto_code')),
      '12345',
    );
    await tester.tap(find.byKey(const Key('telegram_mtproto_submit_code')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('telegram_mtproto_password')), findsOneWidget);
    await tester.enterText(
      find.byKey(const Key('telegram_mtproto_password')),
      'two-factor-secret',
    );
    await tester.tap(find.byKey(const Key('telegram_mtproto_submit_password')));
    await tester.pumpAndSettle();

    expect(find.textContaining('Telegram user id: 12345'), findsOneWidget);
    expect(find.byKey(const Key('telegram_mtproto_code')), findsNothing);
    expect(find.byKey(const Key('telegram_mtproto_password')), findsNothing);
  });

  testWidgets(
    'connected scope supports zero folders, preview, reconcile and unavailable group',
    (tester) async {
      final calls = <String>[];
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          calls.add('${request.method} ${request.url.path}');
          final path = request.url.path;
          if (path.endsWith('/status')) {
            return http.Response(jsonEncode(_connectedStatus()), 200);
          }
          if (path.endsWith('/sync-scope/preview')) {
            return http.Response(
              jsonEncode({
                'dialogs': [],
                'truncated': true,
                'skipped_counts': {'bot': 1},
                'configured_folder_count': 0,
              }),
              200,
            );
          }
          if (path.endsWith('/sync-scope/reconcile')) {
            return http.Response(
              jsonEncode({
                'active': 0,
                'activated': 0,
                'deactivated': 0,
                'unchanged': 0,
                'peers': [],
              }),
              200,
            );
          }
          if (path.contains('/groups/')) {
            return http.Response(
              jsonEncode({'peer_id': -100, 'selected': true}),
              200,
            );
          }
          return _scopeResponse(path);
        }),
      );
      client.configure(baseUrl: 'https://secretary.example', token: 'token');
      await _pumpSection(tester, client);

      expect(find.text('Unavailable'), findsOneWidget);
      expect(
        find.byKey(const Key('telegram_mtproto_folder_1')),
        findsOneWidget,
      );
      await tester.tap(find.byKey(const Key('telegram_mtproto_folder_1')));
      await tester.tap(find.byKey(const Key('telegram_mtproto_save_folders')));
      await tester.pumpAndSettle();
      expect(
        calls.any(
          (call) => call.startsWith('PUT /telegram/mtproto/sync-folders'),
        ),
        isTrue,
      );

      await tester.tap(find.byKey(const Key('telegram_mtproto_preview_scope')));
      await tester.tap(
        find.byKey(const Key('telegram_mtproto_reconcile_scope')),
      );
      await tester.pumpAndSettle();
      expect(find.textContaining('Предпросмотр усечён'), findsOneWidget);
      expect(find.textContaining('Пропущено'), findsOneWidget);
    },
  );

  testWidgets('duplicate auth submit sends one request', (tester) async {
    final start = Completer<http.Response>();
    var calls = 0;
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path.endsWith('/status')) {
          return http.Response(
            jsonEncode({
              'configured': true,
              'connected': false,
              'account': null,
            }),
            200,
          );
        }
        calls += 1;
        return start.future;
      }),
    );
    client.configure(baseUrl: 'https://secretary.example', token: 'token');
    await _pumpSection(tester, client);
    await tester.enterText(
      find.byKey(const Key('telegram_mtproto_phone')),
      '+70000000000',
    );
    await tester.tap(find.byKey(const Key('telegram_mtproto_start_auth')));
    await tester.tap(find.byKey(const Key('telegram_mtproto_start_auth')));
    expect(calls, 1);
    start.complete(
      http.Response(
        jsonEncode({'challenge_id': 'challenge-1', 'expires_at': 'x'}),
        200,
      ),
    );
    await tester.pumpAndSettle();
  });
}
