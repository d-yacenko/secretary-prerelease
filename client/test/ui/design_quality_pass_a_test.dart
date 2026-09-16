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
import 'package:personal_secretary/objects/object_detail_screen.dart';
import 'package:personal_secretary/shell/app_shell.dart';
import 'package:personal_secretary/today/today_screen.dart';
import 'package:personal_secretary/ui/object_actions.dart';
import 'package:personal_secretary/ui/ui_text_scale.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../shell/app_shell_test.dart';

http.Response jsonRes(Object body, [int status = 200]) {
  return http.Response.bytes(
    utf8.encode(jsonEncode(body)),
    status,
    headers: {'content-type': 'application/json; charset=utf-8'},
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  Map<String, dynamic> objectJson({
    String id = 'email-1',
    String body = 'See https://example.com/docs for details.',
    Map<String, dynamic>? metadata,
  }) {
    return {
      'id': id,
      'kind': 'email',
      'title': 'Inbound email',
      'body': body,
      'provider': 'gmail',
      'external_id': 'ext-1',
      'canonical_uri': 'https://mail.example/message/1',
      'status': null,
      'start_at': null,
      'due_at': null,
      'metadata': metadata ??
          {
            'raw': 'should-not-render',
          },
      'origin': 'source',
      'state': 'observed',
      'confidence': null,
      'created_at': '2026-08-28T08:00:00Z',
      'updated_at': '2026-08-28T08:00:00Z',
    };
  }

  testWidgets('inbox wide compact cards and refresh remain', (tester) async {
    tester.view.physicalSize = const Size(1280, 768);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final sources = List.generate(8, (index) {
      return {
        'id': 'email-$index',
        'title': 'Письмо $index короткое',
        'kind': 'email',
        'provider': 'gmail',
        'state': 'observed',
        'status': null,
        'origin': 'source',
        'primary_at': '2026-09-08T10:0$index:00Z',
        'excerpt': 'Краткий текст $index',
      };
    });

    String? openedObject;
    String? openTargetId;
    String? graphId;
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox') {
          return jsonRes({
            'unresolved_notifications': [],
            'recent_source_objects': sources,
            'source_sync_status': [],
          });
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
        if (request.url.path.endsWith('/neighbors')) {
          return jsonRes({'object_id': 'email-0', 'neighbors': []});
        }
        if (request.url.path.endsWith('/context')) {
          return jsonRes({
            'object': objectJson(),
            'edges': [],
            'neighbors': [],
          });
        }
        if (request.url.path.endsWith('/labels')) {
          return jsonRes({'labels': []});
        }
        if (request.url.path.startsWith('/objects/')) {
          openedObject = request.url.path;
          return jsonRes(objectJson(id: request.url.path.split('/')[2]));
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
    final capture = CaptureController(apiClient: apiClient, authController: auth);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: InboxScreen(
            apiClient: apiClient,
            authController: auth,
            captureController: capture,
            onShowInGraph: (id) => graphId = id,
            onAskSecretary: (_) {},
            passiveRefreshInterval: const Duration(days: 1),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byTooltip('Обновить'), findsOneWidget);
    expect(
      find.text('Открыть в графе', skipOffstage: false),
      findsAtLeastNWidgets(6),
    );
    expect(find.text('Показать в графе'), findsNothing);
    expect(tester.takeException(), isNull);
    expect(find.text('Письмо 0 короткое'), findsOneWidget);
    expect(
      find.text('Письмо 5 короткое', skipOffstage: false),
      findsOneWidget,
    );

    final firstTitle = tester.getRect(find.text('Письмо 0 короткое'));
    final sixthTitle = tester.getRect(
      find.text('Письмо 5 короткое', skipOffstage: false),
    );
    expect(firstTitle.top, lessThan(768));
    expect(sixthTitle.top, greaterThan(firstTitle.top));

    await tester.tap(find.byKey(const Key('provider_open_gmail')).first);
    await tester.pump();
    expect(openTargetId, isNotNull);
    expect(openedObject, isNull);

    await tester.tap(find.byType(OpenInGraphAction).first);
    expect(graphId, isNotNull);

    await tester.tap(find.text('Письмо 0 короткое'));
    await tester.pump();
    expect(openedObject, isNotNull);
  });

  testWidgets('inbox narrow does not overflow', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox') {
          return jsonRes({
            'unresolved_notifications': [],
            'recent_source_objects': [
              {
                'id': 'email-1',
                'title':
                    'Очень длинное русское название входящего письма для проверки переноса',
                'kind': 'email',
                'provider': 'yandex_mail',
                'state': 'observed',
                'status': null,
                'origin': 'source',
                'primary_at': '2026-09-05T12:00:00Z',
                'excerpt': 'excerpt',
              },
            ],
            'source_sync_status': [],
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
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });

  testWidgets('object detail hides raw metadata and Текст heading', (tester) async {
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/objects/email-1') {
          return jsonRes(objectJson());
        }
        if (request.url.path.endsWith('/neighbors')) {
          return jsonRes({'object_id': 'email-1', 'neighbors': []});
        }
        if (request.url.path.endsWith('/context')) {
          return jsonRes({
            'object': objectJson(),
            'edges': [],
            'neighbors': [],
          });
        }
        if (request.url.path.endsWith('/labels')) {
          return jsonRes({'labels': []});
        }
        if (request.url.path.endsWith('/open-target')) {
          return jsonRes({
            'available': false,
            'action': 'unavailable',
            'label': 'Открыть в источнике',
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
        home: ObjectDetailScreen(
          objectId: 'email-1',
          apiClient: apiClient,
          authController: auth,
          captureController:
              CaptureController(apiClient: apiClient, authController: auth),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Метаданные'), findsNothing);
    expect(find.text('Текст'), findsNothing);
    expect(find.textContaining('should-not-render'), findsNothing);
    expect(find.textContaining('https://example.com/docs'), findsOneWidget);
    expect(find.text('Подробности'), findsOneWidget);
  });

  testWidgets('today current/soon keys and clock wide vs compact', (tester) async {
    tester.view.physicalSize = const Size(1280, 768);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    Map<String, dynamic> event(String id, String start, String? due) => {
          'id': id,
          'kind': 'event',
          'title': id,
          'body': null,
          'provider': 'google_calendar',
          'external_id': null,
          'canonical_uri': null,
          'status': null,
          'start_at': start,
          'due_at': due,
          'metadata': {},
          'origin': 'source',
          'state': 'observed',
          'confidence': null,
          'created_at': '2026-09-08T08:00:00Z',
          'updated_at': '2026-09-08T08:00:00Z',
        };

    final now = DateTime.parse('2026-09-08T12:00:00+03:00');
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/today') {
          return jsonRes({
            'date': '2026-09-08',
            'timezone': 'Europe/Amsterdam',
            'day_start': '2026-09-08T00:00:00+03:00',
            'tasks': [],
            'calendar_events': [
              event('current', '2026-09-08T11:30:00+03:00', '2026-09-08T12:30:00+03:00'),
              event('soon', '2026-09-08T12:40:00+03:00', null),
              event('later', '2026-09-08T15:00:00+03:00', null),
            ],
            'notifications': [],
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
    expect(find.byKey(const Key('today_event_current_current')), findsOneWidget);
    expect(find.byKey(const Key('today_event_soon_soon')), findsOneWidget);
    expect(find.byKey(const Key('today_event_none_later')), findsOneWidget);

    final auth2 = buildAuth();
    await tester.pumpWidget(
      MaterialApp(
        home: AppShell(
          authController: auth2,
          captureController: CaptureController(
            apiClient: auth2.apiClient,
            authController: auth2,
          ),
          assistantController: AssistantController(
            apiClient: auth2.apiClient,
            authController: auth2,
            voiceRecorder: FakeVoiceRecorder(),
            voiceTempFiles: VoiceTempFiles(
              directory: Directory.systemTemp.createTempSync('clock'),
            ),
          ),
          graphController: GraphWorkspaceController(
            apiClient: auth2.apiClient,
            authController: auth2,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('shell_clock')), findsOneWidget);

    tester.view.physicalSize = const Size(400, 800);
    await tester.pumpWidget(
      MaterialApp(
        home: AppShell(
          authController: auth2,
          captureController: CaptureController(
            apiClient: auth2.apiClient,
            authController: auth2,
          ),
          assistantController: AssistantController(
            apiClient: auth2.apiClient,
            authController: auth2,
            voiceRecorder: FakeVoiceRecorder(),
            voiceTempFiles: VoiceTempFiles(
              directory: Directory.systemTemp.createTempSync('clock2'),
            ),
          ),
          graphController: GraphWorkspaceController(
            apiClient: auth2.apiClient,
            authController: auth2,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('shell_clock')), findsNothing);
  });

  test('text scale 0.50 persists and 0.90 remains 0.90', () async {
    SharedPreferences.setMockInitialValues({kUiTextScalePrefsKey: 0.90});
    final loaded = UiTextScaleController();
    await loaded.load();
    expect(loaded.factor, 0.90);
    await loaded.setFactor(0.50);
    expect(loaded.factor, 0.50);
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getDouble(kUiTextScalePrefsKey), 0.50);
    final reloaded = UiTextScaleController();
    await reloaded.load();
    expect(reloaded.factor, 0.50);
  });

  testWidgets('text scale persists clamp and reset', (tester) async {
    SharedPreferences.setMockInitialValues({kUiTextScalePrefsKey: 9.9});
    final controller = UiTextScaleController();
    await controller.load();
    expect(controller.factor, kUiTextScaleMax);
    await controller.setFactor(1.15);
    expect(controller.percent, 115);
    await controller.reset();
    expect(controller.factor, kUiTextScaleDefault);
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getDouble(kUiTextScalePrefsKey), kUiTextScaleDefault);
  });
}
