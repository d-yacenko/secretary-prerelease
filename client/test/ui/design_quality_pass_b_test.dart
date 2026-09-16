import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/assistant/assistant_controller.dart';
import 'package:personal_secretary/assistant/fake_voice_recorder.dart';
import 'package:personal_secretary/assistant/voice_temp_files.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/capture/capture_controller.dart';
import 'package:personal_secretary/graph/graph_workspace_controller.dart';
import 'package:personal_secretary/inbox/inbox_screen.dart';
import 'package:personal_secretary/navigation/app_route_observer.dart';
import 'package:personal_secretary/search/search_screen.dart';
import 'package:personal_secretary/shell/app_shell.dart';
import 'package:personal_secretary/today/today_screen.dart';
import 'package:personal_secretary/ui/object_label_strip.dart';
import 'package:personal_secretary/ui/shell_clock.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../shell/app_shell_test.dart';

http.Response jsonRes(Object body, [int status = 200]) {
  return http.Response.bytes(
    utf8.encode(jsonEncode(body)),
    status,
    headers: {'content-type': 'application/json; charset=utf-8'},
  );
}

Widget _catalogSearchApp({
  required List<String?> labelQueries,
  required List<Map<String, dynamic>> Function() nextCatalog,
}) {
  final apiClient = SecretaryApiClient(
    httpClient: MockClient((request) async {
      if (request.url.path == '/search/facets') {
        return jsonRes({'kinds': [], 'providers': []});
      }
      if (request.url.path == '/labels') {
        return jsonRes({'labels': nextCatalog()});
      }
      if (request.url.path == '/search') {
        labelQueries.add(request.url.queryParameters['label_id']);
        return jsonRes([
          {
            'id': 'email-1',
            'kind': 'email',
            'title': 'Письмо',
            'body': 'body',
            'provider': 'gmail',
            'external_id': null,
            'canonical_uri': null,
            'status': null,
            'start_at': null,
            'due_at': null,
            'metadata': {},
            'origin': 'source',
            'state': 'observed',
            'confidence': null,
            'created_at': '2026-08-30T08:00:00Z',
            'updated_at': '2026-08-30T08:00:00Z',
          },
        ]);
      }
      if (request.url.path == '/labels/by-objects') {
        return jsonRes({'objects': {}});
      }
      return jsonRes({}, 404);
    }),
  );
  apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
  final auth = AuthController(
    apiClient: apiClient,
    tokenStore: FakeTokenStore(),
    serverUrlStore: FakeServerUrlStore(),
  );
  auth.status = AuthStatus.authenticated;
  return MaterialApp(
    navigatorObservers: [appRouteObserver],
    home: Scaffold(
      body: SearchScreen(
        apiClient: apiClient,
        authController: auth,
        captureController:
            CaptureController(apiClient: apiClient, authController: auth),
      ),
    ),
  );
}

Future<void> _returnFromOverlay(WidgetTester tester) async {
  final navigator = tester.state<NavigatorState>(find.byType(Navigator));
  navigator.push(
    MaterialPageRoute<void>(
      builder: (_) => const Scaffold(body: Text('overlay')),
    ),
  );
  await tester.pumpAndSettle();
  navigator.pop();
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('inbox loads labels in one batch and keeps source tap',
      (tester) async {
    tester.view.physicalSize = const Size(1280, 768);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var batchCalls = 0;
    var perObjectCalls = 0;
    String? openTargetId;
    String? openedObject;
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox') {
          return jsonRes({
            'unresolved_notifications': [],
            'recent_source_objects': [
              {
                'id': 'email-1',
                'title': 'Письмо с метками',
                'kind': 'email',
                'provider': 'gmail',
                'state': 'observed',
                'status': null,
                'origin': 'source',
                'primary_at': '2026-09-08T10:00:00Z',
                'excerpt': 'excerpt',
              },
              {
                'id': 'email-2',
                'title': 'Без меток',
                'kind': 'email',
                'provider': 'gmail',
                'state': 'observed',
                'status': null,
                'origin': 'source',
                'primary_at': '2026-09-08T11:00:00Z',
                'excerpt': 'excerpt',
              },
            ],
            'source_sync_status': [],
          });
        }
        if (request.url.path == '/labels/by-objects') {
          batchCalls++;
          return jsonRes({
            'objects': {
              'email-1': [
                {'id': 'l1', 'title': 'Work'},
                {'id': 'l2', 'title': 'Home'},
                {'id': 'l3', 'title': 'Extra'},
              ],
            },
          });
        }
        if (request.url.path.endsWith('/labels') &&
            request.url.path.contains('/objects/')) {
          perObjectCalls++;
          return jsonRes({'labels': []});
        }
        if (request.url.path.endsWith('/open-target')) {
          openTargetId = request.url.path.split('/')[2];
          return jsonRes({
            'available': false,
            'action': 'unavailable',
            'label': 'Открыть в источнике',
            'reason': 'missing',
          });
        }
        if (request.url.path.startsWith('/objects/')) {
          openedObject = request.url.path;
          return jsonRes({
            'id': request.url.path.split('/')[2],
            'kind': 'email',
            'title': 'Письмо с метками',
            'body': 'See https://example.com',
            'provider': 'gmail',
            'external_id': 'ext-1',
            'canonical_uri': 'https://mail.example/message/1',
            'status': null,
            'start_at': null,
            'due_at': null,
            'metadata': {},
            'origin': 'source',
            'state': 'observed',
            'confidence': null,
            'created_at': '2026-08-28T08:00:00Z',
            'updated_at': '2026-08-28T08:00:00Z',
          });
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: InboxScreen(
            apiClient: apiClient,
            authController: auth,
            captureController:
                CaptureController(apiClient: apiClient, authController: auth),
            onAskSecretary: (_) {},
            passiveRefreshInterval: const Duration(days: 1),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(batchCalls, 1);
    expect(perObjectCalls, 0);
    expect(find.text('Work'), findsOneWidget);
    expect(find.text('Home'), findsOneWidget);
    expect(find.text('+1'), findsOneWidget);
    expect(find.text('Extra'), findsNothing);
    expect(find.text('Без меток'), findsOneWidget);

    await tester.tap(find.byKey(const Key('provider_open_gmail')).first);
    await tester.pump();
    expect(openTargetId, isNotNull);
    expect(openedObject, isNull);
  });

  testWidgets('today loads one combined batch and keeps current/soon',
      (tester) async {
    var batchCalls = 0;
    String? batchBody;
    final now = DateTime.parse('2026-09-08T10:00:00+03:00');
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/today') {
          return jsonRes({
            'date': '2026-09-08',
            'timezone': 'Europe/Moscow',
            'day_start': '2026-09-08T00:00:00+03:00',
            'tasks': [
              {
                'id': 'task-1',
                'kind': 'task',
                'title': 'Задача',
                'body': null,
                'provider': null,
                'external_id': null,
                'canonical_uri': null,
                'status': 'pending',
                'start_at': null,
                'due_at': '2026-09-08T18:00:00+03:00',
                'metadata': {},
                'origin': 'user',
                'state': 'confirmed',
                'confidence': null,
                'created_at': '2026-09-08T08:00:00Z',
                'updated_at': '2026-09-08T08:00:00Z',
              },
            ],
            'calendar_events': [
              {
                'id': 'current',
                'kind': 'event',
                'title': 'Сейчас',
                'body': null,
                'provider': 'google_calendar',
                'external_id': null,
                'canonical_uri': null,
                'status': null,
                'start_at': '2026-09-08T09:30:00+03:00',
                'due_at': '2026-09-08T10:30:00+03:00',
                'metadata': {},
                'origin': 'source',
                'state': 'observed',
                'confidence': null,
                'created_at': '2026-09-08T08:00:00Z',
                'updated_at': '2026-09-08T08:00:00Z',
              },
              {
                'id': 'soon',
                'kind': 'event',
                'title': 'Скоро',
                'body': null,
                'provider': 'yandex_calendar',
                'external_id': null,
                'canonical_uri': null,
                'status': null,
                'start_at': '2026-09-08T10:20:00+03:00',
                'due_at': '2026-09-08T11:00:00+03:00',
                'metadata': {},
                'origin': 'source',
                'state': 'observed',
                'confidence': null,
                'created_at': '2026-09-08T08:00:00Z',
                'updated_at': '2026-09-08T08:00:00Z',
              },
            ],
            'notifications': [],
          });
        }
        if (request.url.path == '/labels/by-objects') {
          batchCalls++;
          batchBody = request.body;
          return jsonRes({
            'objects': {
              'task-1': [
                {'id': 'l1', 'title': 'Work'},
              ],
              'current': [
                {'id': 'l2', 'title': 'Focus'},
              ],
            },
          });
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TodayScreen(
            apiClient: apiClient,
            authController: auth,
            captureController:
                CaptureController(apiClient: apiClient, authController: auth),
            now: () => now,
            clockTick: const Duration(days: 1),
            passiveRefreshInterval: const Duration(days: 1),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(batchCalls, 1);
    final decoded = jsonDecode(batchBody!) as Map<String, dynamic>;
    final ids = (decoded['object_ids'] as List<dynamic>).cast<String>();
    expect(ids.toSet(), {'task-1', 'current', 'soon'});
    expect(find.text('Work'), findsOneWidget);
    expect(find.text('Focus'), findsOneWidget);
    expect(find.byKey(const Key('today_event_current_current')), findsOneWidget);
    expect(find.byKey(const Key('today_event_soon_soon')), findsOneWidget);
  });

  testWidgets('search renders labels without N+1 and keeps filter',
      (tester) async {
    var batchCalls = 0;
    final labelQueries = <String?>[];
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/search/facets') {
          return jsonRes({
            'kinds': [
              {'value': 'email', 'count': 1},
            ],
            'providers': [
              {'value': 'gmail', 'count': 1},
            ],
          });
        }
        if (request.url.path == '/labels') {
          return jsonRes({
            'labels': [
              {'id': 'label-1', 'title': 'Work', 'object_count': 1},
            ],
          });
        }
        if (request.url.path == '/search') {
          labelQueries.add(request.url.queryParameters['label_id']);
          return jsonRes([
            {
              'id': 'email-1',
              'kind': 'email',
              'title': 'Письмо от преподавателя',
              'body': 'body',
              'provider': 'gmail',
              'external_id': null,
              'canonical_uri': null,
              'status': null,
              'start_at': null,
              'due_at': null,
              'metadata': {},
              'origin': 'source',
              'state': 'observed',
              'confidence': null,
              'created_at': '2026-08-30T08:00:00Z',
              'updated_at': '2026-08-30T08:00:00Z',
            },
          ]);
        }
        if (request.url.path == '/labels/by-objects') {
          batchCalls++;
          return jsonRes({
            'objects': {
              'email-1': [
                {'id': 'label-1', 'title': 'Work'},
              ],
            },
          });
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
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
            captureController:
                CaptureController(apiClient: apiClient, authController: auth),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, 'письмо');
    await tester.tap(find.widgetWithText(FilledButton, 'Поиск'));
    await tester.pumpAndSettle();
    expect(batchCalls, 1);
    expect(find.text('Work'), findsWidgets);
    expect(find.byType(ObjectLabelStrip), findsOneWidget);
    await tester.tap(find.byKey(const Key('search_label_filter')));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(MenuItemButton, 'Work'));
    await tester.pumpAndSettle();
    expect(labelQueries.last, 'label-1');
    expect(batchCalls, 2);
  });

  testWidgets('search catalog refreshes after returning from overlay route',
      (tester) async {
    var labelsVersion = 0;
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/search/facets') {
          return jsonRes({'kinds': [], 'providers': []});
        }
        if (request.url.path == '/labels') {
          labelsVersion++;
          if (labelsVersion == 1) {
            return jsonRes({
              'labels': [
                {'id': 'label-1', 'title': 'OldName', 'object_count': 1},
              ],
            });
          }
          return jsonRes({
            'labels': [
              {'id': 'label-1', 'title': 'NewName', 'object_count': 1},
            ],
          });
        }
        return jsonRes({}, 404);
      }),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    await tester.pumpWidget(
      MaterialApp(
        navigatorObservers: [appRouteObserver],
        home: Scaffold(
          body: SearchScreen(
            apiClient: apiClient,
            authController: auth,
            captureController:
                CaptureController(apiClient: apiClient, authController: auth),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('search_label_filter')), findsOneWidget);
    final navigator = tester.state<NavigatorState>(find.byType(Navigator));
    navigator.push(
      MaterialPageRoute<void>(
        builder: (_) => const Scaffold(body: Text('overlay')),
      ),
    );
    await tester.pumpAndSettle();
    navigator.pop();
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('search_label_filter')));
    await tester.pumpAndSettle();
    expect(find.text('NewName'), findsWidgets);
    expect(find.text('OldName'), findsNothing);
  });

  testWidgets('search keeps selected label ID after rename in catalog',
      (tester) async {
    final labelQueries = <String?>[];
    var labelsVersion = 0;
    await tester.pumpWidget(
      _catalogSearchApp(
        labelQueries: labelQueries,
        nextCatalog: () {
          labelsVersion++;
          if (labelsVersion == 1) {
            return [
              {'id': 'label-1', 'title': 'OldName', 'object_count': 1},
              {'id': 'label-2', 'title': 'Other', 'object_count': 1},
            ];
          }
          return [
            {'id': 'label-1', 'title': 'NewName', 'object_count': 1},
            {'id': 'label-2', 'title': 'Other', 'object_count': 1},
          ];
        },
      ),
    );
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, 'письмо');
    await tester.tap(find.widgetWithText(FilledButton, 'Поиск'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('search_label_filter')));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(MenuItemButton, 'OldName'));
    await tester.pumpAndSettle();
    expect(labelQueries.last, 'label-1');

    await _returnFromOverlay(tester);
    expect(find.byTooltip('Метка: NewName'), findsOneWidget);
    await tester.tap(find.widgetWithText(FilledButton, 'Поиск'));
    await tester.pumpAndSettle();
    expect(labelQueries.last, 'label-1');
    await tester.tap(find.byKey(const Key('search_label_filter')));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(MenuItemButton, 'NewName'), findsOneWidget);
    expect(find.widgetWithText(MenuItemButton, 'OldName'), findsNothing);
  });

  testWidgets('search clears deleted selected label and reruns as Все',
      (tester) async {
    final labelQueries = <String?>[];
    var labelsVersion = 0;
    await tester.pumpWidget(
      _catalogSearchApp(
        labelQueries: labelQueries,
        nextCatalog: () {
          labelsVersion++;
          if (labelsVersion == 1) {
            return [
              {'id': 'label-1', 'title': 'Work', 'object_count': 1},
              {'id': 'label-2', 'title': 'Home', 'object_count': 1},
            ];
          }
          return [
            {'id': 'label-2', 'title': 'Home', 'object_count': 1},
          ];
        },
      ),
    );
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, 'письмо');
    await tester.tap(find.widgetWithText(FilledButton, 'Поиск'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('search_label_filter')));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(MenuItemButton, 'Work'));
    await tester.pumpAndSettle();
    expect(labelQueries.last, 'label-1');
    final searchesBeforeReturn = labelQueries.length;

    await _returnFromOverlay(tester);
    expect(labelQueries.length, searchesBeforeReturn + 1);
    expect(labelQueries.last, isNull);
    expect(find.byTooltip('Метка: Все'), findsOneWidget);
    final filter = tester.widget<IconButton>(
      find.byKey(const Key('search_label_filter')),
    );
    expect(filter.style?.backgroundColor?.resolve(const <WidgetState>{}), isNull);

    await tester.tap(find.byKey(const Key('search_label_filter')));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(MenuItemButton, 'Work'), findsNothing);
    expect(find.widgetWithText(MenuItemButton, 'Home'), findsOneWidget);
    await tester.tap(find.byKey(const Key('search_label_filter')));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Поиск'));
    await tester.pumpAndSettle();
    expect(labelQueries.last, isNull);
  });

  testWidgets('search keeps selection when a non-selected label is deleted',
      (tester) async {
    final labelQueries = <String?>[];
    var labelsVersion = 0;
    await tester.pumpWidget(
      _catalogSearchApp(
        labelQueries: labelQueries,
        nextCatalog: () {
          labelsVersion++;
          if (labelsVersion == 1) {
            return [
              {'id': 'label-1', 'title': 'Work', 'object_count': 1},
              {'id': 'label-2', 'title': 'Home', 'object_count': 1},
            ];
          }
          return [
            {'id': 'label-1', 'title': 'Work', 'object_count': 1},
          ];
        },
      ),
    );
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, 'письмо');
    await tester.tap(find.widgetWithText(FilledButton, 'Поиск'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('search_label_filter')));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(MenuItemButton, 'Work'));
    await tester.pumpAndSettle();
    expect(labelQueries.last, 'label-1');
    final searchesBeforeReturn = labelQueries.length;

    await _returnFromOverlay(tester);
    expect(labelQueries.length, searchesBeforeReturn);
    expect(find.byTooltip('Метка: Work'), findsOneWidget);
    await tester.tap(find.widgetWithText(FilledButton, 'Поиск'));
    await tester.pumpAndSettle();
    expect(labelQueries.last, 'label-1');
    await tester.tap(find.byKey(const Key('search_label_filter')));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(MenuItemButton, 'Work'), findsOneWidget);
    expect(find.widgetWithText(MenuItemButton, 'Home'), findsNothing);
  });

  testWidgets('LCD hierarchy uses numeric date and heavier time',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ShellClock(
            now: () => DateTime(2026, 9, 8, 14, 5),
          ),
        ),
      ),
    );
    final time = tester.widget<Text>(find.text('14:05'));
    expect(time.style?.fontSize, 27);
    expect(time.style?.fontWeight, FontWeight.w800);
    expect(find.text('08.09.26'), findsOneWidget);
    expect(find.text('вторник'), findsOneWidget);

    tester.view.physicalSize = const Size(400, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final auth = buildAuth();
    await tester.pumpWidget(
      MaterialApp(
        home: AppShell(
          authController: auth,
          captureController: CaptureController(
            apiClient: auth.apiClient,
            authController: auth,
          ),
          assistantController: AssistantController(
            apiClient: auth.apiClient,
            authController: auth,
            voiceRecorder: FakeVoiceRecorder(),
            voiceTempFiles: VoiceTempFiles(
              directory: Directory.systemTemp.createTempSync('passb_clock'),
            ),
          ),
          graphController: GraphWorkspaceController(
            apiClient: auth.apiClient,
            authController: auth,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('shell_clock')), findsNothing);
  });
}
