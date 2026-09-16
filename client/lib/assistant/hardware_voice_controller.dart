import 'dart:async';
import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import '../auth/auth_controller.dart';
import 'hardware_voice_binding.dart';
import 'hardware_voice_bridge.dart';
import 'hardware_voice_keys.dart';
import 'hardware_voice_store.dart';

enum HardwareVoiceUiPhase { idle, learning, testing }

const hardwareVoiceReinstallMessage =
    'Обработчик аппаратных кнопок недоступен.\n'
    'Требуется полная переустановка приложения.';

const hardwareVoiceOemTimeoutMessage =
    'Обработчик работает, но Android не передал событие от этой кнопки.';

class HardwareVoiceController extends ChangeNotifier {
  HardwareVoiceController({
    required AuthController authController,
    HardwareVoiceStore? store,
    HardwareVoiceBridge? bridge,
  }) : _authController = authController,
       _store = store ?? HardwareVoiceStore(),
       _bridge =
           bridge ??
           (!kIsWeb && Platform.isAndroid
               ? MethodChannelHardwareVoiceBridge()
               : NoopHardwareVoiceBridge()) {
    _bridge.setListener(
      HardwareVoiceBridgeListener(
        onVoiceTrigger: _onNativeVoiceTrigger,
        onLearnResult: _onNativeLearnResult,
        onTestResult: _onNativeTestResult,
      ),
    );
    _authController.addListener(_onAuthChanged);
  }

  final AuthController _authController;
  final HardwareVoiceStore _store;
  final HardwareVoiceBridge _bridge;

  HardwareVoiceBinding? _binding;
  HardwareVoiceUiPhase _phase = HardwareVoiceUiPhase.idle;
  Completer<HardwareVoiceLearnResult>? _learnCompleter;
  Completer<HardwareVoiceTestResult>? _testCompleter;
  String? _activeUserId;
  String? _learnHint;
  bool _bridgeAvailable = false;
  String _bridgeProtocol = '';
  bool _nativeActive = false;
  String? _nativeError;

  /// AppShell sets this to switch to Assistant and invoke the canonical trigger.
  Future<bool> Function()? onShellVoiceTrigger;

  HardwareVoiceBinding? get binding => _binding;
  HardwareVoiceUiPhase get phase => _phase;
  bool get hasSavedEnabledBinding => _binding != null && _binding!.enabled;
  bool get hasEnabledBinding => hasSavedEnabledBinding;
  bool get isNativeActive =>
      _bridgeAvailable && _nativeActive && hasSavedEnabledBinding;
  bool get isBridgeAvailable => _bridgeAvailable;
  bool get isLearning => _phase == HardwareVoiceUiPhase.learning;
  bool get isTesting => _phase == HardwareVoiceUiPhase.testing;
  String? get learnHint => _learnHint;
  String? get nativeError => _nativeError;
  String get bridgeProtocol => _bridgeProtocol;

  String? get handlerBanner {
    if (!_bridgeAvailable) {
      return hardwareVoiceReinstallMessage;
    }
    return _nativeError;
  }

  String get statusPrimary {
    if (!_bridgeAvailable) {
      return 'Обработчик аппаратных кнопок недоступен';
    }
    if (hasSavedEnabledBinding) {
      return _binding!.statusPrimary;
    }
    return 'Не настроена';
  }

  String? get statusSecondary {
    if (!_bridgeAvailable) {
      return 'Требуется полная переустановка приложения.';
    }
    if (!hasSavedEnabledBinding) {
      return null;
    }
    if (!_nativeActive) {
      return 'Сохранена, но не активна';
    }
    return _binding!.statusSecondary;
  }

  Future<void> attach() async {
    await _refreshBridgeStatus();
    await _syncFromAuth();
  }

  Future<void> useVolumeUpDouble() async {
    await _saveAndConfigure(HardwareVoiceBinding.volumeUpDouble());
  }

  Future<void> saveLearned({
    required int keyCode,
    int scanCode = 0,
    String? androidKeyName,
  }) async {
    await _saveAndConfigure(
      HardwareVoiceBinding.learned(
        keyCode: keyCode,
        scanCode: scanCode,
        androidKeyName: androidKeyName,
      ),
    );
  }

  Future<void> setGesture(HardwareVoiceGesture gesture) async {
    final current = _binding;
    if (current == null || !current.enabled) {
      return;
    }
    if (current.isVolumeUp) {
      await _saveAndConfigure(HardwareVoiceBinding.volumeUpDouble());
      return;
    }
    await _saveAndConfigure(current.copyWith(gesture: gesture));
  }

  Future<void> disable() async {
    final userId = _authController.user?.id;
    _binding = null;
    _nativeActive = false;
    _nativeError = null;
    if (userId != null) {
      await _store.clear(userId);
    }
    await _disableNative();
    notifyListeners();
  }

  Future<HardwareVoiceLearnResult> startLearn({
    int timeoutMs = hardwareVoiceLearnTimeoutMs,
  }) async {
    if (_phase != HardwareVoiceUiPhase.idle) {
      return const HardwareVoiceLearnResult(
        status: HardwareVoiceLearnStatus.cancelled,
      );
    }
    _phase = HardwareVoiceUiPhase.learning;
    _learnHint = null;
    final completer = Completer<HardwareVoiceLearnResult>();
    _learnCompleter = completer;
    notifyListeners();
    await _refreshBridgeStatus();
    if (!_bridgeAvailable) {
      _phase = HardwareVoiceUiPhase.idle;
      final result = const HardwareVoiceLearnResult(
        status: HardwareVoiceLearnStatus.bridgeError,
        message: hardwareVoiceReinstallMessage,
      );
      if (!completer.isCompleted) {
        completer.complete(result);
      }
      _learnCompleter = null;
      notifyListeners();
      return completer.future;
    }
    try {
      await _bridge.startLearn(timeoutMs: timeoutMs);
    } catch (error) {
      _phase = HardwareVoiceUiPhase.idle;
      if (error is MissingPluginException) {
        _bridgeAvailable = false;
        _nativeActive = false;
        _nativeError = hardwareVoiceReinstallMessage;
      }
      final result = HardwareVoiceLearnResult(
        status: HardwareVoiceLearnStatus.bridgeError,
        message: _bridgeErrorMessage(error),
      );
      if (!completer.isCompleted) {
        completer.complete(result);
      }
      _learnCompleter = null;
      notifyListeners();
      return completer.future;
    }
    return completer.future;
  }

  Future<void> cancelLearn() async {
    if (_phase != HardwareVoiceUiPhase.learning) {
      return;
    }
    try {
      await _bridge.cancelLearn();
    } catch (_) {
      _onNativeLearnResult(
        const HardwareVoiceLearnResult(
          status: HardwareVoiceLearnStatus.cancelled,
        ),
      );
    }
  }

  Future<HardwareVoiceTestResult> startTest({
    int timeoutMs = hardwareVoiceLearnTimeoutMs,
  }) async {
    if (!isNativeActive) {
      return HardwareVoiceTestResult(
        status: HardwareVoiceTestStatus.bridgeError,
        message: _bridgeAvailable
            ? (_nativeError ??
                  'Не удалось активировать обработчик аппаратных кнопок.')
            : hardwareVoiceReinstallMessage,
      );
    }
    if (_phase != HardwareVoiceUiPhase.idle) {
      return const HardwareVoiceTestResult(
        status: HardwareVoiceTestStatus.cancelled,
      );
    }
    _phase = HardwareVoiceUiPhase.testing;
    final completer = Completer<HardwareVoiceTestResult>();
    _testCompleter = completer;
    notifyListeners();
    await _refreshBridgeStatus();
    if (!_bridgeAvailable) {
      _phase = HardwareVoiceUiPhase.idle;
      final result = const HardwareVoiceTestResult(
        status: HardwareVoiceTestStatus.bridgeError,
        message: hardwareVoiceReinstallMessage,
      );
      if (!completer.isCompleted) {
        completer.complete(result);
      }
      _testCompleter = null;
      notifyListeners();
      return completer.future;
    }
    try {
      await _bridge.startTest(timeoutMs: timeoutMs);
    } catch (error) {
      _phase = HardwareVoiceUiPhase.idle;
      if (error is MissingPluginException) {
        _bridgeAvailable = false;
        _nativeActive = false;
        _nativeError = hardwareVoiceReinstallMessage;
      }
      final result = HardwareVoiceTestResult(
        status: HardwareVoiceTestStatus.bridgeError,
        message: _bridgeErrorMessage(error),
      );
      if (!completer.isCompleted) {
        completer.complete(result);
      }
      _testCompleter = null;
      notifyListeners();
      return completer.future;
    }
    return completer.future;
  }

  Future<void> cancelTest() async {
    if (_phase != HardwareVoiceUiPhase.testing) {
      return;
    }
    try {
      await _bridge.cancelTest();
    } catch (_) {
      _onNativeTestResult(
        const HardwareVoiceTestResult(
          status: HardwareVoiceTestStatus.cancelled,
        ),
      );
    }
  }

  Future<void> setListening(bool listening) async {
    await _bridge.setListening(listening);
  }

  @visibleForTesting
  void debugEmitVoiceTrigger() {
    _onNativeVoiceTrigger();
  }

  @visibleForTesting
  void debugEmitLearnResult(HardwareVoiceLearnResult result) {
    _onNativeLearnResult(result);
  }

  @visibleForTesting
  void debugEmitTestResult(HardwareVoiceTestResult result) {
    _onNativeTestResult(result);
  }

  Future<void> _onAuthChanged() async {
    await _syncFromAuth();
  }

  Future<void> _syncFromAuth() async {
    final user = _authController.user;
    final authenticated = _authController.status == AuthStatus.authenticated;
    if (!authenticated || user == null) {
      _activeUserId = null;
      _binding = null;
      _nativeActive = false;
      _nativeError = null;
      _abortSessions();
      await _disableNative();
      notifyListeners();
      return;
    }
    await _refreshBridgeStatus();
    if (_activeUserId == user.id && _binding != null) {
      if (_binding!.enabled) {
        await _configureNative(_binding!);
      } else {
        await _disableNative();
      }
      notifyListeners();
      return;
    }
    _activeUserId = user.id;
    _binding = await _store.load(user.id);
    if (_binding != null && _binding!.enabled) {
      await _configureNative(_binding!);
    } else {
      await _disableNative();
    }
    notifyListeners();
  }

  Future<void> _saveAndConfigure(HardwareVoiceBinding binding) async {
    final userId = _authController.user?.id;
    final normalized = binding.normalized();
    _binding = normalized;
    if (userId != null) {
      await _store.save(userId, normalized);
    }
    if (normalized.enabled) {
      await _configureNative(normalized);
    } else {
      await _disableNative();
    }
    notifyListeners();
  }

  Future<void> _refreshBridgeStatus() async {
    try {
      final status = await _bridge.getStatus();
      _bridgeAvailable = status.isHealthy;
      _bridgeProtocol = status.protocol;
      if (!_bridgeAvailable) {
        _nativeActive = false;
        _nativeError = hardwareVoiceReinstallMessage;
      }
    } catch (_) {
      _bridgeAvailable = false;
      _bridgeProtocol = '';
      _nativeActive = false;
      _nativeError = hardwareVoiceReinstallMessage;
    }
  }

  Future<void> _configureNative(HardwareVoiceBinding binding) async {
    late final HardwareVoiceConfigureAck ack;
    try {
      ack = await _bridge.configure(
        HardwareVoiceNativeConfig(
          enabled: binding.enabled,
          keyCode: binding.keyCode,
          scanCode: binding.scanCode,
          gesture: binding.gesture,
        ),
      );
    } catch (error) {
      _bridgeAvailable = false;
      _bridgeProtocol = '';
      _nativeActive = false;
      _nativeError = _bridgeErrorMessage(error);
      return;
    }
    _applyConfigureAck(ack, desiredEnabled: binding.enabled);
  }

  Future<void> _disableNative() async {
    _nativeActive = false;
    try {
      final ack = await _bridge.configure(
        const HardwareVoiceNativeConfig(
          enabled: false,
          keyCode: 0,
          scanCode: 0,
          gesture: HardwareVoiceGesture.single,
        ),
      );
      if (ack.available && ack.protocol == hardwareVoiceProtocol) {
        _bridgeAvailable = true;
        _bridgeProtocol = ack.protocol;
        if (_nativeError == hardwareVoiceReinstallMessage) {
          _nativeError = null;
        }
      }
    } catch (_) {
      // Logout must still clear local armed state even if native is missing.
    }
  }

  void _applyConfigureAck(
    HardwareVoiceConfigureAck ack, {
    required bool desiredEnabled,
  }) {
    _bridgeAvailable = ack.available && ack.protocol == hardwareVoiceProtocol;
    _bridgeProtocol = ack.protocol;
    if (!ack.ok || !_bridgeAvailable) {
      _nativeActive = false;
      _nativeError = _bridgeAvailable
          ? (ack.message ??
                'Не удалось активировать обработчик аппаратных кнопок.')
          : hardwareVoiceReinstallMessage;
      return;
    }
    _nativeActive = desiredEnabled && ack.enabled;
    _nativeError = _nativeActive
        ? null
        : 'Не удалось активировать обработчик аппаратных кнопок.';
  }

  void _abortSessions() {
    final learn = _learnCompleter;
    if (learn != null && !learn.isCompleted) {
      learn.complete(
        const HardwareVoiceLearnResult(
          status: HardwareVoiceLearnStatus.cancelled,
        ),
      );
    }
    _learnCompleter = null;
    final test = _testCompleter;
    if (test != null && !test.isCompleted) {
      test.complete(
        const HardwareVoiceTestResult(
          status: HardwareVoiceTestStatus.cancelled,
        ),
      );
    }
    _testCompleter = null;
    _learnHint = null;
    _phase = HardwareVoiceUiPhase.idle;
  }

  void _onNativeVoiceTrigger() {
    if (_phase != HardwareVoiceUiPhase.idle) {
      return;
    }
    if (!isNativeActive) {
      return;
    }
    final handler = onShellVoiceTrigger;
    if (handler == null) {
      return;
    }
    unawaited(handler());
  }

  void _onNativeLearnResult(HardwareVoiceLearnResult result) {
    if (_phase != HardwareVoiceUiPhase.learning) {
      return;
    }
    if (result.status == HardwareVoiceLearnStatus.rejected) {
      _learnHint =
          result.message ?? 'Эту кнопку нельзя назначить голосовому помощнику.';
      notifyListeners();
      return;
    }
    _phase = HardwareVoiceUiPhase.idle;
    _learnHint = null;
    final completer = _learnCompleter;
    _learnCompleter = null;
    if (completer != null && !completer.isCompleted) {
      completer.complete(result);
    }
    notifyListeners();
    unawaited(_restoreNativeAfterSession());
  }

  void _onNativeTestResult(HardwareVoiceTestResult result) {
    if (_phase != HardwareVoiceUiPhase.testing) {
      return;
    }
    _phase = HardwareVoiceUiPhase.idle;
    final completer = _testCompleter;
    _testCompleter = null;
    if (completer != null && !completer.isCompleted) {
      completer.complete(result);
    }
    notifyListeners();
    unawaited(_restoreNativeAfterSession());
  }

  Future<void> _restoreNativeAfterSession() async {
    final current = _binding;
    if (current != null && current.enabled) {
      await _configureNative(current);
    } else {
      await _disableNative();
    }
    notifyListeners();
  }

  String _bridgeErrorMessage(Object error) {
    if (error is MissingPluginException) {
      return hardwareVoiceReinstallMessage;
    }
    return hardwareVoiceReinstallMessage;
  }

  @override
  void dispose() {
    _authController.removeListener(_onAuthChanged);
    onShellVoiceTrigger = null;
    _abortSessions();
    _bridge.dispose();
    super.dispose();
  }
}
