import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/assistant/assistant_controller.dart';
import 'package:personal_secretary/assistant/fake_speech_player.dart';
import 'package:personal_secretary/assistant/fake_voice_recorder.dart';
import 'package:personal_secretary/assistant/hardware_voice_controller.dart';
import 'package:personal_secretary/assistant/hardware_voice_store.dart';
import 'package:personal_secretary/assistant/voice_temp_files.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/capture/capture_controller.dart';
import 'package:personal_secretary/graph/graph_workspace_controller.dart';
import 'package:personal_secretary/shell/app_shell.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../assistant/fake_hardware_voice_bridge.dart';

MockClient shellMockClient() {
  return MockClient((request) async {
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
    if (request.url.path == '/notifications') {
      return http.Response(jsonEncode({'notifications': []}), 200);
    }
    if (request.url.path == '/today' || request.url.path == '/week') {
      return http.Response(
        jsonEncode({
          'date': '2026-08-28',
          'timezone': 'Europe/Amsterdam',
          'day_start': '2026-08-28T00:00:00+02:00',
          'tasks': [],
          'calendar_events': [],
          'notifications': [],
          'events': [],
          'scheduled_work': [],
          'temporal_hints': [],
        }),
        200,
      );
    }
    if (request.url.path == '/graph/workspace') {
      return http.Response(
        jsonEncode({
          'root_id': null,
          'seed_ids': [],
          'nodes': [],
          'edges': [],
          'truncated': false,
        }),
        200,
      );
    }
    if (request.url.path == '/search') {
      return http.Response(jsonEncode([]), 200);
    }
    if (request.url.path == '/labels' ||
        request.url.path == '/labels/by-objects') {
      return http.Response(jsonEncode({'labels': [], 'by_object_id': {}}), 200);
    }
    if (request.url.path == '/assistant/transcribe') {
      return http.Response(jsonEncode({'text': 'привет'}), 200);
    }
    if (request.url.path == '/assistant/message') {
      return http.Response(
        jsonEncode({'answer': 'ок', 'references': [], 'affected_objects': []}),
        200,
      );
    }
    if (request.url.path == '/assistant/speech') {
      return http.Response.bytes(
        [1, 2, 3, 4],
        200,
        headers: {'content-type': 'audio/mpeg'},
      );
    }
    return http.Response('{}', 404);
  });
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  Future<void> pumpShell(
    WidgetTester tester, {
    required AuthController auth,
    required AssistantController assistant,
    required HardwareVoiceController hardware,
    required FakeVoiceRecorder recorder,
  }) async {
    tester.view.physicalSize = const Size(400, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        home: AppShell(
          authController: auth,
          captureController: CaptureController(
            apiClient: auth.apiClient,
            authController: auth,
          ),
          assistantController: assistant,
          graphController: GraphWorkspaceController(
            apiClient: auth.apiClient,
            authController: auth,
          ),
          hardwareVoiceController: hardware,
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  Future<
    (
      AuthController,
      AssistantController,
      HardwareVoiceController,
      FakeVoiceRecorder,
    )
  >
  buildControllers() async {
    final apiClient = SecretaryApiClient(httpClient: shellMockClient());
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    auth.user = UserMe(
      id: 'u1',
      displayName: 'Alice',
      createdAt: '2026-01-01T00:00:00Z',
    );
    final recorder = FakeVoiceRecorder();
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: recorder,
      speechPlayer: FakeSpeechPlayer(),
      voiceTempFiles: VoiceTempFiles(
        directory: Directory.systemTemp.createTempSync('hw_shell_voice'),
      ),
    );
    final hardware = HardwareVoiceController(
      authController: auth,
      store: HardwareVoiceStore(
        preferences: await SharedPreferences.getInstance(),
      ),
      bridge: FakeHardwareVoiceBridge(),
    );
    await hardware.attach();
    await hardware.saveLearned(keyCode: 1082);
    return (auth, assistant, hardware, recorder);
  }

  testWidgets(
    'hardware trigger from Inbox/Today/Search/Graph selects Assistant',
    (tester) async {
      final (auth, assistant, hardware, recorder) = await buildControllers();
      await pumpShell(
        tester,
        auth: auth,
        assistant: assistant,
        hardware: hardware,
        recorder: recorder,
      );

      for (final label in ['Входящие', 'Сегодня', 'Поиск', 'Граф']) {
        await tester.tap(find.text(label).first);
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 100));
        hardware.debugEmitVoiceTrigger();
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 50));
        expect(find.widgetWithText(AppBar, 'Секретарь'), findsOneWidget);
        expect(find.text('Спросить секретаря…'), findsOneWidget);
        expect(recorder.startCallCount, greaterThan(0));
        assistant.resetSession();
        await tester.pump();
      }
      await tester.pump(const Duration(milliseconds: 600));
      assistant.dispose();
      hardware.dispose();
    },
  );

  testWidgets('hardware trigger ignores pushed Account instead of popping', (
    tester,
  ) async {
    final (auth, assistant, hardware, recorder) = await buildControllers();
    await pumpShell(
      tester,
      auth: auth,
      assistant: assistant,
      hardware: hardware,
      recorder: recorder,
    );
    await tester.tap(find.byKey(const Key('shell_account_button')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    hardware.debugEmitVoiceTrigger();
    await tester.pump();
    expect(recorder.startCallCount, 0);
    expect(find.text('Аккаунт'), findsOneWidget);
    assistant.dispose();
    hardware.dispose();
  });
}
