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
import 'package:personal_secretary/navigation/secretary_navigation.dart';
import 'package:personal_secretary/objects/object_detail_screen.dart';

void main() {
  const baseUrl = 'https://secretary.example';
  const token = 'delete-token';

  Map<String, dynamic> objectPayload({required String id, String kind = 'note'}) {
    return {
      'id': id,
      'kind': kind,
      'title': 'Disposable',
      'body': 'body',
      'provider': null,
      'external_id': null,
      'canonical_uri': null,
      'status': null,
      'start_at': null,
      'due_at': null,
      'metadata': {},
      'origin': 'user',
      'state': 'confirmed',
      'confidence': null,
      'created_at': '2026-01-01T00:00:00Z',
      'updated_at': '2026-01-01T00:00:00Z',
    };
  }

  Widget buildApp(MockClient mock, {required void Function(ObjectDetailNavigationResult?) onResult}) {
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final capture = CaptureController(apiClient: apiClient, authController: auth);
    return MaterialApp(
      home: Builder(
        builder: (context) => Scaffold(
          body: FilledButton(
            onPressed: () async {
              final result = await openObjectDetail(
                context,
                objectId: 'note-1',
                apiClient: apiClient,
                authController: auth,
                captureController: capture,
              );
              onResult(result);
            },
            child: const Text('Open'),
          ),
        ),
      ),
    );
  }

  testWidgets('successful delete pops navigation result', (tester) async {
    var deleteCalls = 0;
    ObjectDetailNavigationResult? popped;
    await tester.pumpWidget(
      buildApp(
        MockClient((request) async {
          if (request.method == 'GET' && request.url.path == '/objects/note-1') {
            return http.Response(jsonEncode(objectPayload(id: 'note-1')), 200);
          }
          if (request.method == 'GET' && request.url.path == '/objects/note-1/neighbors') {
            return http.Response(
              jsonEncode({'object_id': 'note-1', 'neighbors': []}),
              200,
            );
          }
          if (request.method == 'GET' && request.url.path == '/objects/note-1/context') {
            return http.Response(
              jsonEncode({
                'object': objectPayload(id: 'note-1'),
                'edges': [],
                'neighbors': [],
              }),
              200,
            );
          }
          if (request.method == 'DELETE' && request.url.path == '/objects/note-1') {
            deleteCalls += 1;
            return http.Response(
              jsonEncode({
                'object_id': 'note-1',
                'deleted_at': '2026-01-01T00:00:00Z',
                'already_deleted': false,
              }),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
        onResult: (result) => popped = result,
      ),
    );

    await tester.tap(find.text('Open'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('object_detail_delete')));
    await tester.pumpAndSettle();
    await tester.tap(
      find.descendant(
        of: find.byType(AlertDialog),
        matching: find.widgetWithText(FilledButton, 'Удалить'),
      ),
    );
    await tester.pumpAndSettle();

    expect(deleteCalls, 1);
    expect(popped?.deletedObjectId, 'note-1');
    expect(find.byType(ObjectDetailScreen), findsNothing);
  });

  testWidgets('failed delete keeps detail open', (tester) async {
    await tester.pumpWidget(
      buildApp(
        MockClient((request) async {
          if (request.method == 'GET' && request.url.path == '/objects/note-1') {
            return http.Response(jsonEncode(objectPayload(id: 'note-1')), 200);
          }
          if (request.method == 'GET' && request.url.path == '/objects/note-1/neighbors') {
            return http.Response(
              jsonEncode({'object_id': 'note-1', 'neighbors': []}),
              200,
            );
          }
          if (request.method == 'GET' && request.url.path == '/objects/note-1/context') {
            return http.Response(
              jsonEncode({
                'object': objectPayload(id: 'note-1'),
                'edges': [],
                'neighbors': [],
              }),
              200,
            );
          }
          if (request.method == 'DELETE' && request.url.path == '/objects/note-1') {
            return http.Response('{"message":"delete failed"}', 500);
          }
          return http.Response('{}', 404);
        }),
        onResult: (_) {},
      ),
    );

    await tester.tap(find.text('Open'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('object_detail_delete')));
    await tester.pumpAndSettle();
    await tester.tap(
      find.descendant(
        of: find.byType(AlertDialog),
        matching: find.widgetWithText(FilledButton, 'Удалить'),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Disposable'), findsWidgets);
    expect(find.text('Request failed (500)'), findsOneWidget);
  });
}

class FakeTokenStore implements TokenStore {
  @override
  Future<String?> readToken() async => 'delete-token';

  @override
  Future<void> writeToken(String token) async {}

  @override
  Future<void> deleteToken() async {}
}

class FakeServerUrlStore implements ServerUrlStore {
  @override
  Future<String?> readServerUrl() async => 'https://secretary.example';

  @override
  Future<void> writeServerUrl(String url) async {}

  @override
  Future<void> deleteServerUrl() async {}
}
