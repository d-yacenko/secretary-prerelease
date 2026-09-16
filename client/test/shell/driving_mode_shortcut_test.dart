import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/account/system_assistant_account_section.dart';
import 'package:personal_secretary/assistant/assistant_controller.dart';
import 'package:personal_secretary/assistant/fake_voice_recorder.dart';
import 'package:personal_secretary/assistant/system_assistant_bridge.dart';
import 'package:personal_secretary/assistant/voice_temp_files.dart';
import 'package:personal_secretary/capture/capture_controller.dart';
import 'package:personal_secretary/shell/app_shell.dart';
import 'package:personal_secretary/shell/driving_mode_shortcut.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'app_shell_test.dart';

class FakeDrivingBridge implements SystemAssistantBridge {
  int requestCount = 0;
  int openLauncherCount = 0;

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
      isDefaultAssistant: false,
      roleManagerAvailable: true,
      keyguardLocked: false,
      protocol: systemAssistantProtocol,
      drivingSessionAuthorized: true,
      drivingSessionId: 'sess-unlocked',
    );
  }

  @override
  Future<void> requestAssistantRole() async {
    requestCount += 1;
  }

  @override
  Future<void> openLockScreenLauncher() async {
    openLauncherCount += 1;
  }

  @override
  Future<void> dismiss() async {}

  @override
  Future<void> clearDrivingSession() async {}
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  Future<SystemAssistantController> attachController(
    FakeDrivingBridge bridge, {
    bool enabled = false,
  }) async {
    final prefs = await SharedPreferences.getInstance();
    if (enabled) {
      await prefs.setBool(LockScreenVoiceStore.prefKeyForUser('u1'), true);
    }
    final controller = SystemAssistantController(
      bridge: bridge,
      store: LockScreenVoiceStore(preferences: prefs),
    );
    await controller.attach('u1');
    return controller;
  }

  Future<void> pumpShell(
    WidgetTester tester, {
    required SystemAssistantController controller,
    TargetPlatform platform = TargetPlatform.android,
    Size size = const Size(400, 800),
  }) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final auth = buildAuth();
    final capture = CaptureController(
      apiClient: auth.apiClient,
      authController: auth,
    );
    final assistant = AssistantController(
      apiClient: auth.apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(
        directory: Directory.systemTemp.createTempSync('driving_shortcut'),
      ),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: AppShell(
          authController: auth,
          captureController: capture,
          assistantController: assistant,
          graphController: buildGraph(auth),
          systemAssistantController: controller,
          platform: platform,
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  Future<void> pumpShortcut(
    WidgetTester tester,
    SystemAssistantController controller,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          appBar: AppBar(
            actions: [DrivingModeShortcutButton(controller: controller)],
          ),
        ),
      ),
    );
  }

  testWidgets('Android shortcut is visible next to Account', (tester) async {
    final bridge = FakeDrivingBridge();
    final controller = await attachController(bridge);
    await pumpShell(tester, controller: controller);
    expect(find.byKey(drivingModeShortcutButtonKey), findsOneWidget);
    expect(find.byIcon(Icons.directions_car), findsOneWidget);
    expect(find.byTooltip(drivingModeShortcutTooltip), findsOneWidget);
    expect(find.byKey(const Key('shell_account_button')), findsOneWidget);
    final drivingX = tester
        .getTopLeft(find.byKey(drivingModeShortcutButtonKey))
        .dx;
    final accountX = tester
        .getTopLeft(find.byKey(const Key('shell_account_button')))
        .dx;
    expect(drivingX, lessThan(accountX));
    controller.dispose();
  });

  testWidgets('Linux shortcut is hidden', (tester) async {
    final bridge = FakeDrivingBridge();
    final controller = await attachController(bridge, enabled: true);
    await pumpShell(
      tester,
      controller: controller,
      platform: TargetPlatform.linux,
    );
    expect(find.byKey(drivingModeShortcutButtonKey), findsNothing);
    expect(find.byIcon(Icons.directions_car), findsNothing);
    expect(find.byKey(const Key('shell_account_button')), findsOneWidget);
    controller.dispose();
  });

  testWidgets('enabled shortcut launches driving mode once', (tester) async {
    final bridge = FakeDrivingBridge();
    final controller = await attachController(bridge, enabled: true);
    await pumpShortcut(tester, controller);
    await tester.tap(find.byKey(drivingModeShortcutButtonKey));
    await tester.pumpAndSettle();
    expect(find.byKey(drivingModeEnableDialogKey), findsNothing);
    expect(bridge.openLauncherCount, 1);
    expect(bridge.requestCount, 0);
    controller.dispose();
  });

  testWidgets('disabled shortcut shows confirmation', (tester) async {
    final bridge = FakeDrivingBridge();
    final controller = await attachController(bridge);
    await pumpShortcut(tester, controller);
    await tester.tap(find.byKey(drivingModeShortcutButtonKey));
    await tester.pumpAndSettle();
    expect(find.byKey(drivingModeEnableDialogKey), findsOneWidget);
    expect(find.text(drivingModeEnableConfirmMessage), findsOneWidget);
    expect(find.text(drivingModeEnableConfirmLabel), findsOneWidget);
    expect(bridge.openLauncherCount, 0);
    expect(controller.lockScreenVoiceEnabled, isFalse);
    controller.dispose();
  });

  testWidgets('cancel leaves preference off and does not launch', (
    tester,
  ) async {
    final bridge = FakeDrivingBridge();
    final controller = await attachController(bridge);
    await pumpShortcut(tester, controller);
    await tester.tap(find.byKey(drivingModeShortcutButtonKey));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(drivingModeEnableCancelKey));
    await tester.pumpAndSettle();
    expect(find.byKey(drivingModeEnableDialogKey), findsNothing);
    expect(controller.lockScreenVoiceEnabled, isFalse);
    expect(bridge.openLauncherCount, 0);
    expect(bridge.requestCount, 0);
    final prefs = await SharedPreferences.getInstance();
    expect(
      prefs.getBool(LockScreenVoiceStore.prefKeyForUser('u1')),
      isNot(true),
    );
    controller.dispose();
  });

  testWidgets('confirm enables preference and launches once', (tester) async {
    final bridge = FakeDrivingBridge();
    final controller = await attachController(bridge);
    await pumpShortcut(tester, controller);
    await tester.tap(find.byKey(drivingModeShortcutButtonKey));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(drivingModeEnableConfirmKey));
    await tester.pumpAndSettle();
    expect(find.byKey(drivingModeEnableDialogKey), findsNothing);
    expect(controller.lockScreenVoiceEnabled, isTrue);
    expect(bridge.openLauncherCount, 1);
    expect(bridge.requestCount, 0);
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getBool(LockScreenVoiceStore.prefKeyForUser('u1')), isTrue);
    controller.dispose();
  });

  testWidgets('Profile driving entry still launches', (tester) async {
    final bridge = FakeDrivingBridge();
    final controller = await attachController(bridge, enabled: true);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SystemAssistantAccountSection(
            controller: controller,
            platform: TargetPlatform.android,
          ),
        ),
      ),
    );
    await tester.tap(find.byKey(const Key('lock_screen_open_driving_mode')));
    await tester.pumpAndSettle();
    expect(bridge.openLauncherCount, 1);
    expect(bridge.requestCount, 0);
    controller.dispose();
  });
}
