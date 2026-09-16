/// Android hardware-voice constants. Keep in sync with
/// `HardwareVoiceConstants` / `HardwareVoiceKeyPolicy` in Kotlin.
library;

/// MethodChannel protocol advertised by the native plugin.
const String hardwareVoiceProtocol = 'secretary.hardware_voice.v1';

/// Double-press window for Volume Up fallback and optional generic double.
const int hardwareVoiceDoublePressWindowMs = 500;

/// Learn / test timeout while waiting for a physical key.
const int hardwareVoiceLearnTimeoutMs = 9000;

/// Android `KeyEvent.KEYCODE_VOLUME_UP`.
const int androidKeyCodeVolumeUp = 24;

/// Android navigation / system-critical keys rejected during Learn.
///
/// Matches `android.view.KeyEvent` codes. Volume Up is not rejected; Learn
/// converts it to the dedicated double-press Volume Up preset. Volume Down is
/// rejected so ordinary volume-down is never stolen.
const Set<int> androidRejectedHardwareVoiceKeyCodes = {
  3, // KEYCODE_HOME
  4, // KEYCODE_BACK
  5, // KEYCODE_CALL
  6, // KEYCODE_ENDCALL
  25, // KEYCODE_VOLUME_DOWN
  26, // KEYCODE_POWER
  82, // KEYCODE_MENU
  164, // KEYCODE_VOLUME_MUTE
  187, // KEYCODE_APP_SWITCH / Recents
  223, // KEYCODE_SLEEP
  224, // KEYCODE_WAKEUP
  276, // KEYCODE_SOFT_SLEEP
  280, // KEYCODE_SYSTEM_NAVIGATION_UP
  281, // KEYCODE_SYSTEM_NAVIGATION_DOWN
  282, // KEYCODE_SYSTEM_NAVIGATION_LEFT
  283, // KEYCODE_SYSTEM_NAVIGATION_RIGHT
};

String hardwareVoiceDisplayLabel({
  required int keyCode,
  String? androidKeyName,
}) {
  if (keyCode == androidKeyCodeVolumeUp) {
    return 'Громкость +';
  }
  final name = androidKeyName?.trim();
  if (name != null &&
      name.isNotEmpty &&
      name.toLowerCase() != 'keycode_unknown' &&
      !name.toUpperCase().startsWith('KEYCODE_UNKNOWN')) {
    final lower = name.toLowerCase();
    if (lower.contains('bixby') ||
        lower.contains('assist') && !lower.startsWith('keycode_')) {
      return name;
    }
  }
  return 'Дополнительная кнопка (код $keyCode)';
}
