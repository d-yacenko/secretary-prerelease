import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/capture/capture_controller.dart';
import 'package:personal_secretary/objects/object_detail_screen.dart';

void main() {
  const baseUrl = 'https://secretary.example';
  const token = 'object-token';

  Map<String, dynamic> objectPayload({
    String? canonicalUri,
    String? body,
    String? status,
  }) {
    return {
      'id': 'email-1',
      'kind': 'email',
      'title': 'Inbound email',
      'body': body,
      'provider': 'gmail',
      'external_id': 'ext-1',
      'canonical_uri': canonicalUri,
      'status': status,
      'start_at': null,
      'due_at': null,
      'metadata': {},
      'origin': 'source',
      'state': 'observed',
      'confidence': null,
      'created_at': '2026-08-28T08:00:00Z',
      'updated_at': '2026-08-28T08:00:00Z',
    };
  }

  Widget buildDetail(MockClient mock) {
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
      home: ObjectDetailScreen(
        objectId: 'email-1',
        apiClient: apiClient,
        authController: auth,
        captureController: capture,
      ),
    );
  }

  testWidgets('fields and neighbors render', (tester) async {
    await tester.pumpWidget(
      buildDetail(MockClient((request) async {
        if (request.url.path == '/objects/email-1') {
          return http.Response(
            jsonEncode(objectPayload(body: 'Email body')),
            200,
          );
        }
        if (request.url.path == '/objects/email-1/neighbors') {
          return http.Response(
            jsonEncode({
              'object_id': 'email-1',
              'neighbors': [
                {
                  'object': {
                    'id': 'task-2',
                    'kind': 'task',
                    'title': 'Related task',
                    'body': null,
                    'provider': null,
                    'external_id': null,
                    'canonical_uri': null,
                    'status': null,
                    'start_at': null,
                    'due_at': null,
                    'metadata': {},
                    'origin': 'agent',
                    'state': 'confirmed',
                    'confidence': 0.8,
                    'created_at': '2026-08-28T08:00:00Z',
                    'updated_at': '2026-08-28T08:00:00Z',
                  },
                  'edge': {
                    'id': 'edge-1',
                    'source_id': 'task-2',
                    'target_id': 'email-1',
                    'type': 'references',
                    'origin': 'agent',
                    'confidence': 0.8,
                    'state': 'confirmed',
                    'metadata': {},
                    'created_at': '2026-08-28T08:00:00Z',
                    'updated_at': '2026-08-28T08:00:00Z',
                  },
                  'direction': 'incoming',
                },
              ],
            }),
            200,
          );
        }
        if (request.url.path == '/objects/email-1/context') {
          return http.Response(
            jsonEncode({
              'object': objectPayload(body: 'Email body'),
              'edges': [],
              'neighbors': [],
            }),
            200,
          );
        }
        if (request.url.path == '/objects/email-1/labels') {
          return http.Response(jsonEncode({'labels': []}), 200);
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    expect(find.text('Inbound email'), findsWidgets);
    expect(find.text('Email body'), findsOneWidget);
    expect(find.text('Related task'), findsOneWidget);
    expect(find.textContaining('Ссылается на'), findsOneWidget);
    expect(find.byType(SelectionArea), findsWidgets);
  });

  testWidgets('missing optional fields do not crash', (tester) async {
    await tester.pumpWidget(
      buildDetail(MockClient((request) async {
        if (request.url.path == '/objects/email-1') {
          return http.Response(jsonEncode(objectPayload()), 200);
        }
        if (request.url.path == '/objects/email-1/neighbors') {
          return http.Response(
            jsonEncode({'object_id': 'email-1', 'neighbors': []}),
            200,
          );
        }
        if (request.url.path == '/objects/email-1/context') {
          return http.Response(
            jsonEncode({
              'object': objectPayload(),
              'edges': [],
              'neighbors': [],
            }),
            200,
          );
        }
        if (request.url.path == '/objects/email-1/labels') {
          return http.Response(jsonEncode({'labels': []}), 200);
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    expect(find.text('Inbound email'), findsWidgets);
    expect(find.text('Статус'), findsNothing);
  });

  testWidgets('canonical URI does not expose credentials', (tester) async {
    await tester.pumpWidget(
      buildDetail(MockClient((request) async {
        if (request.url.path == '/objects/email-1') {
          return http.Response(
            jsonEncode(
              objectPayload(
                canonicalUri: 'https://user:secret@mail.example/message/1',
              ),
            ),
            200,
          );
        }
        if (request.url.path == '/objects/email-1/neighbors') {
          return http.Response(
            jsonEncode({'object_id': 'email-1', 'neighbors': []}),
            200,
          );
        }
        if (request.url.path == '/objects/email-1/context') {
          return http.Response(
            jsonEncode({
              'object': objectPayload(
                canonicalUri: 'https://user:secret@mail.example/message/1',
              ),
              'edges': [],
              'neighbors': [],
            }),
            200,
          );
        }
        if (request.url.path == '/objects/email-1/labels') {
          return http.Response(jsonEncode({'labels': []}), 200);
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('Подробности'));
    await tester.pumpAndSettle();

    expect(find.textContaining('secret'), findsNothing);
    expect(find.textContaining('mail.example/message/1'), findsOneWidget);
  });
}
