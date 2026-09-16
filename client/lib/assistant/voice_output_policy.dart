import 'voice_invocation_source.dart';

/// Device-local auto-speech preference. Not synced to UserSettings.
enum VoiceOutputPolicy {
  /// Speak hands-free invocations only (hardware / system assistant /
  /// lock-screen launcher). The on-screen microphone is dictation and never
  /// auto-speaks.
  handsFreeEnabled,

  /// Never auto-speak Assistant answers.
  never,
}

extension VoiceOutputPolicySpeech on VoiceOutputPolicy {
  bool allowsAutoSpeech(VoiceInvocationSource source) {
    if (source == VoiceInvocationSource.screenMic ||
        source == VoiceInvocationSource.typed) {
      return false;
    }
    switch (this) {
      case VoiceOutputPolicy.never:
        return false;
      case VoiceOutputPolicy.handsFreeEnabled:
        return source.isHandsFree;
    }
  }
}
