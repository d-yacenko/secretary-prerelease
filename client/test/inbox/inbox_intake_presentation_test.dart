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
import 'package:personal_secretary/ui/object_presentation.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  const baseUrl = 'https://secretary.example';
  const token = 'inbox-presentation-token';
  const passiveRefreshInterval = Duration(hours: 24);

  Widget buildInbox(MockClient mock) {
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
      home: Scaffold(
        body: InboxScreen(
          apiClient: apiClient,
          authController: auth,
          captureController: capture,
          passiveRefreshInterval: passiveRefreshInterval,
        ),
      ),
    );
  }

  Map<String, dynamic> inboxJson(List<Map<String, dynamic>> recentSources) {
    return {
      'unresolved_notifications': [],
      'recent_source_objects': recentSources,
      'source_sync_status': [],
    };
  }

  testWidgets('note displayed in Inbox with Заметка semantics', (tester) async {
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(
            jsonEncode(inboxJson([
              {
                'id': 'note-1',
                'title': 'My inbox note title',
                'kind': 'note',
                'provider': null,
                'origin': 'user',
                'state': 'confirmed',
                'status': null,
                'primary_at': '2026-08-31T10:00:00Z',
                'excerpt': 'note excerpt body',
              },
            ])),
            200,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    final titleFinder = find.text('My inbox note title');
    expect(titleFinder, findsOneWidget);
    final semantics = tester.getSemantics(titleFinder);
    expect(semantics.label, contains(objectKindLabel('note')));
  });

  testWidgets('web_page displayed in Inbox with Веб-страница semantics', (tester) async {
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(
            jsonEncode(inboxJson([
              {
                'id': 'web-1',
                'title': 'Captured web page',
                'kind': 'web_page',
                'provider': 'web',
                'origin': 'explicit',
                'state': 'observed',
                'status': null,
                'primary_at': '2026-08-31T10:00:00Z',
                'excerpt': 'web excerpt',
              },
            ])),
            200,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    final titleFinder = find.text('Captured web page');
    expect(titleFinder, findsOneWidget);
    final semantics = tester.getSemantics(titleFinder);
    expect(semantics.label, contains(objectKindLabel('web_page')));
  });

  testWidgets('task does not appear merely because it is user-created', (tester) async {
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(
            jsonEncode(inboxJson([
              {
                'id': 'email-1',
                'title': 'Visible email row',
                'kind': 'email',
                'provider': 'gmail',
                'origin': 'source',
                'state': 'observed',
                'status': null,
                'primary_at': '2026-08-31T10:00:00Z',
                'excerpt': 'email body',
              },
            ])),
            200,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    expect(find.text('Visible email row'), findsOneWidget);
    expect(find.text(objectKindLabel('task')), findsNothing);
  });

  testWidgets('compact inbox rows do not overflow horizontally', (tester) async {
    tester.view.physicalSize = const Size(360, 640);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(
            jsonEncode(inboxJson([
              {
                'id': 'note-long',
                'title': 'Very long note title for compact overflow regression test',
                'kind': 'note',
                'provider': null,
                'state': 'confirmed',
                'status': null,
                'primary_at': '2026-08-31T10:00:00Z',
                'excerpt':
                    'Long note excerpt text for compact layout overflow regression',
              },
              {
                'id': 'web-long',
                'title': 'Very long web page title for compact overflow regression',
                'kind': 'web_page',
                'provider': 'web',
                'state': 'observed',
                'status': null,
                'primary_at': '2026-08-31T09:00:00Z',
                'excerpt': 'Long web page excerpt text',
              },
            ])),
            200,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));

    expect(tester.takeException(), isNull);
  });

  testWidgets('inbound telegram chat_message renders Telegram mark in Inbox', (tester) async {
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response.bytes(
            utf8.encode(jsonEncode(inboxJson([
              {
                'id': 'tg-in-1',
                'title': 'Ivan: hello',
                'kind': 'chat_message',
                'provider': 'telegram',
                'origin': 'source',
                'state': 'observed',
                'status': null,
                'primary_at': '2026-09-13T10:00:00Z',
                'excerpt': 'hello',
              },
            ]))),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.text('Ivan: hello'), findsOneWidget);
    expect(find.byKey(const Key('source_mark_telegram')), findsOneWidget);
    expect(find.text('Исходящее Telegram'), findsNothing);
  });

  testWidgets('inbound teams chat_message renders Teams mark in Inbox', (tester) async {
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response.bytes(
            utf8.encode(jsonEncode(inboxJson([
              {
                'id': 'teams-in-1',
                'title': 'Petrushin: hello',
                'kind': 'chat_message',
                'provider': 'teams',
                'origin': 'source',
                'state': 'observed',
                'status': null,
                'primary_at': '2026-09-13T10:00:00Z',
                'excerpt': 'hello',
              },
            ]))),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.text('Petrushin: hello'), findsOneWidget);
    expect(find.byKey(const Key('source_mark_teams')), findsOneWidget);
  });
}
