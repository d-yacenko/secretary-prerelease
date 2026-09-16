import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/assistant/hardware_voice_binding.dart';
import 'package:personal_secretary/assistant/hardware_voice_bridge.dart';
import 'package:personal_secretary/assistant/hardware_voice_controller.dart';
import 'package:personal_secretary/assistant/hardware_voice_keys.dart';
import 'package:personal_secretary/assistant/hardware_voice_store.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_hardware_voice_bridge.dart';

AuthController buildAuth({String userId = 'user-a'}) {
  final auth = AuthController(
    apiClient: SecretaryApiClient(),
    tokenStore: FakeTokenStore(),
    serverUrlStore: FakeServerUrlStore(),
  );
  auth.status = AuthStatus.authenticated;
  auth.user = UserMe(
    id: userId,
    displayName: userId,
    createdAt: '2026-01-01T00:00:00Z',
  );
  return auth;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  test('binding persists locally for the authenticated user', () async {
    final prefs = await SharedPreferences.getInstance();
    final store = HardwareVoiceStore(preferences: prefs);
    final auth = buildAuth();
    final bridge = FakeHardwareVoiceBridge();
    final controller = HardwareVoiceController(
      authController: auth,
      store: store,
      bridge: bridge,
    );
    await controller.attach();
    await controller.saveLearned(keyCode: 1082, scanCode: 11);
    expect(controller.binding!.keyCode, 1082);
    expect(controller.binding!.gesture, HardwareVoiceGesture.single);
    expect(bridge.nativeEnabled, isTrue);

    final other = HardwareVoiceController(
      authController: buildAuth(),
      store: HardwareVoiceStore(preferences: prefs),
      bridge: FakeHardwareVoiceBridge(),
    );
    await other.attach();
    expect(other.binding!.keyCode, 1082);
    expect(other.binding!.scanCode, 11);
    other.dispose();
    controller.dispose();
  });

  test('bindings are separated by authenticated user id', () async {
    final prefs = await SharedPreferences.getInstance();
    final store = HardwareVoiceStore(preferences: prefs);
    final authA = buildAuth(userId: 'user-a');
    final bridgeA = FakeHardwareVoiceBridge();
    final a = HardwareVoiceController(
      authController: authA,
      store: store,
      bridge: bridgeA,
    );
    await a.attach();
    await a.saveLearned(keyCode: 1082);
    a.dispose();

    final authB = buildAuth(userId: 'user-b');
    final bridgeB = FakeHardwareVoiceBridge();
    final b = HardwareVoiceController(
      authController: authB,
      store: store,
      bridge: bridgeB,
    );
    await b.attach();
    expect(b.binding, isNull);
    await b.useVolumeUpDouble();
    expect(b.binding!.keyCode, androidKeyCodeVolumeUp);
    b.dispose();

    final aAgain = HardwareVoiceController(
      authController: buildAuth(userId: 'user-a'),
      store: store,
      bridge: FakeHardwareVoiceBridge(),
    );
    await aAgain.attach();
    expect(aAgain.binding!.keyCode, 1082);
    aAgain.dispose();
  });

  test(
    'logout disables native binding but keeps the user-namespaced pref',
    () async {
      final prefs = await SharedPreferences.getInstance();
      final store = HardwareVoiceStore(preferences: prefs);
      final auth = buildAuth();
      final bridge = FakeHardwareVoiceBridge();
      final controller = HardwareVoiceController(
        authController: auth,
        store: store,
        bridge: bridge,
      );
      await controller.attach();
      await controller.useVolumeUpDouble();
      expect(bridge.nativeEnabled, isTrue);

      auth.terminateAuthenticatedSession();
      await Future<void>.delayed(Duration.zero);
      expect(bridge.nativeEnabled, isFalse);
      expect(await store.load('user-a'), isA<HardwareVoiceBinding>());
      controller.dispose();
    },
  );

  test('generic learned key defaults to single press', () {
    final binding = HardwareVoiceBinding.learned(keyCode: 1082, scanCode: 4);
    expect(binding.gesture, HardwareVoiceGesture.single);
    expect(binding.isVolumeUp, isFalse);
  });

  test('Volume Up preset is forced to double press', () {
    final learned = HardwareVoiceBinding.learned(
      keyCode: androidKeyCodeVolumeUp,
    );
    expect(learned.gesture, HardwareVoiceGesture.doublePress);
    expect(learned.displayLabel, 'Громкость +');
    final coerced = HardwareVoiceBinding(
      enabled: true,
      keyCode: androidKeyCodeVolumeUp,
      gesture: HardwareVoiceGesture.single,
      displayLabel: 'ignored',
    ).normalized();
    expect(coerced.gesture, HardwareVoiceGesture.doublePress);
  });

  test('Volume Up double-press window is 500 ms', () {
    expect(hardwareVoiceDoublePressWindowMs, 500);
  });

  test('disabling binding prevents activation', () async {
    final auth = buildAuth();
    final bridge = FakeHardwareVoiceBridge();
    final controller = HardwareVoiceController(
      authController: auth,
      store: HardwareVoiceStore(
        preferences: await SharedPreferences.getInstance(),
      ),
      bridge: bridge,
    );
    var triggers = 0;
    controller.onShellVoiceTrigger = () async {
      triggers += 1;
      return true;
    };
    await controller.attach();
    await controller.saveLearned(keyCode: 1082);
    await controller.disable();
    controller.debugEmitVoiceTrigger();
    expect(triggers, 0);
    expect(bridge.nativeEnabled, isFalse);
    controller.dispose();
  });

  test('learn and test native events do not start Voice', () async {
    final auth = buildAuth();
    final bridge = FakeHardwareVoiceBridge();
    final controller = HardwareVoiceController(
      authController: auth,
      store: HardwareVoiceStore(
        preferences: await SharedPreferences.getInstance(),
      ),
      bridge: bridge,
    );
    var triggers = 0;
    controller.onShellVoiceTrigger = () async {
      triggers += 1;
      return true;
    };
    await controller.attach();
    await controller.useVolumeUpDouble();
    final learn = controller.startLearn();
    controller.debugEmitVoiceTrigger();
    expect(triggers, 0);
    controller.debugEmitLearnResult(
      const HardwareVoiceLearnResult(status: HardwareVoiceLearnStatus.timeout),
    );
    await learn;

    final test = controller.startTest();
    controller.debugEmitVoiceTrigger();
    expect(triggers, 0);
    controller.debugEmitTestResult(
      const HardwareVoiceTestResult(status: HardwareVoiceTestStatus.recognized),
    );
    await test;
    expect(triggers, 0);
    controller.dispose();
  });

  test('bridge ping success marks the native handler available', () async {
    final bridge = FakeHardwareVoiceBridge();
    final controller = HardwareVoiceController(
      authController: buildAuth(),
      store: HardwareVoiceStore(
        preferences: await SharedPreferences.getInstance(),
      ),
      bridge: bridge,
    );
    await controller.attach();
    expect(controller.isBridgeAvailable, isTrue);
    expect(controller.bridgeProtocol, hardwareVoiceProtocol);
    expect(controller.handlerBanner, isNull);
    expect(bridge.statusCount, greaterThan(0));
    controller.dispose();
  });

  test('MissingPlugin learn failure is not a physical-key timeout', () async {
    final bridge = FakeHardwareVoiceBridge();
    final controller = HardwareVoiceController(
      authController: buildAuth(),
      store: HardwareVoiceStore(
        preferences: await SharedPreferences.getInstance(),
      ),
      bridge: bridge,
    );
    await controller.attach();
    bridge.startLearnException = missingHardwareVoicePlugin();
    final result = await controller.startLearn();
    expect(result.status, HardwareVoiceLearnStatus.bridgeError);
    expect(result.status, isNot(HardwareVoiceLearnStatus.timeout));
    expect(result.message, contains('переустановка'));
    expect(controller.isBridgeAvailable, isFalse);
    controller.dispose();
  });

  test(
    'failed native configure is not shown as a healthy active binding',
    () async {
      final bridge = FakeHardwareVoiceBridge()..configureOk = false;
      final controller = HardwareVoiceController(
        authController: buildAuth(),
        store: HardwareVoiceStore(
          preferences: await SharedPreferences.getInstance(),
        ),
        bridge: bridge,
      );
      await controller.attach();
      await controller.useVolumeUpDouble();
      expect(controller.hasSavedEnabledBinding, isTrue);
      expect(controller.isNativeActive, isFalse);
      expect(controller.statusSecondary, 'Сохранена, но не активна');
      expect(controller.handlerBanner, isNotNull);
      controller.dispose();
    },
  );

  test('restore of saved binding surfaces native configure failure', () async {
    final prefs = await SharedPreferences.getInstance();
    final store = HardwareVoiceStore(preferences: prefs);
    final prepared = HardwareVoiceController(
      authController: buildAuth(),
      store: store,
      bridge: FakeHardwareVoiceBridge(),
    );
    await prepared.attach();
    await prepared.useVolumeUpDouble();
    prepared.dispose();

    final failing = FakeHardwareVoiceBridge()..configureOk = false;
    final restored = HardwareVoiceController(
      authController: buildAuth(),
      store: store,
      bridge: failing,
    );
    await restored.attach();
    expect(restored.binding!.keyCode, androidKeyCodeVolumeUp);
    expect(restored.isNativeActive, isFalse);
    expect(restored.statusSecondary, 'Сохранена, но не активна');
    restored.dispose();
  });

  test('Learn single Volume Up captures as Volume Up double', () async {
    final controller = HardwareVoiceController(
      authController: buildAuth(),
      store: HardwareVoiceStore(
        preferences: await SharedPreferences.getInstance(),
      ),
      bridge: FakeHardwareVoiceBridge(),
    );
    await controller.attach();
    await controller.saveLearned(keyCode: androidKeyCodeVolumeUp, scanCode: 33);
    expect(controller.binding!.isVolumeUp, isTrue);
    expect(controller.binding!.gesture, HardwareVoiceGesture.doublePress);
    expect(controller.binding!.scanCode, 0);
    expect(controller.isNativeActive, isTrue);
    controller.dispose();
  });

  test('Test distinguishes native error from gesture timeout', () async {
    final bridge = FakeHardwareVoiceBridge();
    final controller = HardwareVoiceController(
      authController: buildAuth(),
      store: HardwareVoiceStore(
        preferences: await SharedPreferences.getInstance(),
      ),
      bridge: bridge,
    );
    await controller.attach();
    await controller.useVolumeUpDouble();
    bridge.startTestException = missingHardwareVoicePlugin();
    final nativeError = await controller.startTest();
    expect(nativeError.status, HardwareVoiceTestStatus.bridgeError);

    bridge.startTestException = null;
    await controller.useVolumeUpDouble();
    expect(controller.isNativeActive, isTrue);
    final timeout = controller.startTest();
    controller.debugEmitTestResult(
      const HardwareVoiceTestResult(status: HardwareVoiceTestStatus.timeout),
    );
    final timedOut = await timeout;
    expect(timedOut.status, HardwareVoiceTestStatus.timeout);
    controller.dispose();
  });
}
