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
import 'package:personal_secretary/capture/capture_screen.dart';
import 'package:personal_secretary/inbox/inbox_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

Future<void> pumpFrames(WidgetTester tester, {int frames = 6}) async {
  for (var i = 0; i < frames; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  const baseUrl = 'https://secretary.example';
  const token = 'inbox-universal-token';

  Widget buildInbox(MockClient mock, {CaptureController? capture}) {
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final captureController = capture ??
        CaptureController(apiClient: apiClient, authController: auth);
    return MaterialApp(
      home: Scaffold(
        body: InboxScreen(
          apiClient: apiClient,
          authController: auth,
          captureController: captureController,
          passiveRefreshInterval: const Duration(hours: 24),
        ),
      ),
    );
  }

  Map<String, dynamic> inboxJson() {
    return {
      'unresolved_notifications': [],
      'recent_source_objects': [],
      'source_sync_status': [],
    };
  }

  testWidgets('plain text submits capture note', (tester) async {
    String? path;
    Map<String, dynamic>? body;
    int inboxCalls = 0;
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          inboxCalls++;
          return http.Response(jsonEncode(inboxJson()), 200);
        }
        if (request.url.path == '/capture/note') {
          path = request.url.path;
          body = jsonDecode(request.body) as Map<String, dynamic>;
          return http.Response(jsonEncode({'note_id': 'n1'}), 201);
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
      find.byKey(const Key('inbox_link_input')),
      'Идея про проектное обучение',
    );
    await tester.tap(find.byKey(const Key('inbox_link_add_button')));
    await tester.pumpAndSettle();

    expect(path, '/capture/note');
    expect(body!['text'], 'Идея про проектное обучение');
    expect(find.text('Заметка добавлена'), findsOneWidget);
    expect(inboxCalls, greaterThanOrEqualTo(2));
  });

  testWidgets('embedded url text submits capture note', (tester) async {
    String? path;
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(jsonEncode(inboxJson()), 200);
        }
        if (request.url.path == '/capture/note') {
          path = request.url.path;
          return http.Response(jsonEncode({'note_id': 'n2'}), 201);
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
      find.byKey(const Key('inbox_link_input')),
      'Прочитать https://example.org завтра',
    );
    await tester.tap(find.byKey(const Key('inbox_link_add_button')));
    await tester.pumpAndSettle();

    expect(path, '/capture/note');
  });

  testWidgets('exact generic url submits intake link', (tester) async {
    String? path;
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(jsonEncode(inboxJson()), 200);
        }
        if (request.url.path == '/intake/link') {
          path = request.url.path;
          return http.Response(
            jsonEncode({
              'object_id': 'web-1',
              'provider': 'web',
              'kind': 'web_page',
              'status': 'created',
              'content_status': 'ready',
              'content_jobs_enqueued': 1,
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
      find.byKey(const Key('inbox_link_input')),
      'https://example.org/article',
    );
    await tester.tap(find.byKey(const Key('inbox_link_add_button')));
    await tester.pumpAndSettle();

    expect(path, '/intake/link');
  });

  testWidgets('google docs url submits intake link not provider-specific path',
      (tester) async {
    String? path;
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(jsonEncode(inboxJson()), 200);
        }
        if (request.url.path == '/intake/link') {
          path = request.url.path;
          return http.Response(
            jsonEncode({
              'object_id': 'drive-1',
              'provider': 'google_drive',
              'kind': 'file',
              'status': 'created',
              'content_status': 'pending',
              'content_jobs_enqueued': 1,
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
      find.byKey(const Key('inbox_link_input')),
      'https://docs.google.com/document/d/abc/edit',
    );
    await tester.tap(find.byKey(const Key('inbox_link_add_button')));
    await tester.pumpAndSettle();

    expect(path, '/intake/link');
  });

  testWidgets('yandex disk url submits intake link', (tester) async {
    String? path;
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(jsonEncode(inboxJson()), 200);
        }
        if (request.url.path == '/intake/link') {
          path = request.url.path;
          return http.Response(
            jsonEncode({
              'object_id': 'yandex-1',
              'provider': 'yandex_disk',
              'kind': 'file',
              'status': 'created',
              'content_status': 'metadata_only',
              'content_jobs_enqueued': 0,
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
      find.byKey(const Key('inbox_link_input')),
      'https://disk.yandex.ru/d/abc123',
    );
    await tester.tap(find.byKey(const Key('inbox_link_add_button')));
    await tester.pumpAndSettle();

    expect(path, '/intake/link');
  });

  testWidgets('inbox intake bar shows microphone button', (tester) async {
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(jsonEncode(inboxJson()), 200);
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('inbox_voice_button')), findsOneWidget);
    expect(find.text('Введите заметку или вставьте ссылку'), findsOneWidget);
  });

  testWidgets('voice transcript fills inbox input without auto submit', (tester) async {
    int noteCalls = 0;
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(jsonEncode(inboxJson()), 200);
        }
        if (request.url.path == '/assistant/transcribe') {
          return http.Response.bytes(
            utf8.encode(jsonEncode({'text': 'Голосовая заметка'})),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        if (request.url.path == '/capture/note') {
          noteCalls++;
          return http.Response(jsonEncode({'note_id': 'vn1'}), 201);
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.runAsync(() async {
      await tester.tap(find.byKey(const Key('inbox_voice_button')));
      await Future<void>.delayed(const Duration(milliseconds: 200));
    });
    await pumpFrames(tester);
    expect(find.textContaining('Запись'), findsOneWidget);

    await tester.runAsync(() async {
      await tester.tap(find.byKey(const Key('inbox_voice_button')));
      await Future<void>.delayed(const Duration(milliseconds: 300));
    });
    await pumpFrames(tester, frames: 10);

    final field = tester.widget<TextField>(find.byKey(const Key('inbox_link_input')));
    expect(field.controller!.text, contains('Голосовая заметка'));
    expect(noteCalls, 0);

    await tester.tap(find.byKey(const Key('inbox_link_add_button')));
    await tester.pumpAndSettle();
    expect(noteCalls, 1);
  });

  testWidgets('voice transcript appends to existing inbox text', (tester) async {
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(jsonEncode(inboxJson()), 200);
        }
        if (request.url.path == '/assistant/transcribe') {
          return http.Response.bytes(
            utf8.encode(jsonEncode({'text': 'дополнение'})),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
      find.byKey(const Key('inbox_link_input')),
      'Уже есть текст',
    );

    await tester.runAsync(() async {
      await tester.tap(find.byKey(const Key('inbox_voice_button')));
      await Future<void>.delayed(const Duration(milliseconds: 200));
    });
    await pumpFrames(tester);
    await tester.runAsync(() async {
      await tester.tap(find.byKey(const Key('inbox_voice_button')));
      await Future<void>.delayed(const Duration(milliseconds: 300));
    });
    await pumpFrames(tester, frames: 10);

    final field = tester.widget<TextField>(find.byKey(const Key('inbox_link_input')));
    expect(field.controller!.text, 'Уже есть текст дополнение');
  });

  testWidgets('voice transcript exact url does not auto submit link intake', (tester) async {
    int linkCalls = 0;
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(jsonEncode(inboxJson()), 200);
        }
        if (request.url.path == '/assistant/transcribe') {
          return http.Response.bytes(
            utf8.encode(jsonEncode({'text': 'https://example.org/article'})),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        if (request.url.path == '/intake/link') {
          linkCalls++;
          return http.Response('{}', 200);
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.runAsync(() async {
      await tester.tap(find.byKey(const Key('inbox_voice_button')));
      await Future<void>.delayed(const Duration(milliseconds: 200));
    });
    await pumpFrames(tester);
    await tester.runAsync(() async {
      await tester.tap(find.byKey(const Key('inbox_voice_button')));
      await Future<void>.delayed(const Duration(milliseconds: 300));
    });
    await pumpFrames(tester, frames: 10);

    expect(linkCalls, 0);
    final field = tester.widget<TextField>(find.byKey(const Key('inbox_link_input')));
    expect(field.controller!.text, 'https://example.org/article');
  });

  testWidgets('capture screen is task-only', (tester) async {
    final mock = MockClient((request) async => http.Response('{}', 404));
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    final capture = CaptureController(apiClient: apiClient, authController: auth);

    await tester.pumpWidget(
      MaterialApp(
        home: CaptureScreen(controller: capture, authController: auth),
      ),
    );

    expect(find.text('Создание задачи'), findsOneWidget);
    expect(find.text('Текст задачи'), findsOneWidget);
    expect(find.text('Создать задачу'), findsOneWidget);
    expect(find.text('Заметка'), findsNothing);
    expect(find.text('Добавить заметку'), findsNothing);
    expect(find.text('Добавить ссылку'), findsNothing);
  });
}
