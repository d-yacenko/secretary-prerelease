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
import 'package:personal_secretary/assistant/voice_session_screen.dart';
import 'package:personal_secretary/assistant/voice_temp_files.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _LockedBridge implements SystemAssistantBridge {
  @override
  void setOnAssist(VoidCallback? callback) {}

  @override
  void setOnKeyguard(void Function(bool locked)? callback) {}

  @override
  void setOnRoleResult(void Function(SystemAssistantStatus status)? callback) {}

  @override
  Future<SystemAssistantStatus> getStatus() async {
    return const SystemAssistantStatus(
      available: true,
      isDefaultAssistant: true,
      roleManagerAvailable: false,
      keyguardLocked: true,
      protocol: systemAssistantProtocol,
    );
  }

  @override
  Future<void> requestAssistantRole() async {}

  @override
  Future<void> openLockScreenLauncher() async {}

  @override
  Future<void> dismiss() async {}

  @override
  Future<void> clearDrivingSession() async {}
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory tempDir;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    tempDir = Directory.systemTemp.createTempSync('secretary_voice_session_ui');
  });

  tearDown(() {
    if (tempDir.existsSync()) {
      tempDir.deleteSync(recursive: true);
    }
  });

  testWidgets('lock overlay shows status only, no chat history', (
    tester,
  ) async {
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((_) async => http.Response('{}', 404)),
    );
    apiClient.configure(baseUrl: 'https://secretary.example', token: 't');
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(directory: tempDir),
      speechPlayer: FakeSpeechPlayer(),
      lockScreenSession: true,
    );
    final systemAssistant = SystemAssistantController(
      bridge: _LockedBridge(),
      store: LockScreenVoiceStore(
        preferences: await SharedPreferences.getInstance(),
      ),
    );
    await systemAssistant.attach('user-1');
    await tester.pumpWidget(
      MaterialApp(
        home: VoiceSessionScreen(
          assistant: assistant,
          systemAssistant: systemAssistant,
        ),
      ),
    );
    await tester.pump();
    expect(find.byKey(const Key('voice_session_status')), findsOneWidget);
    expect(find.text(lockScreenVoiceEnabledMessage), findsOneWidget);
    expect(find.byType(ListView), findsNothing);
    expect(find.textContaining('Входящие'), findsNothing);
    assistant.dispose();
    systemAssistant.dispose();
  });
}
