import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/account/account_screen.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/assistant/system_assistant_bridge.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/ui/ui_text_scale.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'account_test_helpers.dart';

class FakeSystemAssistantBridge implements SystemAssistantBridge {
  FakeSystemAssistantBridge({
    this.isDefaultAssistant = false,
    this.keyguardLocked = false,
  });

  bool isDefaultAssistant;
  bool keyguardLocked;
  int requestCount = 0;
  int openLauncherCount = 0;
  int clearDrivingCount = 0;
  bool drivingSessionAuthorized = false;
  String? drivingSessionId;
  VoidCallback? onAssist;
  void Function(bool locked)? onKeyguard;

  @override
  void setOnAssist(VoidCallback? callback) {
    onAssist = callback;
  }

  @override
  void setOnKeyguard(void Function(bool locked)? callback) {
    onKeyguard = callback;
  }

  @override
  void setOnRoleResult(void Function(SystemAssistantStatus status)? callback) {}

  @override
  Future<SystemAssistantStatus> getStatus() async {
    return SystemAssistantStatus(
      available: true,
      isDefaultAssistant: isDefaultAssistant,
      roleManagerAvailable: true,
      keyguardLocked: keyguardLocked,
      protocol: systemAssistantProtocol,
      drivingSessionAuthorized: drivingSessionAuthorized,
      drivingSessionId: drivingSessionId,
    );
  }

  @override
  Future<void> requestAssistantRole() async {
    requestCount += 1;
  }

  @override
  Future<void> openLockScreenLauncher() async {
    openLauncherCount += 1;
    if (!keyguardLocked) {
      drivingSessionAuthorized = true;
      drivingSessionId = 'sess-unlocked';
    }
  }

  @override
  Future<void> dismiss() async {
    drivingSessionAuthorized = false;
    drivingSessionId = null;
  }

  @override
  Future<void> clearDrivingSession() async {
    clearDrivingCount += 1;
    drivingSessionAuthorized = false;
    drivingSessionId = null;
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  Future<SystemAssistantController> attachController(
    FakeSystemAssistantBridge bridge,
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

  AccountScreen screen({
    required AuthController auth,
    required SystemAssistantController controller,
  }) {
    return AccountScreen(
      apiClient: auth.apiClient,
      authController: auth,
      initialConnections: Connections.fromJson(accountConnectionsJson()),
      initialSettings: UserSettings.fromJson(accountSettingsJson()),
      initialSourcePreferences: SourcePreferenceList.fromJson(
        accountSourcePreferencesJson(),
      ).preferences,
      initialIdentity: UserIdentity.fromJson(accountIdentityJson()),
      initialSemanticContext: UserSemanticContext.fromJson(
        accountSemanticContextJson(),
      ),
      systemAssistantController: controller,
      systemAssistantPlatform: TargetPlatform.android,
    );
  }

  testWidgets('Android account shows lock-screen launcher, not assistant role', (
    tester,
  ) async {
    final client = buildAccountApiClient();
    final auth = AuthController(
      apiClient: client,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    auth.user = UserMe(
      id: 'user-1',
      displayName: 'Alice',
      createdAt: '2026-01-01T00:00:00Z',
    );
    final bridge = FakeSystemAssistantBridge();
    final controller = await attachController(bridge);
    await pumpAccountReady(tester, screen(auth: auth, controller: controller));
    expect(find.text('Голос с экрана блокировки'), findsOneWidget);
    expect(find.text('Системный помощник'), findsNothing);
    expect(find.text('Выбрать Секретарь помощником…'), findsNothing);
    expect(find.byKey(const Key('system_assistant_request_role')), findsNothing);
    expect(
      find.byKey(const Key('system_assistant_lock_screen')),
      findsOneWidget,
    );
    expect(
      find.text(lockScreenDrivingWritePolicyMessage),
      findsOneWidget,
    );
    expect(
      find.textContaining('по-прежнему требует разблокировки'),
      findsNothing,
    );
    expect(bridge.requestCount, 0);
    await tester.tap(find.byKey(const Key('system_assistant_lock_screen')));
    await tester.pump();
    expect(controller.lockScreenVoiceEnabled, isTrue);
    expect(find.byKey(const Key('lock_screen_open_driving_mode')), findsOneWidget);
    await tester.tap(find.byKey(const Key('lock_screen_open_driving_mode')));
    await tester.pump();
    expect(bridge.openLauncherCount, 1);
    expect(bridge.requestCount, 0);
    controller.dispose();
  });

  testWidgets('Android driving section sits immediately after Profile', (
    tester,
  ) async {
    final client = buildAccountApiClient();
    final auth = AuthController(
      apiClient: client,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    auth.user = UserMe(
      id: 'user-1',
      displayName: 'Alice',
      createdAt: '2026-01-01T00:00:00Z',
    );
    final bridge = FakeSystemAssistantBridge();
    final controller = await attachController(bridge);
    final scale = UiTextScaleController();
    await pumpAccountReady(
      tester,
      UiTextScaleScope(
        controller: scale,
        child: screen(auth: auth, controller: controller),
      ),
    );
    final profileY = tester.getTopLeft(find.text('Профиль')).dy;
    final drivingY = tester
        .getTopLeft(find.text('Голос с экрана блокировки'))
        .dy;
    final scaleY = tester.getTopLeft(find.textContaining('Масштаб текста')).dy;
    expect(profileY, lessThan(drivingY));
    expect(drivingY, lessThan(scaleY));
    final slider = tester.widget<Slider>(
      find.byKey(const Key('ui_text_scale_slider')),
    );
    expect(slider.min, kUiTextScaleMin);
    expect(slider.max, kUiTextScaleMax);
    expect(slider.divisions, kUiTextScaleDivisions);
    expect(slider.min, 0.50);
    expect(slider.max, 1.30);
    controller.dispose();
  });

  testWidgets('Linux account hides lock-screen driving section', (
    tester,
  ) async {
    final client = buildAccountApiClient();
    final auth = AuthController(
      apiClient: client,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    auth.user = UserMe(
      id: 'user-1',
      displayName: 'Alice',
      createdAt: '2026-01-01T00:00:00Z',
    );
    final bridge = FakeSystemAssistantBridge();
    final controller = await attachController(bridge);
    await pumpAccountReady(
      tester,
      AccountScreen(
        apiClient: auth.apiClient,
        authController: auth,
        initialConnections: Connections.fromJson(accountConnectionsJson()),
        initialSettings: UserSettings.fromJson(accountSettingsJson()),
        initialSourcePreferences: SourcePreferenceList.fromJson(
          accountSourcePreferencesJson(),
        ).preferences,
        initialIdentity: UserIdentity.fromJson(accountIdentityJson()),
        initialSemanticContext: UserSemanticContext.fromJson(
          accountSemanticContextJson(),
        ),
        systemAssistantController: controller,
        systemAssistantPlatform: TargetPlatform.linux,
      ),
    );
    expect(find.text('Голос с экрана блокировки'), findsNothing);
    expect(find.byKey(const Key('system_assistant_section')), findsNothing);
    controller.dispose();
  });

  test('disabled lock-screen voice does not open the launcher', () async {
    final bridge = FakeSystemAssistantBridge();
    final controller = await attachController(bridge);
    expect(controller.lockScreenVoiceEnabled, isFalse);
    await controller.openLockScreenLauncher();
    expect(bridge.openLauncherCount, 0);
    expect(bridge.requestCount, 0);
    await controller.setLockScreenVoiceEnabled(true);
    await controller.openLockScreenLauncher();
    expect(bridge.openLauncherCount, 1);
    expect(bridge.requestCount, 0);
    expect(controller.drivingSessionAuthorized, isTrue);
    expect(controller.drivingSessionId, 'sess-unlocked');
    await controller.dismissOverlay();
    expect(controller.drivingSessionAuthorized, isFalse);
    expect(controller.drivingSessionId, isNull);
    controller.dispose();
  });

  test('opening driving while locked does not arm authorization', () async {
    final bridge = FakeSystemAssistantBridge(keyguardLocked: true);
    final controller = await attachController(bridge);
    await controller.setLockScreenVoiceEnabled(true);
    expect(controller.drivingSessionAuthorized, isFalse);
    await controller.openLockScreenLauncher();
    expect(bridge.openLauncherCount, 1);
    expect(controller.drivingSessionAuthorized, isFalse);
    expect(controller.drivingSessionId, isNull);
    controller.dispose();
  });

  test('assistInvoke does not arm driving authorization', () async {
    final bridge = FakeSystemAssistantBridge();
    final controller = await attachController(bridge);
    expect(controller.drivingSessionAuthorized, isFalse);
    bridge.onAssist?.call();
    await controller.refresh();
    expect(controller.drivingSessionAuthorized, isFalse);
    expect(bridge.openLauncherCount, 0);
    controller.dispose();
  });

  test('process default driving authorization is false', () async {
    final bridge = FakeSystemAssistantBridge();
    final controller = await attachController(bridge);
    expect(controller.drivingSessionAuthorized, isFalse);
    expect(controller.drivingSessionId, isNull);
    controller.dispose();
  });

  test('auth loss clears driving authorization fail-closed', () async {
    final bridge = FakeSystemAssistantBridge();
    final controller = await attachController(bridge);
    await controller.setLockScreenVoiceEnabled(true);
    await controller.openLockScreenLauncher();
    expect(controller.drivingSessionAuthorized, isTrue);
    await controller.attach(null);
    expect(controller.drivingSessionAuthorized, isFalse);
    expect(controller.drivingSessionId, isNull);
    expect(bridge.clearDrivingCount, greaterThanOrEqualTo(1));
    controller.dispose();
  });

  test('lock-screen voice pref is per user and defaults off', () async {
    final prefs = await SharedPreferences.getInstance();
    final store = LockScreenVoiceStore(preferences: prefs);
    expect(await store.load('user-a'), isFalse);
    await store.save('user-a', true);
    expect(await store.load('user-a'), isTrue);
    expect(await store.load('user-b'), isFalse);
  });
}
