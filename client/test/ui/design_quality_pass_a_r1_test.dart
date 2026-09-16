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
import 'package:personal_secretary/shell/app_shell.dart';
import 'package:personal_secretary/ui/object_presentation.dart';
import 'package:personal_secretary/ui/provider_icon.dart';
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

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  Future<void> pumpShell(
    WidgetTester tester, {
    required Size size,
  }) async {
    tester.view.physicalSize = size;
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
              directory: Directory.systemTemp.createTempSync('r1_shell'),
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
  }

  testWidgets('wide 1280x768 rail order: Add, LCD, Inbox, Account at bottom',
      (tester) async {
    await pumpShell(tester, size: const Size(1280, 768));

    final add = tester.getRect(find.byKey(const Key('shell_add_button')));
    final clock = tester.getRect(find.byKey(const Key('shell_clock')));
    final inbox = tester.getRect(find.text('Входящие').first);
    final account = tester.getRect(find.byKey(const Key('shell_account_button')));

    expect(add.bottom, lessThanOrEqualTo(clock.top + 1));
    expect(clock.bottom, lessThanOrEqualTo(inbox.top + 1));
    expect(account.top, greaterThan(inbox.bottom));
    expect(account.bottom, greaterThan(768 * 0.82));
    expect(find.byKey(const Key('shell_clock_display')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('compact mobile has no LCD clock', (tester) async {
    await pumpShell(tester, size: const Size(400, 800));
    expect(find.byKey(const Key('shell_clock')), findsNothing);
    expect(find.byType(NavigationBar), findsOneWidget);
  });

  testWidgets('shorter linux window does not overflow rail', (tester) async {
    await pumpShell(tester, size: const Size(1024, 600));
    expect(find.byType(NavigationRail), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('LCD clock shows display, time, date, weekday from injected now',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Center(
            child: ShellClock(
              key: const Key('shell_clock'),
              now: () => DateTime(2026, 9, 8, 14, 5),
            ),
          ),
        ),
      ),
    );
    expect(find.byKey(const Key('shell_clock_display')), findsOneWidget);
    expect(find.text('14:05'), findsOneWidget);
    expect(find.text('08.09.26'), findsOneWidget);
    expect(find.text('вторник'), findsOneWidget);
  });

  testWidgets('wide inbox mic is inside field and submit is icon-only outside',
      (tester) async {
    tester.view.physicalSize = const Size(1280, 768);
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
                'title': 'Письмо',
                'kind': 'email',
                'provider': 'gmail',
                'state': 'observed',
                'status': null,
                'origin': 'source',
                'primary_at': '2026-09-08T10:00:00Z',
                'excerpt': 'excerpt',
              },
            ],
            'source_sync_status': [],
          });
        }
        if (request.url.path == '/capture/note') {
          return http.Response.bytes(
            utf8.encode(jsonEncode({'note_id': 'n1'})),
            201,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        if (request.url.path.endsWith('/open-target')) {
          return jsonRes({
            'available': false,
            'action': 'unavailable',
            'label': 'Открыть в источнике',
            'reason': 'missing',
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

    final field = tester.getRect(find.byKey(const Key('inbox_link_input')));
    final mic = tester.getRect(find.byKey(const Key('inbox_voice_button')));
    final add = tester.getRect(find.byKey(const Key('inbox_link_add_button')));
    expect(field.contains(mic.center), isTrue);
    expect(add.left, greaterThan(field.right - 2));
    expect(find.byIcon(Icons.move_to_inbox_outlined), findsOneWidget);
    expect(find.byTooltip('Добавить во входящие'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Добавить'), findsNothing);

    await tester.enterText(find.byKey(const Key('inbox_link_input')), 'hello note');
    await tester.tap(find.byKey(const Key('inbox_link_add_button')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(tester.takeException(), isNull);
  });

  testWidgets('narrow inbox composer does not overflow', (tester) async {
    tester.view.physicalSize = const Size(360, 640);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/inbox') {
          return jsonRes({
            'unresolved_notifications': [],
            'recent_source_objects': [],
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
            onAskSecretary: (_) {},
            passiveRefreshInterval: const Duration(days: 1),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.byKey(const Key('inbox_voice_button')), findsOneWidget);
    expect(find.byIcon(Icons.move_to_inbox_outlined), findsOneWidget);
  });

  testWidgets('kind icon stays independent from branded source marks',
      (tester) async {
    var opened = false;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ObjectCompactHeaderRow(
            title: 'Тема',
            kind: 'email',
            provider: 'gmail',
            trailingText: '09:42',
            onProviderTap: () => opened = true,
          ),
        ),
      ),
    );
    expect(find.byIcon(Icons.email_outlined), findsOneWidget);
    expect(find.byKey(const Key('source_mark_google')), findsOneWidget);
    expect(find.byIcon(Icons.mail), findsNothing);
    expect(find.byIcon(Icons.calendar_month), findsNothing);

    await tester.tap(find.byKey(const Key('provider_open_gmail')));
    expect(opened, isTrue);
  });

  test('provider source mapping uses brand marks not kind duplicates', () {
    expect(providerSourceMark('gmail'), ProviderSourceMark.google);
    expect(providerSourceMark('google_calendar'), ProviderSourceMark.google);
    expect(providerSourceMark('google_drive'), ProviderSourceMark.google);
    expect(providerSourceMark('google'), ProviderSourceMark.google);
    expect(providerSourceMark('yandex_mail'), ProviderSourceMark.yandex);
    expect(providerSourceMark('yandex_calendar'), ProviderSourceMark.yandex);
    expect(providerSourceMark('yandex_disk'), ProviderSourceMark.yandex);
    expect(providerSourceMark('mattermost'), ProviderSourceMark.mattermost);
    expect(providerSourceMark('telegram'), ProviderSourceMark.telegram);
    expect(providerSourceMark('local_device'), ProviderSourceMark.computer);
    expect(providerSourceMark('cloud'), ProviderSourceMark.cloud);
    expect(providerSourceMark('web'), ProviderSourceMark.web);
    expect(providerSourceMark('unknown'), ProviderSourceMark.fallback);
    expect(providerVisual('gmail').icon, isNull);
    expect(providerVisual('yandex_mail').icon, isNull);
    expect(providerVisual('mattermost').icon, isNull);
    expect(providerVisual('local_device').icon, Icons.computer);
    expect(providerVisual('cloud').icon, Icons.cloud_outlined);
  });

  testWidgets('yandex mattermost local and cloud source artwork', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: Column(
            children: [
              ProviderSourceIcon(provider: 'yandex_mail'),
              ProviderSourceIcon(provider: 'mattermost'),
              ProviderSourceIcon(provider: 'local_device'),
              ProviderSourceIcon(provider: 'cloud'),
            ],
          ),
        ),
      ),
    );
    expect(find.byKey(const Key('source_mark_yandex')), findsOneWidget);
    expect(find.byKey(const Key('source_mark_mattermost')), findsOneWidget);
    expect(find.byKey(const Key('source_mark_computer')), findsOneWidget);
    expect(find.byKey(const Key('source_mark_cloud')), findsOneWidget);
    expect(find.byIcon(Icons.forum), findsNothing);
    expect(find.byIcon(Icons.alternate_email), findsNothing);
  });
}
