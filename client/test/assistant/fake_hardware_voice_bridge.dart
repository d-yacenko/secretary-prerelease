import 'package:flutter/services.dart';
import 'package:personal_secretary/assistant/hardware_voice_bridge.dart';
import 'package:personal_secretary/assistant/hardware_voice_keys.dart';

class FakeHardwareVoiceBridge implements HardwareVoiceBridge {
  HardwareVoiceBridgeListener? listener;
  HardwareVoiceNativeConfig? lastConfig;
  int configureCount = 0;
  int startLearnCount = 0;
  int cancelLearnCount = 0;
  int startTestCount = 0;
  int cancelTestCount = 0;
  int statusCount = 0;
  int setListeningCount = 0;
  bool? lastListening;
  bool disposed = false;
  bool available = true;
  String protocol = hardwareVoiceProtocol;
  String mode = 'disabled';
  Object? statusException;
  Object? configureException;
  Object? startLearnException;
  Object? startTestException;
  bool configureOk = true;

  bool get nativeEnabled => lastConfig?.enabled == true;

  @override
  void setListener(HardwareVoiceBridgeListener? next) {
    listener = next;
  }

  @override
  Future<HardwareVoiceBridgeStatus> getStatus() async {
    statusCount += 1;
    final error = statusException;
    if (error != null) {
      throw error;
    }
    return HardwareVoiceBridgeStatus(
      available: available,
      protocol: protocol,
      mode: mode,
    );
  }

  @override
  Future<HardwareVoiceConfigureAck> configure(
    HardwareVoiceNativeConfig config,
  ) async {
    configureCount += 1;
    lastConfig = config;
    final error = configureException;
    if (error != null) {
      throw error;
    }
    mode = config.enabled ? 'armed' : 'disabled';
    return HardwareVoiceConfigureAck(
      ok: configureOk && available,
      available: available,
      protocol: protocol,
      enabled: configureOk && available && config.enabled,
      message: configureOk ? null : 'native configure failed',
    );
  }

  @override
  Future<void> startLearn({int timeoutMs = hardwareVoiceLearnTimeoutMs}) async {
    startLearnCount += 1;
    final error = startLearnException;
    if (error != null) {
      throw error;
    }
    mode = 'learn';
  }

  @override
  Future<void> cancelLearn() async {
    cancelLearnCount += 1;
    listener?.onLearnResult(
      const HardwareVoiceLearnResult(
        status: HardwareVoiceLearnStatus.cancelled,
      ),
    );
  }

  @override
  Future<void> startTest({int timeoutMs = hardwareVoiceLearnTimeoutMs}) async {
    startTestCount += 1;
    final error = startTestException;
    if (error != null) {
      throw error;
    }
    mode = 'test';
  }

  @override
  Future<void> cancelTest() async {
    cancelTestCount += 1;
    listener?.onTestResult(
      const HardwareVoiceTestResult(status: HardwareVoiceTestStatus.cancelled),
    );
  }

  @override
  Future<void> setListening(bool listening) async {
    setListeningCount += 1;
    lastListening = listening;
  }

  @override
  void dispose() {
    disposed = true;
    listener = null;
  }
}

MissingPluginException missingHardwareVoicePlugin() {
  return MissingPluginException(
    'No implementation found for method getStatus on channel $hardwareVoiceChannelName',
  );
}
