import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_error.dart';
import 'package:personal_secretary/api/api_models.dart';

import '../test_secretary_api_client.dart';

Map<String, dynamic> _account() => {
  'id': 'account-1',
  'telegram_user_id': 12345,
  'username': 'alice',
  'display_name': 'Alice',
};

Map<String, dynamic> _sync() => {
  'peer_id': -100,
  'scanned': 4,
  'materialized': 3,
  'created': 1,
  'updated': 1,
  'unchanged': 1,
  'skipped': 1,
  'jobs_enqueued': 0,
  'history_complete': true,
};

void main() {
  test('parses status, folder, scope, group and sync models safely', () {
    final status = TelegramMtprotoStatus.fromJson({
      'configured': true,
      'connected': true,
      'account': _account(),
    });
    expect(status.account!.telegramUserId, 12345);
    expect(
      TelegramMtprotoFolderList.fromJson({
        'folders': [
          {'folder_id': 1, 'name': 'Work'},
        ],
        'truncated': true,
      }).truncated,
      isTrue,
    );
    expect(
      TelegramMtprotoScopePreview.fromJson({
        'dialogs': [
          {
            'peer_id': 10,
            'kind': 'private',
            'title': 'Alice',
            'username': 'alice',
            'is_muted': false,
          },
        ],
        'truncated': true,
        'skipped_counts': {'bot': 2},
        'configured_folder_count': 1,
      }).skippedCounts['bot'],
      2,
    );
    expect(
      TelegramMtprotoGroupList.fromJson({
        'groups': [
          {
            'peer_id': -100,
            'kind': 'supergroup',
            'title': 'Team',
            'username': null,
            'is_forum': false,
            'selected': true,
            'available': true,
          },
        ],
        'truncated': false,
      }).groups.single.kind,
      'supergroup',
    );
    expect(TelegramMtprotoHistorySync.fromJson(_sync()).created, 1);
  });

  test('client uses the existing MTProto endpoint contract', () async {
    final calls = <String>[];
    final client = testSecretaryApiClient(
      MockClient((request) async {
        calls.add('${request.method} ${request.url.path} ${request.body}');
        final path = request.url.path;
        if (path.endsWith('/status')) {
          return http.Response(
            jsonEncode({
              'configured': true,
              'connected': false,
              'account': null,
            }),
            200,
          );
        }
        if (path.endsWith('/auth/start')) {
          expect(jsonDecode(request.body), {'phone': '+70000000000'});
          return http.Response(
            jsonEncode({
              'challenge_id': 'challenge-1',
              'expires_at': '2026-09-18T10:00:00Z',
            }),
            200,
          );
        }
        if (path.endsWith('/auth/code')) {
          expect(jsonDecode(request.body), {
            'challenge_id': 'challenge-1',
            'code': '12345',
          });
          return http.Response(
            jsonEncode({'status': 'authorized', 'account': _account()}),
            200,
          );
        }
        if (path.endsWith('/auth/password')) {
          return http.Response(jsonEncode(_account()), 200);
        }
        if (path.endsWith('/folders')) {
          return http.Response(
            jsonEncode({'folders': [], 'truncated': false}),
            200,
          );
        }
        if (path.endsWith('/sync-folders')) {
          return http.Response(
            jsonEncode({'folders': [], 'ignore_muted': true}),
            200,
          );
        }
        if (path.endsWith('/sync-scope/preview')) {
          return http.Response(
            jsonEncode({
              'dialogs': [],
              'truncated': false,
              'skipped_counts': {},
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
        if (path.contains('/sync-scope/peers/')) {
          return http.Response(jsonEncode(_sync()), 200);
        }
        if (path.endsWith('/groups')) {
          return http.Response(
            jsonEncode({'groups': [], 'truncated': false}),
            200,
          );
        }
        if (path.contains('/groups/')) {
          return http.Response(
            jsonEncode({'peer_id': -100, 'selected': true}),
            200,
          );
        }
        return http.Response('{}', 404);
      }),
    );
    client.configure(baseUrl: 'https://secretary.example', token: 'token');

    expect((await client.getTelegramMtprotoStatus()).connected, isFalse);
    expect(
      (await client.startTelegramMtprotoAuth(
        phone: '+70000000000',
      )).challengeId,
      'challenge-1',
    );
    expect(
      (await client.submitTelegramMtprotoCode(
        challengeId: 'challenge-1',
        code: '12345',
      )).status,
      'authorized',
    );
    await client.submitTelegramMtprotoPassword(
      challengeId: 'challenge-1',
      password: 'secret',
    );
    await client.getTelegramMtprotoFolders();
    await client.getTelegramMtprotoSyncFolders();
    await client.putTelegramMtprotoSyncFolders(
      folderNames: [],
      ignoreMuted: true,
    );
    await client.previewTelegramMtprotoScope();
    await client.reconcileTelegramMtprotoScope();
    await client.syncTelegramMtprotoScopePeer(-100);
    await client.getTelegramMtprotoGroups();
    await client.setTelegramMtprotoGroupSelected(peerId: -100, selected: true);
    await client.syncTelegramMtprotoGroup(-100);

    expect(calls, hasLength(13));
    expect(
      calls.any(
        (call) => call.startsWith('PUT /telegram/mtproto/sync-folders'),
      ),
      isTrue,
    );
  });

  test(
    'MTProto API errors use existing sanitized exception conventions',
    () async {
      for (final status in [400, 409, 410, 503]) {
        final client = testSecretaryApiClient(
          MockClient(
            (_) async =>
                http.Response(jsonEncode({'detail': 'safe error'}), status),
          ),
        );
        client.configure(baseUrl: 'https://secretary.example', token: 'token');
        expect(client.getTelegramMtprotoStatus(), throwsA(isA<ApiException>()));
      }
    },
  );
}
