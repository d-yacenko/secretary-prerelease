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
import 'package:personal_secretary/assistant/voice_session_app.dart';
import 'package:personal_secretary/assistant/voice_session_screen.dart';
import 'package:personal_secretary/assistant/voice_temp_files.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:shared_preferences/shared_preferences.dart';

class DelayedTokenStore implements TokenStore {
  DelayedTokenStore(this._token, {required this.delay});

  final String _token;
  final Duration delay;

  @override
  Future<String?> readToken() async {
    await Future<void>.delayed(delay);
    return _token;
  }

  @override
  Future<void> writeToken(String token) async {}

  @override
  Future<void> deleteToken() async {}
}

class DelayedServerUrlStore implements ServerUrlStore {
  DelayedServerUrlStore(this._url);

  final String _url;

  @override
  Future<String?> readServerUrl() async => _url;

  @override
  Future<void> writeServerUrl(String url) async {}

  @override
  Future<void> deleteServerUrl() async {}
}

class DelayedLockScreenVoiceStore extends LockScreenVoiceStore {
  DelayedLockScreenVoiceStore({
    required super.preferences,
    required this.delay,
  });

  final Duration delay;

  @override
  Future<bool> load(String userId) async {
    await Future<void>.delayed(delay);
    return super.load(userId);
  }
}

class RecordingSystemAssistantBridge implements SystemAssistantBridge {
  RecordingSystemAssistantBridge({
    this.keyguardLocked = true,
    this.statusDelay = Duration.zero,
  });

  bool keyguardLocked;
  Duration statusDelay;
  VoidCallback? onAssist;
  int assistEmits = 0;

  void emitAssist() {
    assistEmits += 1;
    onAssist?.call();
  }

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
    if (statusDelay > Duration.zero) {
      await Future<void>.delayed(statusDelay);
    }
    return SystemAssistantStatus(
      available: true,
      isDefaultAssistant: true,
      roleManagerAvailable: false,
      keyguardLocked: keyguardLocked,
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
    tempDir = Directory.systemTemp.createTempSync('secretary_voice_boot');
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

  SecretaryApiClient authedClient() {
    final client = SecretaryApiClient(
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
          return http.Response.bytes(
            [1, 2, 3, 4],
            200,
            headers: {'content-type': 'audio/mpeg'},
          );
        }
        return http.Response('{}', 404);
      }),
    );
    client.configure(baseUrl: 'https://secretary.example', token: 'boot-token');
    return client;
  }

  Future<void> pumpUntil(WidgetTester tester, bool Function() condition) async {
    final end = DateTime.now().add(const Duration(seconds: 3));
    while (!condition()) {
      if (DateTime.now().isAfter(end)) {
        fail('timed out waiting for condition');
      }
      await tester.pump(const Duration(milliseconds: 20));
    }
  }

  testWidgets(
    'delayed auth and pref load still start an enabled locked session once',
    (tester) async {
      SharedPreferences.setMockInitialValues({
        LockScreenVoiceStore.prefKeyForUser('user-1'): true,
      });
      final prefs = await SharedPreferences.getInstance();
      final recorder = FakeVoiceRecorder();
      final apiClient = authedClient();
      final auth = AuthController(
        apiClient: apiClient,
        tokenStore: DelayedTokenStore(
          'boot-token',
          delay: const Duration(milliseconds: 80),
        ),
        serverUrlStore: DelayedServerUrlStore('https://secretary.example'),
        defaultBaseUrl: 'https://secretary.example',
      );
      final bridge = RecordingSystemAssistantBridge(
        statusDelay: const Duration(milliseconds: 40),
      );
      final systemAssistant = SystemAssistantController(
        bridge: bridge,
        store: DelayedLockScreenVoiceStore(
          preferences: prefs,
          delay: const Duration(milliseconds: 80),
        ),
      );
      final assistant = AssistantController(
        apiClient: apiClient,
        authController: auth,
        voiceRecorder: recorder,
        voiceTempFiles: VoiceTempFiles(directory: tempDir),
        speechPlayer: FakeSpeechPlayer(),
        lockScreenSession: true,
      );
      await tester.pumpWidget(
        VoiceSessionApp(
          authController: auth,
          assistant: assistant,
          systemAssistant: systemAssistant,
        ),
      );
      bridge.emitAssist();
      await tester.pump();
      expect(recorder.startCallCount, 0);
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      await pumpUntil(
        tester,
        () => assistant.voiceState == AssistantVoiceState.recording,
      );
      expect(assistant.lockScreenVoiceEnabled, isTrue);
      expect(assistant.keyguardLocked, isTrue);
      expect(recorder.startCallCount, 1);
      await tester.pump(const Duration(milliseconds: 80));
      assistant.dispose();
      systemAssistant.dispose();
    },
  );

  testWidgets('launcher overlay without assist invoke does not auto-record', (
    tester,
  ) async {
    SharedPreferences.setMockInitialValues({
      LockScreenVoiceStore.prefKeyForUser('user-1'): true,
    });
    final prefs = await SharedPreferences.getInstance();
    final recorder = FakeVoiceRecorder();
    final apiClient = authedClient();
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final bridge = RecordingSystemAssistantBridge();
    final systemAssistant = SystemAssistantController(
      bridge: bridge,
      store: LockScreenVoiceStore(preferences: prefs),
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
    expect(assistant.voiceState, AssistantVoiceState.idle);
    assistant.dispose();
    systemAssistant.dispose();
  });

  testWidgets(
    'delayed auth still keeps a disabled locked session from recording',
    (tester) async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      final recorder = FakeVoiceRecorder();
      final apiClient = authedClient();
      final auth = AuthController(
        apiClient: apiClient,
        tokenStore: DelayedTokenStore(
          'boot-token',
          delay: const Duration(milliseconds: 80),
        ),
        serverUrlStore: DelayedServerUrlStore('https://secretary.example'),
        defaultBaseUrl: 'https://secretary.example',
      );
      final bridge = RecordingSystemAssistantBridge(
        statusDelay: const Duration(milliseconds: 40),
      );
      final systemAssistant = SystemAssistantController(
        bridge: bridge,
        store: DelayedLockScreenVoiceStore(
          preferences: prefs,
          delay: const Duration(milliseconds: 80),
        ),
      );
      final assistant = AssistantController(
        apiClient: apiClient,
        authController: auth,
        voiceRecorder: recorder,
        voiceTempFiles: VoiceTempFiles(directory: tempDir),
        speechPlayer: FakeSpeechPlayer(),
        lockScreenSession: true,
      );
      await tester.pumpWidget(
        VoiceSessionApp(
          authController: auth,
          assistant: assistant,
          systemAssistant: systemAssistant,
        ),
      );
      bridge.emitAssist();
      await tester.pump();
      expect(recorder.startCallCount, 0);
      await pumpUntil(
        tester,
        () => find.text(lockScreenVoiceEnabledMessage).evaluate().isNotEmpty,
      );
      await tester.pump(const Duration(milliseconds: 80));
      expect(recorder.startCallCount, 0);
      expect(assistant.voiceState, AssistantVoiceState.idle);
      assistant.dispose();
      systemAssistant.dispose();
    },
  );

  testWidgets('lock overlay can start then stop on a later assist invoke', (
    tester,
  ) async {
    SharedPreferences.setMockInitialValues({
      LockScreenVoiceStore.prefKeyForUser('user-1'): true,
    });
    final prefs = await SharedPreferences.getInstance();
    final recorder = FakeVoiceRecorder();
    final apiClient = authedClient();
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final bridge = RecordingSystemAssistantBridge();
    final systemAssistant = SystemAssistantController(
      bridge: bridge,
      store: LockScreenVoiceStore(preferences: prefs),
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
    assistant.keyguardLocked = true;
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
    bridge.emitAssist();
    await pumpUntil(
      tester,
      () => assistant.voiceState == AssistantVoiceState.recording,
    );
    expect(recorder.startCallCount, 1);
    bridge.emitAssist();
    await pumpUntil(tester, () => recorder.stopCallCount == 1);
    expect(recorder.startCallCount, 1);
    assistant.dispose();
    systemAssistant.dispose();
  });
}
