import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/capture/capture_controller.dart';
import 'package:personal_secretary/inbox/inbox_screen.dart';

Map<String, dynamic> _event({
  required String id,
  required String eventType,
  String status = 'new',
  String? readAt,
  String? sourceObjectId = 'mtproto-object-1',
}) {
  return {
    'id': id,
    'title': 'raw backend title',
    'body': 'A useful Telegram message preview',
    'priority': 'normal',
    'status': status,
    'source_object_id': sourceObjectId,
    'related_object_id': null,
    'result_object_id': null,
    'proposal': {
      'type': 'transport_event',
      'provider': 'telegram',
      'transport': 'mtproto',
      'event_type': eventType,
      'conversation_title': 'Work chat',
      'occurred_at': '2026-09-01T12:34:00Z',
      if (eventType == 'message_edited') 'edited_at': '2026-09-01T12:35:00Z',
      'event_key': 'telegram:mtproto:secret-event-key',
      'account_id': 'secret-account-id',
      'peer_id': -100123,
      'message_id': 456,
    },
    'read_at': readAt,
    'created_at': '2026-09-01T12:34:00Z',
    'updated_at': '2026-09-01T12:34:00Z',
  };
}

Map<String, dynamic> _inbox(List<Map<String, dynamic>> notifications) => {
  'unresolved_notifications': notifications,
  'recent_source_objects': [],
  'source_sync_status': [],
};

Map<String, dynamic> _object() => {
  'id': 'mtproto-object-1',
  'kind': 'chat_message',
  'title': 'Work chat',
  'body': 'A useful Telegram message preview',
  'provider': 'telegram',
  'external_id': 'telegram:mtproto:message',
  'canonical_uri': null,
  'status': null,
  'start_at': null,
  'due_at': null,
  'metadata': {'transport': 'mtproto'},
  'origin': 'source',
  'state': 'observed',
  'confidence': null,
  'created_at': '2026-09-01T12:34:00Z',
  'updated_at': '2026-09-01T12:34:00Z',
};

Future<void> _pumpInbox(WidgetTester tester, AuthController auth) async {
  final client = auth.apiClient;
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: InboxScreen(
          apiClient: client,
          authController: auth,
          captureController: CaptureController(
            apiClient: client,
            authController: auth,
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

AuthController _auth(SecretaryApiClient client) {
  final auth = AuthController(
    apiClient: client,
    tokenStore: FakeTokenStore(),
    serverUrlStore: FakeServerUrlStore(),
  );
  auth.status = AuthStatus.authenticated;
  return auth;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets(
    'created edited deleted transport events have safe presentation',
    (tester) async {
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          if (request.url.path == '/inbox') {
            return http.Response(
              jsonEncode(
                _inbox([
                  _event(id: 'created', eventType: 'message_created'),
                  _event(id: 'edited', eventType: 'message_edited'),
                  _event(id: 'deleted', eventType: 'message_deleted'),
                ]),
              ),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
      );
      client.configure(baseUrl: 'https://secretary.example', token: 'token');
      await _pumpInbox(tester, _auth(client));
      expect(
        find.text('Telegram · Новое сообщение · Work chat'),
        findsOneWidget,
      );
      expect(
        find.text('Telegram · Сообщение изменено · Work chat'),
        findsOneWidget,
      );
      expect(
        find.text('Telegram · Сообщение удалено · Work chat'),
        findsOneWidget,
      );
      expect(find.text('A useful Telegram message preview'), findsNWidgets(3));
      expect(find.textContaining('Время:'), findsWidgets);
      expect(find.text('raw backend title'), findsNothing);
      expect(find.textContaining('secret-event-key'), findsNothing);
      expect(find.textContaining('secret-account-id'), findsNothing);
      expect(find.textContaining('-100123'), findsNothing);
      expect(find.textContaining('456'), findsNothing);
    },
  );

  testWidgets('transport actions use accept and ignore endpoints', (
    tester,
  ) async {
    final calls = <String>[];
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        calls.add('${request.method} ${request.url.path}');
        if (request.url.path == '/inbox') {
          return http.Response(
            jsonEncode(
              _inbox([
                _event(id: 'created', eventType: 'message_created'),
                _event(id: 'ignored', eventType: 'message_deleted'),
              ]),
            ),
            200,
          );
        }
        if (request.url.path.endsWith('/accept')) {
          return http.Response(
            jsonEncode(
              _event(
                id: 'created',
                eventType: 'message_created',
                status: 'accepted',
              ),
            ),
            200,
          );
        }
        if (request.url.path.endsWith('/ignore')) {
          return http.Response(
            jsonEncode(
              _event(
                id: 'ignored',
                eventType: 'message_deleted',
                status: 'ignored',
              ),
            ),
            200,
          );
        }
        return http.Response('{}', 404);
      }),
    );
    client.configure(baseUrl: 'https://secretary.example', token: 'token');
    await _pumpInbox(tester, _auth(client));
    expect(find.text('Готово'), findsNWidgets(2));
    expect(find.text('Пропустить'), findsNWidgets(2));
    await tester.tap(find.byKey(const Key('notification_accept_created')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('notification_ignore_ignored')));
    await tester.pumpAndSettle();
    expect(calls, contains('POST /notifications/created/accept'));
    expect(calls, contains('POST /notifications/ignored/ignore'));
  });

  testWidgets('malformed transport proposal falls back safely', (tester) async {
    final malformed = _event(id: 'bad', eventType: 'message_created')
      ..['proposal'] = {
        'type': 'transport_event',
        'provider': 'telegram',
        'transport': 'mtproto',
        'event_type': 'unknown',
      };
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(jsonEncode(_inbox([malformed])), 200);
        }
        return http.Response('{}', 404);
      }),
    );
    client.configure(baseUrl: 'https://secretary.example', token: 'token');
    await _pumpInbox(tester, _auth(client));
    expect(find.text('raw backend title'), findsOneWidget);
    expect(find.byKey(const Key('notification_card_bad')), findsOneWidget);
  });

  testWidgets('unread context marks read best-effort and opens source object', (
    tester,
  ) async {
    final calls = <String>[];
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        calls.add('${request.method} ${request.url.path}');
        if (request.url.path == '/inbox') {
          return http.Response(
            jsonEncode(
              _inbox([_event(id: 'context', eventType: 'message_created')]),
            ),
            200,
          );
        }
        if (request.url.path == '/notifications/context/read') {
          return http.Response(jsonEncode({'detail': 'read failed'}), 500);
        }
        if (request.url.path == '/objects/mtproto-object-1') {
          return http.Response(jsonEncode(_object()), 200);
        }
        if (request.url.path.endsWith('/neighbors')) {
          return http.Response(
            jsonEncode({'object_id': 'mtproto-object-1', 'neighbors': []}),
            200,
          );
        }
        if (request.url.path.endsWith('/context')) {
          return http.Response(
            jsonEncode({'object': _object(), 'edges': [], 'neighbors': []}),
            200,
          );
        }
        return http.Response('{}', 404);
      }),
    );
    client.configure(baseUrl: 'https://secretary.example', token: 'token');
    await _pumpInbox(tester, _auth(client));
    await tester.tap(find.byKey(const Key('notification_context_context')));
    await tester.pumpAndSettle();
    expect(calls, contains('POST /notifications/context/read'));
    expect(calls, contains('GET /objects/mtproto-object-1'));
    expect(find.text('Work chat'), findsWidgets);
  });

  testWidgets('read transport event does not redundantly mark read', (
    tester,
  ) async {
    final calls = <String>[];
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        calls.add('${request.method} ${request.url.path}');
        if (request.url.path == '/inbox') {
          return http.Response(
            jsonEncode(
              _inbox([
                _event(
                  id: 'read',
                  eventType: 'message_created',
                  status: 'accepted',
                  readAt: '2026-09-01T12:40:00Z',
                ),
              ]),
            ),
            200,
          );
        }
        if (request.url.path == '/objects/mtproto-object-1') {
          return http.Response(jsonEncode(_object()), 200);
        }
        if (request.url.path.endsWith('/neighbors')) {
          return http.Response(
            jsonEncode({'object_id': 'mtproto-object-1', 'neighbors': []}),
            200,
          );
        }
        if (request.url.path.endsWith('/context')) {
          return http.Response(
            jsonEncode({'object': _object(), 'edges': [], 'neighbors': []}),
            200,
          );
        }
        return http.Response('{}', 404);
      }),
    );
    client.configure(baseUrl: 'https://secretary.example', token: 'token');
    await _pumpInbox(tester, _auth(client));
    await tester.tap(find.byKey(const Key('notification_context_read')));
    await tester.pumpAndSettle();
    expect(calls.where((call) => call.contains('/read')), isEmpty);
  });

  testWidgets('mark-read 401 routes through AuthController', (tester) async {
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(
            jsonEncode(
              _inbox([_event(id: 'auth', eventType: 'message_created')]),
            ),
            200,
          );
        }
        if (request.url.path.endsWith('/read')) {
          return http.Response(jsonEncode({'detail': 'unauthorized'}), 401);
        }
        return http.Response('{}', 404);
      }),
    );
    client.configure(baseUrl: 'https://secretary.example', token: 'token');
    final auth = _auth(client);
    await _pumpInbox(tester, auth);
    await tester.tap(find.byKey(const Key('notification_context_auth')));
    await tester.pumpAndSettle();
    expect(auth.status, AuthStatus.needsAuth);
  });

  testWidgets('Telegram source object remains in normal Inbox feed', (
    tester,
  ) async {
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(
            jsonEncode({
              ..._inbox([]),
              'recent_source_objects': [
                {
                  'id': 'source-1',
                  'title': 'Telegram source message',
                  'kind': 'chat_message',
                  'provider': 'telegram',
                  'origin': 'source',
                  'state': 'observed',
                  'status': null,
                  'primary_at': '2026-09-01T12:34:00Z',
                  'excerpt': 'message body',
                },
              ],
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      }),
    );
    client.configure(baseUrl: 'https://secretary.example', token: 'token');
    await _pumpInbox(tester, _auth(client));
    expect(find.text('Последние входящие'), findsOneWidget);
    expect(find.text('Telegram source message'), findsOneWidget);
    expect(find.text('Telegram'), findsNothing);
  });
}
