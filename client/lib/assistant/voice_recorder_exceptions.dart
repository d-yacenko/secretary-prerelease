/// Voice recorder failures mapped to user-visible categories.
sealed class VoiceRecorderException implements Exception {
  const VoiceRecorderException(this.message);

  final String message;
}

class VoiceRecorderPermissionDenied extends VoiceRecorderException {
  const VoiceRecorderPermissionDenied()
      : super('Microphone permission is required for voice input.');
}

class VoiceRecorderEncoderUnsupported extends VoiceRecorderException {
  const VoiceRecorderEncoderUnsupported()
      : super('Voice recording is not supported on this device.');
}

class VoiceRecorderDeviceUnavailable extends VoiceRecorderException {
  const VoiceRecorderDeviceUnavailable()
      : super('Recording device is unavailable.');
}

class VoiceRecorderStartFailure extends VoiceRecorderException {
  const VoiceRecorderStartFailure()
      : super('Voice recording could not start.');
}

class VoiceRecorderStopFailure extends VoiceRecorderException {
  const VoiceRecorderStopFailure() : super('Voice recording failed.');
}
