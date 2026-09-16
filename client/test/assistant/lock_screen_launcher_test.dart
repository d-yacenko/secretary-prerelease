import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/assistant/assistant_controller.dart';
import 'package:personal_secretary/assistant/fake_speech_player.dart';
import 'package:personal_secretary/assistant/fake_voice_recorder.dart';
import 'package:personal_secretary/assistant/system_assistant_bridge.dart';
import 'package:personal_secretary/assistant/voice_invocation_source.dart';
import 'package:personal_secretary/assistant/voice_session_app.dart';
import 'package:personal_secretary/assistant/voice_session_screen.dart';
import 'package:personal_secretary/assistant/voice_temp_files.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/auth_setup_screen.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _LauncherBridge implements SystemAssistantBridge {
  _LauncherBridge({this.keyguardLocked = true});

  bool keyguardLocked;
  VoidCallback? onAssist;
  int dismissCount = 0;

  @override
  void setOnAssist(VoidCallback? callback) {
    onAssist = callback;
  }

  @override
  void setOnKeyguard(void Function(bool locked)? callback) {}

  @override
  void setOnRoleResult(void Function(SystemAssistantStatus status)? callback) {}

  @override
  Future<SystemAssistantStatus> getStatus() async {
    return SystemAssistantStatus(
      available: true,
      isDefaultAssistant: false,
      roleManagerAvailable: true,
      keyguardLocked: keyguardLocked,
      protocol: systemAssistantProtocol,
    );
  }

  @override
  Future<void> requestAssistantRole() async {}

  @override
  Future<void> openLockScreenLauncher() async {}

  @override
  Future<void> dismiss() async {
    dismissCount += 1;
  }

  @override
  Future<void> clearDrivingSession() async {}
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory tempDir;

  setUp(() {
    SharedPreferences.setMockInitialValues({
      LockScreenVoiceStore.prefKeyForUser('user-1'): true,
    });
    tempDir = Directory.systemTemp.createTempSync('secretary_lock_launcher');
  });

  tearDown(() {
    if (tempDir.existsSync()) {
      tempDir.deleteSync(recursive: true);
    }
  });

  http.Response jsonResponse(Object body) {
    return http.Response.bytes(
      utf8.encode(jsonEncode(body)),
      200,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );
  }

  http.Response speechOk() {
    return http.Response.bytes(
      [1, 2, 3, 4],
      200,
      headers: {'content-type': 'audio/mpeg'},
    );
  }

  SecretaryApiClient voiceClient() {
    return SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.url.path == '/me') {
          return jsonResponse({
            'id': 'user-1',
            'display_name': 'Alice',
            'created_at': '2026-01-01T00:00:00Z',
          });
        }
        if (request.url.path == '/assistant/transcribe') {
          return jsonResponse({'text': 'который час'});
        }
        if (request.url.path == '/assistant/message') {
          return jsonResponse({
            'answer': 'полдень',
            'references': [],
            'affected_objects': [],
          });
        }
        if (request.url.path == '/assistant/speech') {
          return speechOk();
        }
        return http.Response('{}', 404);
      }),
    )..configure(baseUrl: 'https://secretary.example', token: 't');
  }

  Future<void> pumpUntil(
    WidgetTester tester,
    bool Function() condition, {
    Object? debugValue,
  }) async {
    for (var i = 0; i < 250; i++) {
      if (condition()) {
        return;
      }
      await tester.pump(const Duration(milliseconds: 20));
    }
    fail('timed out waiting for condition: $debugValue');
  }

  Future<void> waitUntil(bool Function() condition) async {
    final end = DateTime.now().add(const Duration(seconds: 3));
    while (!condition()) {
      if (DateTime.now().isAfter(end)) {
        fail('timed out waiting for condition');
      }
      await Future<void>.delayed(const Duration(milliseconds: 5));
    }
  }

  Future<SystemAssistantController> enabledAssistant(
    SystemAssistantBridge bridge,
  ) async {
    final controller = SystemAssistantController(
      bridge: bridge,
      store: LockScreenVoiceStore(
        preferences: await SharedPreferences.getInstance(),
      ),
    );
    await controller.attach('user-1');
    return controller;
  }

  testWidgets('launcher mode stays idle until the large button is tapped', (
    tester,
  ) async {
    final recorder = FakeVoiceRecorder();
    final apiClient = voiceClient();
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final bridge = _LauncherBridge();
    final systemAssistant = await enabledAssistant(bridge);
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: recorder,
      voiceTempFiles: VoiceTempFiles(directory: tempDir),
      speechPlayer: FakeSpeechPlayer(),
      lockScreenSession: true,
    );
    assistant.lockScreenVoiceEnabled = true;
    await tester.pumpWidget(
      MaterialApp(
        home: VoiceSessionScreen(
          assistant: assistant,
          systemAssistant: systemAssistant,
        ),
      ),
    );
    await tester.pump();
    expect(recorder.startCallCount, 0);
    expect(find.text('Нажмите, чтобы говорить'), findsWidgets);
    expect(find.byType(ListView), findsNothing);
    await tester.tap(find.byKey(const Key('voice_session_launcher_button')));
    await pumpUntil(
      tester,
      () => assistant.voiceState == AssistantVoiceState.recording,
    );
    expect(recorder.startCallCount, 1);
    expect(assistant.turnSource, VoiceInvocationSource.lockScreenLauncher);
    await tester.tap(find.byKey(const Key('voice_session_launcher_button')));
    await pumpUntil(tester, () => recorder.stopCallCount == 1);
    expect(assistant.turnSource, VoiceInvocationSource.lockScreenLauncher);
    assistant.dispose();
    systemAssistant.dispose();
  });

  testWidgets('duplicate tap during starting does not start a second recording', (
    tester,
  ) async {
    final recorder = FakeVoiceRecorder()
      ..startDelay = const Duration(milliseconds: 80);
    final apiClient = voiceClient();
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final bridge = _LauncherBridge();
    final systemAssistant = await enabledAssistant(bridge);
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: recorder,
      voiceTempFiles: VoiceTempFiles(directory: tempDir),
      speechPlayer: FakeSpeechPlayer(),
      lockScreenSession: true,
    );
    assistant.lockScreenVoiceEnabled = true;
    await tester.pumpWidget(
      MaterialApp(
        home: VoiceSessionScreen(
          assistant: assistant,
          systemAssistant: systemAssistant,
        ),
      ),
    );
    await tester.pump();
    await tester.tap(find.byKey(const Key('voice_session_launcher_button')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('voice_session_launcher_button')));
    await tester.pump(const Duration(milliseconds: 120));
    expect(recorder.startCallCount, 1);
    assistant.dispose();
    systemAssistant.dispose();
  });

  test(
    'tap while speaking interrupts and starts the next lock-screen turn',
    () async {
      final recorder = FakeVoiceRecorder();
      final speech = FakeSpeechPlayer(completeImmediately: false);
      final apiClient = voiceClient();
      final auth = AuthController(
        apiClient: apiClient,
        tokenStore: FakeTokenStore(),
        serverUrlStore: FakeServerUrlStore(),
      );
      auth.status = AuthStatus.authenticated;
      final assistant = AssistantController(
        apiClient: apiClient,
        authController: auth,
        voiceRecorder: recorder,
        voiceTempFiles: VoiceTempFiles(directory: tempDir),
        speechPlayer: speech,
        lockScreenSession: true,
      );
      assistant.lockScreenVoiceEnabled = true;
      assistant.keyguardLocked = true;
      final turn = () async {
        await assistant.handleVoiceTrigger(
          source: VoiceInvocationSource.lockScreenLauncher,
        );
        await assistant.handleVoiceTrigger(
          source: VoiceInvocationSource.lockScreenLauncher,
        );
      }();
      await waitUntil(
        () => assistant.voiceState == AssistantVoiceState.speaking,
      );
      expect(assistant.turnSource, VoiceInvocationSource.lockScreenLauncher);
      await assistant.handleVoiceTrigger(
        source: VoiceInvocationSource.lockScreenLauncher,
      );
      await waitUntil(
        () => assistant.voiceState == AssistantVoiceState.recording,
      );
      expect(recorder.startCallCount, 2);
      expect(assistant.turnSource, VoiceInvocationSource.lockScreenLauncher);
      speech.completeHeldPlay();
      await turn;
      assistant.dispose();
    },
  );

  testWidgets('disabled lock-screen voice does not start from the large button', (
    tester,
  ) async {
    SharedPreferences.setMockInitialValues({});
    final recorder = FakeVoiceRecorder();
    final apiClient = voiceClient();
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final bridge = _LauncherBridge();
    final systemAssistant = SystemAssistantController(
      bridge: bridge,
      store: LockScreenVoiceStore(
        preferences: await SharedPreferences.getInstance(),
      ),
    );
    await systemAssistant.attach('user-1');
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: recorder,
      voiceTempFiles: VoiceTempFiles(directory: tempDir),
      speechPlayer: FakeSpeechPlayer(),
      lockScreenSession: true,
    );
    await tester.pumpWidget(
      MaterialApp(
        home: VoiceSessionScreen(
          assistant: assistant,
          systemAssistant: systemAssistant,
        ),
      ),
    );
    await tester.pump();
    expect(find.text(lockScreenVoiceEnabledMessage), findsOneWidget);
    await tester.tap(find.byKey(const Key('voice_session_launcher_button')));
    await tester.pump();
    expect(recorder.startCallCount, 0);
    assistant.dispose();
    systemAssistant.dispose();
  });

  testWidgets(
    'unauthenticated locked overlay does not show AuthSetupScreen',
    (tester) async {
      final apiClient = voiceClient();
      final auth = AuthController(
        apiClient: apiClient,
        tokenStore: FakeTokenStore(),
        serverUrlStore: FakeServerUrlStore(),
      );
      final bridge = _LauncherBridge(keyguardLocked: true);
      final systemAssistant = SystemAssistantController(
        bridge: bridge,
        store: LockScreenVoiceStore(
          preferences: await SharedPreferences.getInstance(),
        ),
      );
      await tester.pumpWidget(
        VoiceSessionApp(
          authController: auth,
          systemAssistant: systemAssistant,
        ),
      );
      await pumpUntil(
        tester,
        () => find
            .byKey(const Key('voice_session_sign_in_required'))
            .evaluate()
            .isNotEmpty,
      );
      expect(find.byType(AuthSetupScreen), findsNothing);
      expect(find.byType(TextField), findsNothing);
      expect(find.text(lockScreenSignInMessage), findsOneWidget);
      systemAssistant.dispose();
    },
  );
}
