import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/account/account_screen.dart';
import 'package:personal_secretary/account/hardware_voice_account_section.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/assistant/hardware_voice_controller.dart';
import 'package:personal_secretary/assistant/hardware_voice_store.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../assistant/fake_hardware_voice_bridge.dart';
import 'account_test_helpers.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  Future<HardwareVoiceController> buildHardware(AuthController auth) async {
    final controller = HardwareVoiceController(
      authController: auth,
      store: HardwareVoiceStore(
        preferences: await SharedPreferences.getInstance(),
      ),
      bridge: FakeHardwareVoiceBridge(),
    );
    await controller.attach();
    return controller;
  }

  AccountScreen screen({
    required AuthController auth,
    required HardwareVoiceController hardware,
    TargetPlatform platform = TargetPlatform.android,
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
      hardwareVoiceController: hardware,
      hardwareVoicePlatform: platform,
    );
  }

  testWidgets('Android account section shows hardware voice controls', (
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
    final hardware = await buildHardware(auth);
    await pumpAccountReady(tester, screen(auth: auth, hardware: hardware));
    expect(find.text('Голосовой помощник'), findsOneWidget);
    expect(find.text('Не настроена'), findsOneWidget);
    expect(find.text('Выбрать кнопку…'), findsOneWidget);
    expect(
      find.text('Использовать «Громкость +» (двойное нажатие)'),
      findsOneWidget,
    );
    expect(find.byKey(const Key('hardware_voice_bridge_error')), findsNothing);
    hardware.dispose();
  });

  testWidgets('unavailable native bridge shows reinstall copy', (tester) async {
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
    final hardware = HardwareVoiceController(
      authController: auth,
      store: HardwareVoiceStore(
        preferences: await SharedPreferences.getInstance(),
      ),
      bridge: FakeHardwareVoiceBridge()..available = false,
    );
    await hardware.attach();
    await pumpAccountReady(tester, screen(auth: auth, hardware: hardware));
    expect(
      find.byKey(const Key('hardware_voice_bridge_error')),
      findsOneWidget,
    );
    expect(find.textContaining('переустановка'), findsWidgets);
    hardware.dispose();
  });

  testWidgets('Linux does not show Android hardware-button selector', (
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
    final hardware = await buildHardware(auth);
    await pumpAccountReady(
      tester,
      screen(auth: auth, hardware: hardware, platform: TargetPlatform.linux),
    );
    expect(find.text('Голосовой помощник'), findsNothing);
    hardware.dispose();
  });

  test('hardwareVoiceSettingsVisible is Android-only', () {
    expect(
      hardwareVoiceSettingsVisible(platform: TargetPlatform.android),
      isTrue,
    );
    expect(
      hardwareVoiceSettingsVisible(platform: TargetPlatform.linux),
      isFalse,
    );
  });
}
