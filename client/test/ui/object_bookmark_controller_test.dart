import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/ui/object_bookmark_controller.dart';

http.Response jsonRes(Object body, [int status = 200]) {
  return http.Response.bytes(
    utf8.encode(jsonEncode(body)),
    status,
    headers: {'content-type': 'application/json; charset=utf-8'},
  );
}

ObjectBookmarkController buildController(
  SecretaryApiClient apiClient,
) {
  final auth = AuthController(
    apiClient: apiClient,
    tokenStore: FakeTokenStore(),
    serverUrlStore: FakeServerUrlStore(),
  );
  auth.status = AuthStatus.authenticated;
  apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
  return ObjectBookmarkController(apiClient: apiClient, authController: auth);
}

void main() {
  test('reconcile merges queried ids, drops absent, leaves unrelated, dedupes',
      () async {
    var batchCalls = 0;
    List<dynamic>? lastIds;
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/object-bookmarks/by-objects') {
          batchCalls++;
          lastIds =
              (jsonDecode(request.body) as Map)['object_ids'] as List<dynamic>;
          return jsonRes({
            'objects': {
              'b': {'color': 'blue'},
            },
          });
        }
        if (request.method == 'PUT' &&
            request.url.path.startsWith('/object-bookmarks/')) {
          final color = (jsonDecode(request.body) as Map)['color'] as String;
          final id = request.url.path.split('/').last;
          return jsonRes({
            'object_id': id,
            'color': color,
            'updated_at': '2026-09-09T13:00:00Z',
          });
        }
        return jsonRes({}, 404);
      }),
    );
    final controller = buildController(apiClient);
    expect(await controller.reconcileVisible([]), isTrue);
    expect(batchCalls, 0);
    await controller.setColor('x', 'gray');
    await controller.setColor('a', 'red');
    expect(await controller.reconcileVisible(['a', 'a', 'b']), isTrue);
    expect(batchCalls, 1);
    expect(lastIds, ['a', 'b']);
    expect(controller.colorFor('a'), isNull);
    expect(controller.colorFor('b'), 'blue');
    expect(controller.colorFor('x'), 'gray');
  });

  test('stale batch read does not overwrite a newer mutation', () async {
    final batchGate = Completer<void>();
    var batchCalls = 0;
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/object-bookmarks/by-objects') {
          batchCalls++;
          await batchGate.future;
          return jsonRes({
            'objects': {
              'a': {'color': 'orange'},
            },
          });
        }
        if (request.method == 'PUT' &&
            request.url.path == '/object-bookmarks/a') {
          return jsonRes({
            'object_id': 'a',
            'color': 'red',
            'updated_at': '2026-09-09T13:00:00Z',
          });
        }
        return jsonRes({}, 404);
      }),
    );
    final controller = buildController(apiClient);
    final reconcile = controller.reconcileVisible(['a']);
    while (batchCalls == 0) {
      await Future<void>.delayed(Duration.zero);
    }
    await controller.setColor('a', 'red');
    expect(controller.colorFor('a'), 'red');
    batchGate.complete();
    expect(await reconcile, isTrue);
    expect(controller.colorFor('a'), 'red');
  });

  test('failed batch read preserves cache; successful absence removes it',
      () async {
    var batchCalls = 0;
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/object-bookmarks/by-objects') {
          batchCalls++;
          if (batchCalls == 1) {
            return jsonRes({'detail': 'unavailable'}, 500);
          }
          return jsonRes({
            'objects': {
              'b': {'color': 'green'},
            },
          });
        }
        if (request.method == 'PUT' &&
            request.url.path.startsWith('/object-bookmarks/')) {
          final color = (jsonDecode(request.body) as Map)['color'] as String;
          final id = request.url.path.split('/').last;
          return jsonRes({
            'object_id': id,
            'color': color,
            'updated_at': '2026-09-09T13:00:00Z',
          });
        }
        return jsonRes({}, 404);
      }),
    );
    final controller = buildController(apiClient);
    await controller.setColor('a', 'red');
    await controller.setColor('b', 'blue');
    var notifies = 0;
    controller.addListener(() => notifies++);
    expect(await controller.reconcileVisible(['a', 'b']), isFalse);
    expect(batchCalls, 1);
    expect(controller.colorFor('a'), 'red');
    expect(controller.colorFor('b'), 'blue');
    expect(notifies, 0);
    expect(await controller.reconcileVisible(['a', 'b']), isTrue);
    expect(batchCalls, 2);
    expect(controller.colorFor('a'), isNull);
    expect(controller.colorFor('b'), 'green');
    expect(notifies, 1);
  });

  test('auth failure on batch read does not treat bookmarks as absent', () async {
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/object-bookmarks/by-objects') {
          return jsonRes({'detail': 'invalid token'}, 401);
        }
        if (request.method == 'PUT' &&
            request.url.path.startsWith('/object-bookmarks/')) {
          final color = (jsonDecode(request.body) as Map)['color'] as String;
          final id = request.url.path.split('/').last;
          return jsonRes({
            'object_id': id,
            'color': color,
            'updated_at': '2026-09-09T13:00:00Z',
          });
        }
        return jsonRes({}, 404);
      }),
    );
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    final controller = ObjectBookmarkController(
      apiClient: apiClient,
      authController: auth,
    );
    await controller.setColor('a', 'red');
    var notifies = 0;
    controller.addListener(() => notifies++);
    expect(await controller.reconcileVisible(['a']), isFalse);
    expect(auth.status, AuthStatus.needsAuth);
    expect(controller.colorFor('a'), 'red');
    expect(notifies, 0);
  });
}
