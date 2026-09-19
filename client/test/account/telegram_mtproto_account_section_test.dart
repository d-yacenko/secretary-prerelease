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

AuthController _auth(
  SecretaryApiClient client, {
  VoidCallback? onAuthenticationFailure,
}) {
  final auth = AuthController(
    apiClient: client,
    tokenStore: FakeTokenStore(),
    serverUrlStore: FakeServerUrlStore(),
  );
  auth.status = AuthStatus.authenticated;
  auth.onSessionTerminated = onAuthenticationFailure;
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
            key: UniqueKey(),
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

  testWidgets('server not configured and configured disconnected states', (
    tester,
  ) async {
    final notConfigured = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path.endsWith('/status')) {
          return http.Response(
            jsonEncode({'detail': 'Telegram MTProto is not configured'}),
            503,
          );
        }
        return http.Response('{}', 404);
      }),
    );
    notConfigured.configure(
      baseUrl: 'https://secretary.example',
      token: 'token',
    );
    await _pumpSection(tester, notConfigured);
    expect(
      find.text('Telegram MTProto не настроен на сервере.'),
      findsOneWidget,
    );

    final disconnected = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path.endsWith('/status')) {
          return http.Response(
            jsonEncode({'configured': true, 'connected': false}),
            200,
          );
        }
        return http.Response('{}', 404);
      }),
    );
    disconnected.configure(
      baseUrl: 'https://secretary.example',
      token: 'token',
    );
    await _pumpSection(tester, disconnected);
    expect(find.textContaining('не подключён'), findsOneWidget);
  });

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

  testWidgets('phone -> code -> authorized never shows password UI', (
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
          connected = true;
          return http.Response(
            jsonEncode({'status': 'authorized', 'account': _account()}),
            200,
          );
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
    expect(find.byKey(const Key('telegram_mtproto_code')), findsOneWidget);
    expect(find.byKey(const Key('telegram_mtproto_password')), findsNothing);
    expect(
      find.byKey(const Key('telegram_mtproto_submit_password')),
      findsNothing,
    );
    await tester.enterText(
      find.byKey(const Key('telegram_mtproto_code')),
      '12345',
    );
    await tester.tap(find.byKey(const Key('telegram_mtproto_submit_code')));
    await tester.pumpAndSettle();
    expect(find.textContaining('Telegram user id: 12345'), findsOneWidget);
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

  testWidgets(
    'reconcile replaces preview peers authoritatively and syncs exact peer',
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
                'dialogs': [
                  {
                    'peer_id': 666,
                    'kind': 'private',
                    'title': 'A',
                    'username': 'a',
                    'is_muted': false,
                  },
                  {
                    'peer_id': 777,
                    'kind': 'private',
                    'title': 'B',
                    'username': 'b',
                    'is_muted': false,
                  },
                ],
                'truncated': false,
                'skipped_counts': {},
                'configured_folder_count': 1,
              }),
              200,
            );
          }
          if (path.endsWith('/sync-scope/reconcile')) {
            return http.Response(
              jsonEncode({
                'active': 2,
                'activated': 1,
                'deactivated': 0,
                'unchanged': 0,
                'peers': [
                  {
                    'peer_id': 777,
                    'kind': 'private',
                    'title': 'B',
                    'username': 'b',
                    'is_muted': false,
                  },
                  {
                    'peer_id': 888,
                    'kind': 'supergroup',
                    'title': 'C',
                    'username': 'c',
                    'is_muted': false,
                  },
                ],
              }),
              200,
            );
          }
          if (path.endsWith('/sync-scope/peers/888/sync')) {
            return http.Response(
              jsonEncode({
                'peer_id': 888,
                'scanned': 2,
                'materialized': 2,
                'created': 1,
                'updated': 1,
                'unchanged': 0,
                'skipped': 0,
                'jobs_enqueued': 0,
                'history_complete': true,
              }),
              200,
            );
          }
          return _scopeResponse(path);
        }),
      );
      client.configure(baseUrl: 'https://secretary.example', token: 'token');
      await _pumpSection(tester, client);
      await tester.tap(find.byKey(const Key('telegram_mtproto_preview_scope')));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('telegram_mtproto_scope_peer_666')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('telegram_mtproto_scope_peer_777')),
        findsOneWidget,
      );
      await tester.tap(
        find.byKey(const Key('telegram_mtproto_reconcile_scope')),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('telegram_mtproto_scope_peer_666')),
        findsNothing,
      );
      expect(
        find.byKey(const Key('telegram_mtproto_scope_peer_777')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('telegram_mtproto_scope_peer_888')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('telegram_mtproto_sync_scope_peer_777')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('telegram_mtproto_sync_scope_peer_888')),
        findsOneWidget,
      );
      await tester.tap(
        find.byKey(const Key('telegram_mtproto_sync_scope_peer_888')),
      );
      await tester.pumpAndSettle();
      expect(
        calls,
        contains('POST /telegram/mtproto/sync-scope/peers/888/sync'),
      );
      expect(find.textContaining('created 1'), findsOneWidget);
    },
  );

  testWidgets('ignore muted round trip preserves zero folder selection', (
    tester,
  ) async {
    final requests = <http.Request>[];
    var saved = false;
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        requests.add(request);
        final path = request.url.path;
        if (path.endsWith('/status')) {
          return http.Response(jsonEncode(_connectedStatus()), 200);
        }
        if (path.endsWith('/sync-folders') && request.method == 'GET') {
          return http.Response(
            jsonEncode({'folders': [], 'ignore_muted': !saved}),
            200,
          );
        }
        if (path.endsWith('/sync-folders') && request.method == 'PUT') {
          saved = true;
          return http.Response(
            jsonEncode({'folders': [], 'ignore_muted': false}),
            200,
          );
        }
        if (path.endsWith('/groups/-100') && request.method == 'PATCH') {
          return http.Response(
            jsonEncode({'peer_id': -100, 'selected': false}),
            200,
          );
        }
        return _scopeResponse(path);
      }),
    );
    client.configure(baseUrl: 'https://secretary.example', token: 'token');
    await _pumpSection(tester, client);
    expect(
      tester
          .widget<SwitchListTile>(
            find.byKey(const Key('telegram_mtproto_ignore_muted')),
          )
          .value,
      isTrue,
    );
    await tester.tap(find.byKey(const Key('telegram_mtproto_ignore_muted')));
    await tester.tap(find.byKey(const Key('telegram_mtproto_save_folders')));
    await tester.pumpAndSettle();
    final put = requests.firstWhere((request) => request.method == 'PUT');
    final body = jsonDecode(put.body) as Map<String, dynamic>;
    expect(body['folder_names'], isEmpty);
    expect(body['ignore_muted'], isFalse);

    await tester.tap(find.byKey(const Key('telegram_mtproto_group_-100')));
    await tester.pumpAndSettle();
    expect(
      tester
          .widget<SwitchListTile>(
            find.byKey(const Key('telegram_mtproto_ignore_muted')),
          )
          .value,
      isFalse,
    );
  });

  testWidgets('forum and unavailable groups are explicit and non-actionable', (
    tester,
  ) async {
    final calls = <String>[];
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        calls.add('${request.method} ${request.url.path}');
        final path = request.url.path;
        if (path.endsWith('/status')) {
          return http.Response(jsonEncode(_connectedStatus()), 200);
        }
        if (path.endsWith('/groups')) {
          return http.Response(
            jsonEncode({
              'groups': [
                {
                  'peer_id': -100,
                  'kind': 'supergroup',
                  'title': 'Forum Team',
                  'username': 'forum_team',
                  'is_forum': true,
                  'selected': true,
                  'available': true,
                },
                {
                  'peer_id': -101,
                  'kind': 'group',
                  'title': 'Gone Team',
                  'username': null,
                  'is_forum': false,
                  'selected': false,
                  'available': false,
                },
              ],
            }),
            200,
          );
        }
        return _scopeResponse(path);
      }),
    );
    client.configure(baseUrl: 'https://secretary.example', token: 'token');
    await _pumpSection(tester, client);
    expect(find.textContaining('forum'), findsOneWidget);
    expect(find.textContaining('недоступна'), findsOneWidget);
    final unavailable = find.byType(Checkbox).last;
    expect(tester.widget<Checkbox>(unavailable).onChanged, isNull);
    expect(find.text('Синхронизировать'), findsNWidgets(2));
    await tester.tap(find.text('Синхронизировать').last);
    await tester.pumpAndSettle();
    expect(calls.any((call) => call.contains('/groups/-101/sync')), isFalse);
  });

  testWidgets('selected group toggles and shows manual sync summary', (
    tester,
  ) async {
    final calls = <String>[];
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        calls.add('${request.method} ${request.url.path}');
        final path = request.url.path;
        if (path.endsWith('/status')) {
          return http.Response(jsonEncode(_connectedStatus()), 200);
        }
        if (request.method == 'PATCH' && path.endsWith('/groups/-100')) {
          return http.Response(
            jsonEncode({'peer_id': -100, 'selected': false}),
            200,
          );
        }
        if (request.method == 'POST' && path.endsWith('/groups/-100/sync')) {
          return http.Response(
            jsonEncode({
              'peer_id': -100,
              'scanned': 1,
              'materialized': 1,
              'created': 1,
              'updated': 0,
              'unchanged': 0,
              'skipped': 0,
              'jobs_enqueued': 0,
              'history_complete': true,
            }),
            200,
          );
        }
        return _scopeResponse(path);
      }),
    );
    client.configure(baseUrl: 'https://secretary.example', token: 'token');
    await _pumpSection(tester, client);
    await tester.tap(find.byKey(const Key('telegram_mtproto_group_-100')));
    await tester.pumpAndSettle();
    expect(calls, contains('PATCH /telegram/mtproto/groups/-100'));
    await tester.tap(find.byKey(const Key('telegram_mtproto_sync_group_-100')));
    await tester.pumpAndSettle();
    expect(calls, contains('POST /telegram/mtproto/groups/-100/sync'));
    expect(find.textContaining('created 1'), findsOneWidget);
  });

  testWidgets('authenticated MTProto action routes 401 to AuthController', (
    tester,
  ) async {
    var authFailure = false;
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        final path = request.url.path;
        if (path.endsWith('/status')) {
          return http.Response(jsonEncode(_connectedStatus()), 200);
        }
        if (request.method == 'PUT' && path.endsWith('/sync-folders')) {
          return http.Response(jsonEncode({'detail': 'expired'}), 401);
        }
        return _scopeResponse(path);
      }),
    );
    client.configure(baseUrl: 'https://secretary.example', token: 'token');
    final auth = _auth(
      client,
      onAuthenticationFailure: () => authFailure = true,
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: TelegramMtprotoAccountSection(
              apiClient: client,
              authController: auth,
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('telegram_mtproto_save_folders')));
    await tester.pumpAndSettle();
    expect(authFailure, isTrue);
  });

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
