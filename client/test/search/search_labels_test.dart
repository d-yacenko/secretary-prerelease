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
        ],
        'providers': [
          {'value': 'gmail', 'count': 1},
        ],
      }),
      200,
    );
  }

  http.Response labelsResponse(List<Map<String, dynamic>> labels) {
    return http.Response(jsonEncode({'labels': labels}), 200);
  }

  Map<String, dynamic> searchHit() {
    return {
      'id': 'task-1',
      'kind': 'task',
      'title': 'Alpha task',
      'body': 'body',
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
    };
  }

  testWidgets('labels load independently from facets', (tester) async {
    var labelsHit = false;
    var facetsHit = false;
    await tester.pumpWidget(
      buildSearch(MockClient((request) async {
        if (request.url.path == '/search/facets') {
          facetsHit = true;
          return facetsResponse();
        }
        if (request.url.path == '/labels') {
          labelsHit = true;
          return labelsResponse([
            {
              'id': 'label-1',
              'title': 'Work',
              'object_count': 1,
            },
          ]);
        }
        return http.Response('[]', 200);
      })),
    );
    await tester.pumpAndSettle();
    expect(labelsHit, isTrue);
    expect(facetsHit, isTrue);
    expect(find.byKey(const Key('search_label_filter')), findsOneWidget);
  });

  testWidgets('zero labels hides compact filter', (tester) async {
    await tester.pumpWidget(
      buildSearch(MockClient((request) async {
        if (request.url.path == '/search/facets') {
          return facetsResponse();
        }
        if (request.url.path == '/labels') {
          return labelsResponse([]);
        }
        return http.Response('[]', 200);
      })),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('search_label_filter')), findsNothing);
  });

  testWidgets('selecting label sends label_id and changing reruns search', (
    tester,
  ) async {
    final labelQueries = <String?>[];
    await tester.pumpWidget(
      buildSearch(MockClient((request) async {
        if (request.url.path == '/search/facets') {
          return facetsResponse();
        }
        if (request.url.path == '/labels') {
          return labelsResponse([
            {'id': 'label-1', 'title': 'Work', 'object_count': 1},
            {'id': 'label-2', 'title': 'Home', 'object_count': 1},
          ]);
        }
        if (request.url.path == '/search') {
          labelQueries.add(request.url.queryParameters['label_id']);
          return http.Response(jsonEncode([searchHit()]), 200);
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, 'adh');
    await tester.tap(find.widgetWithText(FilledButton, 'Поиск'));
    await tester.pumpAndSettle();
    expect(labelQueries.last, isNull);

    await tester.tap(find.byKey(const Key('search_label_filter')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Work').last);
    await tester.pumpAndSettle();
    expect(labelQueries.last, 'label-1');

    await tester.tap(find.byKey(const Key('search_label_filter')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Home').last);
    await tester.pumpAndSettle();
    expect(labelQueries.last, 'label-2');

    await tester.tap(find.byKey(const Key('search_label_filter')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Метка: Все'));
    await tester.pumpAndSettle();
    expect(labelQueries.last, isNull);
  });

  testWidgets('label load failure does not break search', (tester) async {
    await tester.pumpWidget(
      buildSearch(MockClient((request) async {
        if (request.url.path == '/search/facets') {
          return facetsResponse();
        }
        if (request.url.path == '/labels') {
          return http.Response('{"detail":"labels down"}', 500);
        }
        if (request.url.path == '/search') {
          return http.Response(jsonEncode([searchHit()]), 200);
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('search_label_filter')), findsNothing);
    await tester.enterText(find.byType(TextField).first, 'alpha');
    await tester.tap(find.widgetWithText(FilledButton, 'Поиск'));
    await tester.pumpAndSettle();
    expect(find.text('Alpha task'), findsOneWidget);
  });

  testWidgets('label auth failure follows client behavior', (tester) async {
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
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(auth.status, AuthStatus.needsAuth);
  });

  testWidgets(
    'narrow Android viewport label sheet scrolls to a late label',
    (tester) async {
      tester.view.physicalSize = const Size(360, 640);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      const lateId = 'label-24';
      const lateTitle = 'Label 24';
      final catalog = [
        for (var index = 1; index <= 24; index++)
          {
            'id': 'label-$index',
            'title': 'Label $index',
            'object_count': 1,
          },
      ];
      final labelQueries = <String?>[];

      await tester.pumpWidget(
        buildSearch(MockClient((request) async {
          if (request.url.path == '/search/facets') {
            return facetsResponse();
          }
          if (request.url.path == '/labels') {
            return labelsResponse(catalog);
          }
          if (request.url.path == '/search') {
            labelQueries.add(request.url.queryParameters['label_id']);
            return http.Response(jsonEncode([searchHit()]), 200);
          }
          return http.Response('{}', 404);
        })),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);

      await tester.enterText(find.byType(TextField).first, 'adh');
      await tester.tap(find.widgetWithText(FilledButton, 'Поиск'));
      await tester.pumpAndSettle();
      expect(labelQueries.last, isNull);

      await tester.tap(find.byKey(const Key('search_label_filter')));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(find.byKey(const Key('search_label_filter_sheet')), findsOneWidget);
      expect(find.text('Метка: Все'), findsOneWidget);
      expect(find.text('Label 1'), findsOneWidget);
      expect(find.text(lateTitle), findsNothing);

      await tester.scrollUntilVisible(
        find.text(lateTitle),
        200,
        scrollable: find
            .descendant(
              of: find.byKey(const Key('search_label_filter_sheet')),
              matching: find.byType(Scrollable),
            )
            .first,
      );
      await tester.pumpAndSettle();
      expect(find.text(lateTitle), findsOneWidget);
      expect(tester.takeException(), isNull);

      await tester.tap(find.text(lateTitle));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('search_label_filter_sheet')), findsNothing);
      expect(labelQueries.last, lateId);

      await tester.tap(find.byKey(const Key('search_label_filter')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Метка: Все'));
      await tester.pumpAndSettle();
      expect(labelQueries.last, isNull);
      expect(tester.takeException(), isNull);
    },
  );
}
