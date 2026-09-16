import 'package:flutter/services.dart';

import 'hardware_voice_binding.dart';
import 'hardware_voice_keys.dart';

const hardwareVoiceChannelName = 'secretary/hardware_voice';

class HardwareVoiceNativeConfig {
  const HardwareVoiceNativeConfig({
    required this.enabled,
    required this.keyCode,
    required this.scanCode,
    required this.gesture,
  });

  final bool enabled;
  final int keyCode;
  final int scanCode;
  final HardwareVoiceGesture gesture;

  Map<String, dynamic> toMap() {
    return {
      'enabled': enabled,
      'keyCode': keyCode,
      'scanCode': scanCode,
      'gesture': gesture == HardwareVoiceGesture.doublePress
          ? 'double'
          : 'single',
    };
  }
}

class HardwareVoiceBridgeStatus {
  const HardwareVoiceBridgeStatus({
    required this.available,
    this.protocol = '',
    this.mode = 'disabled',
  });

  final bool available;
  final String protocol;
  final String mode;

  bool get isHealthy => available && protocol == hardwareVoiceProtocol;
}

class HardwareVoiceConfigureAck {
  const HardwareVoiceConfigureAck({
    required this.ok,
    required this.available,
    this.protocol = '',
    this.enabled = false,
    this.message,
  });

  final bool ok;
  final bool available;
  final String protocol;
  final bool enabled;
  final String? message;
}

enum HardwareVoiceLearnStatus {
  captured,
  rejected,
  timeout,
  cancelled,
  bridgeError,
}

class HardwareVoiceLearnResult {
  const HardwareVoiceLearnResult({
    required this.status,
    this.keyCode,
    this.scanCode = 0,
    this.androidKeyName,
    this.message,
  });

  final HardwareVoiceLearnStatus status;
  final int? keyCode;
  final int scanCode;
  final String? androidKeyName;
  final String? message;

  bool get isCaptured =>
      status == HardwareVoiceLearnStatus.captured && keyCode != null;
}

enum HardwareVoiceTestStatus { recognized, timeout, cancelled, bridgeError }

class HardwareVoiceTestResult {
  const HardwareVoiceTestResult({required this.status, this.message});

  final HardwareVoiceTestStatus status;
  final String? message;

  bool get isRecognized => status == HardwareVoiceTestStatus.recognized;
}

abstract class HardwareVoiceBridge {
  void setListener(HardwareVoiceBridgeListener? listener);

  Future<HardwareVoiceBridgeStatus> getStatus();

  Future<HardwareVoiceConfigureAck> configure(HardwareVoiceNativeConfig config);

  Future<void> startLearn({int timeoutMs = hardwareVoiceLearnTimeoutMs});

  Future<void> cancelLearn();

  Future<void> startTest({int timeoutMs = hardwareVoiceLearnTimeoutMs});

  Future<void> cancelTest();

  Future<void> setListening(bool listening);

  void dispose();
}

class HardwareVoiceBridgeListener {
  const HardwareVoiceBridgeListener({
    required this.onVoiceTrigger,
    required this.onLearnResult,
    required this.onTestResult,
  });

  final void Function() onVoiceTrigger;
  final void Function(HardwareVoiceLearnResult result) onLearnResult;
  final void Function(HardwareVoiceTestResult result) onTestResult;
}

class NoopHardwareVoiceBridge implements HardwareVoiceBridge {
  @override
  void setListener(HardwareVoiceBridgeListener? listener) {}

  @override
  Future<HardwareVoiceBridgeStatus> getStatus() async {
    return const HardwareVoiceBridgeStatus(available: false);
  }

  @override
  Future<HardwareVoiceConfigureAck> configure(
    HardwareVoiceNativeConfig config,
  ) async {
    return const HardwareVoiceConfigureAck(ok: false, available: false);
  }

  @override
  Future<void> startLearn({
    int timeoutMs = hardwareVoiceLearnTimeoutMs,
  }) async {}

  @override
  Future<void> cancelLearn() async {}

  @override
  Future<void> startTest({int timeoutMs = hardwareVoiceLearnTimeoutMs}) async {}

  @override
  Future<void> cancelTest() async {}

  @override
  Future<void> setListening(bool listening) async {}

  @override
  void dispose() {}
}

class MethodChannelHardwareVoiceBridge implements HardwareVoiceBridge {
  MethodChannelHardwareVoiceBridge({MethodChannel? channel})
    : _channel = channel ?? const MethodChannel(hardwareVoiceChannelName) {
    _channel.setMethodCallHandler(_onMethodCall);
  }

  final MethodChannel _channel;
  HardwareVoiceBridgeListener? _listener;

  @override
  void setListener(HardwareVoiceBridgeListener? listener) {
    _listener = listener;
  }

  @override
  Future<HardwareVoiceBridgeStatus> getStatus() async {
    try {
      final raw = await _channel.invokeMethod<dynamic>('getStatus');
      return _parseStatus(raw);
    } on MissingPluginException {
      return const HardwareVoiceBridgeStatus(available: false);
    } on PlatformException {
      return const HardwareVoiceBridgeStatus(available: false);
    }
  }

  @override
  Future<HardwareVoiceConfigureAck> configure(
    HardwareVoiceNativeConfig config,
  ) async {
    try {
      final raw = await _channel.invokeMethod<dynamic>(
        'configure',
        config.toMap(),
      );
      return _parseAck(raw);
    } on MissingPluginException catch (error) {
      return HardwareVoiceConfigureAck(
        ok: false,
        available: false,
        message: error.message,
      );
    } on PlatformException catch (error) {
      return HardwareVoiceConfigureAck(
        ok: false,
        available: false,
        message: error.message,
      );
    }
  }

  @override
  Future<void> startLearn({int timeoutMs = hardwareVoiceLearnTimeoutMs}) async {
    await _channel.invokeMethod<void>('startLearn', {'timeoutMs': timeoutMs});
  }

  @override
  Future<void> cancelLearn() async {
    await _channel.invokeMethod<void>('cancelLearn');
  }

  @override
  Future<void> startTest({int timeoutMs = hardwareVoiceLearnTimeoutMs}) async {
    await _channel.invokeMethod<void>('startTest', {'timeoutMs': timeoutMs});
  }

  @override
  Future<void> cancelTest() async {
    await _channel.invokeMethod<void>('cancelTest');
  }

  @override
  Future<void> setListening(bool listening) async {
    try {
      await _channel.invokeMethod<void>('setListening', {
        'listening': listening,
      });
    } on MissingPluginException {
      return;
    } on PlatformException {
      return;
    }
  }

  @override
  void dispose() {
    _listener = null;
    _channel.setMethodCallHandler(null);
  }

  Future<dynamic> _onMethodCall(MethodCall call) async {
    final listener = _listener;
    if (listener == null) {
      return null;
    }
    switch (call.method) {
      case 'onVoiceTrigger':
        listener.onVoiceTrigger();
        return null;
      case 'onLearnResult':
        listener.onLearnResult(_parseLearn(call.arguments));
        return null;
      case 'onTestResult':
        listener.onTestResult(_parseTest(call.arguments));
        return null;
      default:
        return null;
    }
  }

  HardwareVoiceBridgeStatus _parseStatus(dynamic arguments) {
    final map = _asMap(arguments);
    final protocol = map['protocol'] as String? ?? '';
    final available = map['available'] == true;
    return HardwareVoiceBridgeStatus(
      available: available,
      protocol: protocol,
      mode: map['mode'] as String? ?? 'disabled',
    );
  }

  HardwareVoiceConfigureAck _parseAck(dynamic arguments) {
    final map = _asMap(arguments);
    final protocol = map['protocol'] as String? ?? '';
    final available = map['available'] == true;
    final ok =
        map['ok'] == true && available && protocol == hardwareVoiceProtocol;
    return HardwareVoiceConfigureAck(
      ok: ok,
      available: available,
      protocol: protocol,
      enabled: map['enabled'] == true,
      message: map['message'] as String?,
    );
  }

  HardwareVoiceLearnResult _parseLearn(dynamic arguments) {
    final map = _asMap(arguments);
    final statusRaw = map['status'] as String? ?? 'timeout';
    final status = switch (statusRaw) {
      'captured' => HardwareVoiceLearnStatus.captured,
      'rejected' => HardwareVoiceLearnStatus.rejected,
      'cancelled' => HardwareVoiceLearnStatus.cancelled,
      'bridgeError' => HardwareVoiceLearnStatus.bridgeError,
      _ => HardwareVoiceLearnStatus.timeout,
    };
    return HardwareVoiceLearnResult(
      status: status,
      keyCode: _asInt(map['keyCode']),
      scanCode: _asInt(map['scanCode']) ?? 0,
      androidKeyName: map['androidKeyName'] as String?,
      message: map['message'] as String?,
    );
  }

  HardwareVoiceTestResult _parseTest(dynamic arguments) {
    final map = _asMap(arguments);
    final statusRaw = map['status'] as String? ?? 'timeout';
    final status = switch (statusRaw) {
      'recognized' => HardwareVoiceTestStatus.recognized,
      'cancelled' => HardwareVoiceTestStatus.cancelled,
      'bridgeError' => HardwareVoiceTestStatus.bridgeError,
      _ => HardwareVoiceTestStatus.timeout,
    };
    return HardwareVoiceTestResult(
      status: status,
      message: map['message'] as String?,
    );
  }

  Map<String, dynamic> _asMap(dynamic arguments) {
    if (arguments is Map) {
      return Map<String, dynamic>.from(arguments);
    }
    return <String, dynamic>{};
  }

  int? _asInt(dynamic value) {
    if (value is int) {
      return value;
    }
    if (value is num) {
      return value.toInt();
    }
    return null;
  }
}
