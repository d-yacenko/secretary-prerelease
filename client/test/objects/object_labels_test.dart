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
import 'package:personal_secretary/objects/object_detail_screen.dart';

void main() {
  const baseUrl = 'https://secretary.example';
  const token = 'object-token';

  Map<String, dynamic> objectPayload({
    String id = 'email-1',
    String kind = 'email',
  }) {
    return {
      'id': id,
      'kind': kind,
      'title': kind == 'label' ? 'Work' : 'Inbound email',
      'body': 'body',
      'provider': kind == 'email' ? 'gmail' : null,
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
    };
  }

  Map<String, dynamic> labelJson({
    String id = 'label-1',
    String title = 'Work',
  }) {
    return {
      'id': id,
      'title': title,
      'object_count': 1,
      'created_at': '2026-09-07T00:00:00Z',
      'updated_at': '2026-09-07T00:00:00Z',
    };
  }

  Widget buildDetail(MockClient mock, {String objectId = 'email-1'}) {
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    return MaterialApp(
      home: ObjectDetailScreen(
        objectId: objectId,
        apiClient: apiClient,
        authController: auth,
        captureController: CaptureController(
          apiClient: apiClient,
          authController: auth,
        ),
      ),
    );
  }

  http.Response emptyNeighbors(String id) {
    return http.Response(jsonEncode({'object_id': id, 'neighbors': []}), 200);
  }

  http.Response emptyContext(Map<String, dynamic> object) {
    return http.Response(
      jsonEncode({'object': object, 'edges': [], 'neighbors': []}),
      200,
    );
  }

  testWidgets('current label chips load', (tester) async {
    await tester.pumpWidget(
      buildDetail(MockClient((request) async {
        if (request.url.path == '/objects/email-1') {
          return http.Response(jsonEncode(objectPayload()), 200);
        }
        if (request.url.path == '/objects/email-1/neighbors') {
          return emptyNeighbors('email-1');
        }
        if (request.url.path == '/objects/email-1/context') {
          return emptyContext(objectPayload());
        }
        if (request.url.path == '/objects/email-1/labels') {
          return http.Response(jsonEncode({'labels': [labelJson()]}), 200);
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();
    expect(find.text('Метки'), findsOneWidget);
    expect(find.text('Work'), findsOneWidget);
    expect(find.byKey(const Key('object_add_label')), findsOneWidget);
  });

  testWidgets('empty labels state', (tester) async {
    await tester.pumpWidget(
      buildDetail(MockClient((request) async {
        if (request.url.path == '/objects/email-1') {
          return http.Response(jsonEncode(objectPayload()), 200);
        }
        if (request.url.path == '/objects/email-1/neighbors') {
          return emptyNeighbors('email-1');
        }
        if (request.url.path == '/objects/email-1/context') {
          return emptyContext(objectPayload());
        }
        if (request.url.path == '/objects/email-1/labels') {
          return http.Response(jsonEncode({'labels': []}), 200);
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();
    expect(find.text('Нет меток'), findsOneWidget);
  });

  testWidgets('add existing label without duplicating assigned', (tester) async {
    final assigned = <String>{};
    await tester.pumpWidget(
      buildDetail(MockClient((request) async {
        if (request.url.path == '/objects/email-1') {
          return http.Response(jsonEncode(objectPayload()), 200);
        }
        if (request.url.path == '/objects/email-1/neighbors') {
          return emptyNeighbors('email-1');
        }
        if (request.url.path == '/objects/email-1/context') {
          return emptyContext(objectPayload());
        }
        if (request.url.path == '/objects/email-1/labels' &&
            request.method == 'GET') {
          return http.Response(
            jsonEncode({
              'labels': assigned.contains('label-1') ? [labelJson()] : [],
            }),
            200,
          );
        }
        if (request.url.path == '/labels') {
          return http.Response(
            jsonEncode({
              'labels': [
                labelJson(),
                labelJson(id: 'label-2', title: 'Home'),
              ],
            }),
            200,
          );
        }
        if (request.method == 'POST' &&
            request.url.path == '/objects/email-1/labels/label-2') {
          assigned.add('label-2');
          return http.Response(
            jsonEncode({
              'object_id': 'email-1',
              'label_id': 'label-2',
              'created': true,
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('object_add_label')));
    await tester.pumpAndSettle();
    expect(find.text('Home'), findsOneWidget);
    await tester.tap(find.text('Home'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('object_label_chip_label-2')), findsOneWidget);
    await tester.tap(find.byKey(const Key('object_add_label')));
    await tester.pumpAndSettle();
    final assignedTile = tester.widget<ListTile>(
      find.widgetWithText(ListTile, 'Home'),
    );
    expect(assignedTile.enabled, isFalse);
  });

  testWidgets('create-and-assign', (tester) async {
    await tester.pumpWidget(
      buildDetail(MockClient((request) async {
        if (request.url.path == '/objects/email-1') {
          return http.Response(jsonEncode(objectPayload()), 200);
        }
        if (request.url.path == '/objects/email-1/neighbors') {
          return emptyNeighbors('email-1');
        }
        if (request.url.path == '/objects/email-1/context') {
          return emptyContext(objectPayload());
        }
        if (request.url.path == '/objects/email-1/labels' &&
            request.method == 'GET') {
          return http.Response(jsonEncode({'labels': []}), 200);
        }
        if (request.url.path == '/labels' && request.method == 'GET') {
          return http.Response(jsonEncode({'labels': []}), 200);
        }
        if (request.url.path == '/labels' && request.method == 'POST') {
          return http.Response(
            jsonEncode({
              'label': labelJson(id: 'label-new', title: 'Science'),
              'created': true,
            }),
            200,
          );
        }
        if (request.method == 'POST' &&
            request.url.path == '/objects/email-1/labels/label-new') {
          return http.Response(
            jsonEncode({
              'object_id': 'email-1',
              'label_id': 'label-new',
              'created': true,
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('object_add_label')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Создать новую метку'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).last, 'Science');
    await tester.tap(find.widgetWithText(FilledButton, 'Создать'));
    await tester.pumpAndSettle();
    expect(find.text('Science'), findsOneWidget);
  });

  testWidgets('remove assignment', (tester) async {
    var removed = false;
    await tester.pumpWidget(
      buildDetail(MockClient((request) async {
        if (request.url.path == '/objects/email-1') {
          return http.Response(jsonEncode(objectPayload()), 200);
        }
        if (request.url.path == '/objects/email-1/neighbors') {
          return emptyNeighbors('email-1');
        }
        if (request.url.path == '/objects/email-1/context') {
          return emptyContext(objectPayload());
        }
        if (request.url.path == '/objects/email-1/labels' &&
            request.method == 'GET') {
          return http.Response(
            jsonEncode({'labels': removed ? [] : [labelJson()]}),
            200,
          );
        }
        if (request.method == 'DELETE' &&
            request.url.path == '/objects/email-1/labels/label-1') {
          removed = true;
          return http.Response(
            jsonEncode({
              'object_id': 'email-1',
              'label_id': 'label-1',
              'changed': true,
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('object_label_remove_label-1')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('object_label_chip_label-1')), findsNothing);
  });

  testWidgets('API error preserves current chips', (tester) async {
    await tester.pumpWidget(
      buildDetail(MockClient((request) async {
        if (request.url.path == '/objects/email-1') {
          return http.Response(jsonEncode(objectPayload()), 200);
        }
        if (request.url.path == '/objects/email-1/neighbors') {
          return emptyNeighbors('email-1');
        }
        if (request.url.path == '/objects/email-1/context') {
          return emptyContext(objectPayload());
        }
        if (request.url.path == '/objects/email-1/labels') {
          return http.Response(jsonEncode({'labels': [labelJson()]}), 200);
        }
        if (request.url.path == '/labels') {
          return http.Response(
            jsonEncode({'labels': [labelJson(id: 'label-2', title: 'Home')]}),
            200,
          );
        }
        if (request.method == 'POST') {
          return http.Response('{"detail":"nope"}', 500);
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('object_add_label')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Home'));
    await tester.pumpAndSettle();
    expect(find.text('Work'), findsOneWidget);
    expect(find.text('Home'), findsNothing);
    expect(find.text('nope'), findsOneWidget);
  });

  testWidgets('label object has no assignment controls', (tester) async {
    await tester.pumpWidget(
      buildDetail(
        MockClient((request) async {
          if (request.url.path == '/objects/label-1') {
            return http.Response(
              jsonEncode(objectPayload(id: 'label-1', kind: 'label')),
              200,
            );
          }
          if (request.url.path == '/objects/label-1/neighbors') {
            return emptyNeighbors('label-1');
          }
          if (request.url.path == '/objects/label-1/context') {
            return emptyContext(objectPayload(id: 'label-1', kind: 'label'));
          }
          return http.Response('{}', 404);
        }),
        objectId: 'label-1',
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('object_add_label')), findsNothing);
    expect(find.byKey(const Key('object_detail_delete')), findsNothing);
    expect(find.textContaining('Аккаунт'), findsOneWidget);
  });
}
