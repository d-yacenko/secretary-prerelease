import 'dart:async';
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
import 'package:personal_secretary/objects/object_detail_screen.dart';
import 'package:personal_secretary/today/today_screen.dart';

import '../test_secretary_api_client.dart';

void main() {
  const baseUrl = 'https://secretary.example';
  const token = 'dispose-token';

  SecretaryApiClient buildClient(Future<http.Response> todayResponse) {
    final apiClient = testSecretaryApiClient(
      MockClient((request) async {
        if (request.url.path == '/today') {
          return todayResponse;
        }
        if (request.url.path == '/notifications') {
          await Future<void>.delayed(const Duration(milliseconds: 200));
          return http.Response(jsonEncode({'notifications': []}), 200);
        }
        if (request.url.path == '/objects/obj-1') {
          await Future<void>.delayed(const Duration(milliseconds: 200));
          return http.Response(
            jsonEncode({
              'id': 'obj-1',
              'kind': 'email',
              'title': 'Email',
              'body': null,
              'provider': null,
              'external_id': null,
              'canonical_uri': null,
              'status': null,
              'start_at': null,
              'due_at': null,
              'metadata': {},
              'origin': 'source',
              'state': 'observed',
              'confidence': null,
              'created_at': '2026-08-28T08:00:00Z',
              'updated_at': '2026-08-28T08:00:00Z',
            }),
            200,
          );
        }
        if (request.url.path == '/objects/obj-1/neighbors') {
          return http.Response(
            jsonEncode({'object_id': 'obj-1', 'neighbors': []}),
            200,
          );
        }
        if (request.url.path == '/objects/obj-1/context') {
          return http.Response(
            jsonEncode({
              'object': {
                'id': 'obj-1',
                'kind': 'email',
                'title': 'Email',
                'body': null,
                'provider': null,
                'external_id': null,
                'canonical_uri': null,
                'status': null,
                'start_at': null,
                'due_at': null,
                'metadata': {},
                'origin': 'source',
                'state': 'observed',
                'confidence': null,
                'created_at': '2026-08-28T08:00:00Z',
                'updated_at': '2026-08-28T08:00:00Z',
              },
              'edges': [],
              'neighbors': [],
            }),
            200,
          );
        }
        if (request.url.path == '/inbox') {
          return http.Response(
            jsonEncode({
              'unresolved_notifications': [],
              'recent_source_objects': [],
              'source_sync_status': [],
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      }),
    );
    apiClient.configure(baseUrl: baseUrl, token: token);
    return apiClient;
  }

  ({AuthController auth, CaptureController capture}) buildControllers(
    SecretaryApiClient apiClient,
  ) {
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final capture = CaptureController(apiClient: apiClient, authController: auth);
    return (auth: auth, capture: capture);
  }

  testWidgets('TodayScreen does not setState after dispose', (tester) async {
    final completer = Completer<http.Response>();
    final apiClient = buildClient(completer.future);
    final controllers = buildControllers(apiClient);

    await tester.pumpWidget(
      MaterialApp(
        home: TodayScreen(
          apiClient: apiClient,
          authController: controllers.auth,
          captureController: controllers.capture,
        ),
      ),
    );
    await tester.pump();
    await tester.pumpWidget(const MaterialApp(home: SizedBox.shrink()));

    completer.complete(
      http.Response(
        jsonEncode({
          'date': '2026-08-28',
          'timezone': 'Europe/Amsterdam',
          'day_start': '2026-08-28T00:00:00+02:00',
          'tasks': [],
          'calendar_events': [],
          'notifications': [],
        }),
        200,
      ),
    );
    await tester.pump(const Duration(milliseconds: 300));
  });

  testWidgets('InboxScreen does not setState after dispose', (tester) async {
    final apiClient = buildClient(
      Future.value(http.Response('{}', 404)),
    );
    final controllers = buildControllers(apiClient);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: InboxScreen(
            apiClient: apiClient,
            authController: controllers.auth,
            captureController: controllers.capture,
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pumpWidget(const MaterialApp(home: SizedBox.shrink()));
    await tester.pump(const Duration(milliseconds: 300));
  });

  testWidgets('ObjectDetailScreen does not setState after dispose', (tester) async {
    final apiClient = buildClient(
      Future.value(http.Response('{}', 404)),
    );
    final controllers = buildControllers(apiClient);

    await tester.pumpWidget(
      MaterialApp(
        home: ObjectDetailScreen(
          objectId: 'obj-1',
          apiClient: apiClient,
          authController: controllers.auth,
          captureController: controllers.capture,
        ),
      ),
    );
    await tester.pump();
    await tester.pumpWidget(const MaterialApp(home: SizedBox.shrink()));
    await tester.pump(const Duration(milliseconds: 300));
  });
}
