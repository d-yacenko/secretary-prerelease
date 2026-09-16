import 'hardware_voice_keys.dart';

enum HardwareVoiceGesture { single, doublePress }

class HardwareVoiceBinding {
  const HardwareVoiceBinding({
    required this.enabled,
    required this.keyCode,
    required this.gesture,
    required this.displayLabel,
    this.scanCode = 0,
  });

  final bool enabled;
  final int keyCode;
  final int scanCode;
  final HardwareVoiceGesture gesture;
  final String displayLabel;

  bool get isVolumeUp => keyCode == androidKeyCodeVolumeUp;

  HardwareVoiceBinding normalized() {
    if (!isVolumeUp) {
      return this;
    }
    return HardwareVoiceBinding(
      enabled: enabled,
      keyCode: androidKeyCodeVolumeUp,
      scanCode: 0,
      gesture: HardwareVoiceGesture.doublePress,
      displayLabel: 'Громкость +',
    );
  }

  factory HardwareVoiceBinding.volumeUpDouble({bool enabled = true}) {
    return HardwareVoiceBinding(
      enabled: enabled,
      keyCode: androidKeyCodeVolumeUp,
      scanCode: 0,
      gesture: HardwareVoiceGesture.doublePress,
      displayLabel: 'Громкость +',
    );
  }

  factory HardwareVoiceBinding.learned({
    required int keyCode,
    int scanCode = 0,
    String? androidKeyName,
    HardwareVoiceGesture? gesture,
  }) {
    if (keyCode == androidKeyCodeVolumeUp) {
      return HardwareVoiceBinding.volumeUpDouble();
    }
    return HardwareVoiceBinding(
      enabled: true,
      keyCode: keyCode,
      scanCode: scanCode,
      gesture: gesture ?? HardwareVoiceGesture.single,
      displayLabel: hardwareVoiceDisplayLabel(
        keyCode: keyCode,
        androidKeyName: androidKeyName,
      ),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'enabled': enabled,
      'keyCode': keyCode,
      'scanCode': scanCode,
      'gesture': gesture == HardwareVoiceGesture.doublePress
          ? 'double'
          : 'single',
      'displayLabel': displayLabel,
    };
  }

  factory HardwareVoiceBinding.fromJson(Map<String, dynamic> json) {
    final gestureRaw = json['gesture'] as String? ?? 'single';
    final parsed = HardwareVoiceBinding(
      enabled: json['enabled'] as bool? ?? false,
      keyCode: json['keyCode'] as int? ?? 0,
      scanCode: json['scanCode'] as int? ?? 0,
      gesture: gestureRaw == 'double'
          ? HardwareVoiceGesture.doublePress
          : HardwareVoiceGesture.single,
      displayLabel: json['displayLabel'] as String? ?? '',
    );
    return parsed.normalized();
  }

  HardwareVoiceBinding copyWith({
    bool? enabled,
    int? keyCode,
    int? scanCode,
    HardwareVoiceGesture? gesture,
    String? displayLabel,
  }) {
    return HardwareVoiceBinding(
      enabled: enabled ?? this.enabled,
      keyCode: keyCode ?? this.keyCode,
      scanCode: scanCode ?? this.scanCode,
      gesture: gesture ?? this.gesture,
      displayLabel: displayLabel ?? this.displayLabel,
    ).normalized();
  }

  String get statusPrimary {
    if (!enabled) {
      return 'Не настроена';
    }
    if (displayLabel.trim().isEmpty) {
      return hardwareVoiceDisplayLabel(keyCode: keyCode);
    }
    return displayLabel;
  }

  String? get statusSecondary {
    if (!enabled) {
      return null;
    }
    return gesture == HardwareVoiceGesture.doublePress
        ? 'Двойное нажатие'
        : 'Одно нажатие';
  }
}
