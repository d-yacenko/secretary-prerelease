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
import 'package:personal_secretary/search/search_screen.dart';

void main() {
  const baseUrl = 'https://secretary.example';
  const token = 'search-token';

  Widget buildSearch(MockClient mock) {
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    return MaterialApp(
      home: Scaffold(
        body: SearchScreen(
          apiClient: apiClient,
          authController: auth,
          captureController: CaptureController(
            apiClient: apiClient,
            authController: auth,
          ),
        ),
      ),
    );
  }

  http.Response facetsResponse() {
    return http.Response(
      jsonEncode({
        'kinds': [
          {'value': 'task', 'count': 1},
          {'value': 'email', 'count': 1},
        ],
        'providers': [
          {'value': 'gmail', 'count': 1},
          {'value': 'local_device', 'count': 1},
        ],
      }),
      200,
    );
  }

  testWidgets('search sends GET /search and renders results', (tester) async {
    await tester.pumpWidget(
      buildSearch(MockClient((request) async {
        if (request.url.path == '/search/facets') {
          return facetsResponse();
        }
        if (request.url.path == '/search') {
          expect(request.url.queryParameters['q'], 'alpha task');
          return http.Response(
            jsonEncode([
              {
                'id': 'task-1',
                'kind': 'task',
                'title': 'Alpha task',
                'body': 'Long body text that should be bounded in UI',
                'provider': null,
                'external_id': null,
                'canonical_uri': null,
                'status': 'pending',
                'start_at': null,
                'due_at': null,
                'metadata': {},
                'origin': 'user',
                'state': 'confirmed',
                'confidence': null,
                'created_at': '2026-08-28T08:00:00Z',
                'updated_at': '2026-08-28T08:00:00Z',
              },
            ]),
            200,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField).first, 'alpha task');
    await tester.tap(find.widgetWithText(FilledButton, 'Поиск'));
    await tester.pumpAndSettle();

    expect(find.text('Alpha task'), findsOneWidget);
    expect(find.text('pending'), findsOneWidget);
  });

  testWidgets('search provider filter sends canonical provider value', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      buildSearch(MockClient((request) async {
        if (request.url.path == '/search/facets') {
          return facetsResponse();
        }
        if (request.url.path == '/search') {
          expect(request.url.queryParameters['provider'], 'gmail');
          return http.Response('[]', 200);
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField).first, 'mail');
    await tester.tap(find.byIcon(Icons.storage_outlined));
    await tester.pumpAndSettle();
    expect(find.byType(BottomSheet), findsNothing);
    await tester.tap(find.text('Gmail').last);
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Поиск'));
    await tester.pumpAndSettle();
  });

  testWidgets('desktop type filter uses anchored menu', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      buildSearch(MockClient((request) async {
        if (request.url.path == '/search/facets') {
          return facetsResponse();
        }
        if (request.url.path == '/search') {
          expect(request.url.queryParameters['kind'], 'task');
          return http.Response('[]', 200);
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField).first, 'alpha');
    await tester.tap(find.byIcon(Icons.category_outlined));
    await tester.pumpAndSettle();
    expect(find.byType(BottomSheet), findsNothing);
    await tester.tap(find.text('Задача').last);
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Поиск'));
    await tester.pumpAndSettle();
  });

  testWidgets('desktop sort filter sends newest', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      buildSearch(MockClient((request) async {
        if (request.url.path == '/search/facets') {
          return facetsResponse();
        }
        if (request.url.path == '/search') {
          expect(request.url.queryParameters['sort'], 'newest');
          return http.Response('[]', 200);
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField).first, 'alpha');
    await tester.tap(find.byIcon(Icons.sort));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Сначала новые').last);
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Поиск'));
    await tester.pumpAndSettle();
  });

  testWidgets('search shows Russian provider label and date', (tester) async {
    await tester.pumpWidget(
      buildSearch(MockClient((request) async {
        if (request.url.path == '/search/facets') {
          return facetsResponse();
        }
        if (request.url.path == '/search') {
          return http.Response.bytes(
            utf8.encode(jsonEncode([
              {
                'id': 'email-1',
                'kind': 'email',
                'title': 'Письмо от преподавателя',
                'body': 'Короткий фрагмент',
                'provider': 'gmail',
                'external_id': null,
                'canonical_uri': null,
                'status': null,
                'start_at': null,
                'due_at': null,
                'occurred_at': '2026-08-30T15:43:00Z',
                'metadata': {},
                'origin': 'source',
                'state': 'observed',
                'confidence': null,
                'created_at': '2026-08-28T08:00:00Z',
                'updated_at': '2026-08-28T08:00:00Z',
              },
            ])),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField).first, 'письмо');
    await tester.tap(find.widgetWithText(FilledButton, 'Поиск'));
    await tester.pumpAndSettle();

    expect(find.text('Письмо от преподавателя'), findsOneWidget);
    expect(find.byKey(const Key('source_mark_google')), findsOneWidget);
    expect(find.textContaining('30.08.2026'), findsOneWidget);
    expect(find.textContaining('Письмо · Gmail'), findsNothing);
    expect(find.textContaining('Gmail'), findsNothing);
    expect(find.byIcon(Icons.sort), findsOneWidget);
    expect(find.text('Показано: 1'), findsOneWidget);
  });

  testWidgets('search empty state', (tester) async {
    await tester.pumpWidget(
      buildSearch(MockClient((request) async {
        if (request.url.path == '/search/facets') {
          return facetsResponse();
        }
        if (request.url.path == '/search') {
          return http.Response('[]', 200);
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, 'nothing');
    await tester.tap(find.widgetWithText(FilledButton, 'Поиск'));
    await tester.pumpAndSettle();
    expect(find.text('Ничего не найдено'), findsOneWidget);
  });

  testWidgets('search 401 exits authenticated UI', (tester) async {
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/search/facets') {
          return facetsResponse();
        }
        return http.Response('{"detail":"unauthorized"}', 401);
      }),
    );
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SearchScreen(
            apiClient: apiClient,
            authController: auth,
            captureController: CaptureController(
              apiClient: apiClient,
              authController: auth,
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, 'x');
    await tester.tap(find.widgetWithText(FilledButton, 'Поиск'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(auth.status, AuthStatus.needsAuth);
  });

  testWidgets('search uses compact header without type source line', (tester) async {
    await tester.pumpWidget(
      buildSearch(MockClient((request) async {
        if (request.url.path == '/search/facets') {
          return facetsResponse();
        }
        if (request.url.path == '/search') {
          return http.Response.bytes(
            utf8.encode(jsonEncode([
              {
                'id': 'email-1',
                'kind': 'email',
                'title': 'test для электронного секретаря',
                'body': 'это тестовое письмо',
                'provider': 'gmail',
                'external_id': null,
                'canonical_uri': null,
                'status': null,
                'start_at': null,
                'due_at': null,
                'occurred_at': '2026-08-31T17:33:00Z',
                'metadata': {},
                'origin': 'source',
                'state': 'observed',
                'confidence': null,
                'created_at': '2026-08-31T08:00:00Z',
                'updated_at': '2026-08-31T08:00:00Z',
              },
            ])),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField).first, 'test');
    await tester.tap(find.widgetWithText(FilledButton, 'Поиск'));
    await tester.pumpAndSettle();

    expect(find.text('test для электронного секретаря'), findsOneWidget);
    expect(find.byKey(const Key('source_mark_google')), findsOneWidget);
    expect(find.textContaining('31.08.2026'), findsOneWidget);
    expect(find.textContaining('Письмо · Gmail'), findsNothing);
    expect(find.textContaining('это тестовое письмо'), findsOneWidget);
  });
}
