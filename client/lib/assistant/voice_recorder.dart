/// Cross-platform voice recording abstraction for short Assistant commands.
abstract class VoiceRecorder {
  /// File extension for the active recording format (without dot).
  String get recordingFileExtension => 'wav';

  /// MIME type matching [recordingFileExtension].
  String get recordingContentType => 'audio/wav';

  /// Upload filename for transcription.
  String get recordingFilename => 'secretary_voice.$recordingFileExtension';

  /// Encoder name for debug diagnostics (no audio payload).
  String get recordingDebugEncoder => recordingFileExtension;

  /// Select the active encoder before the temp path is created.
  Future<void> prepareRecordingFormat() async {}

  Future<bool> hasPermission();

  Future<bool> requestPermission();

  Future<void> startRecording(String filePath);

  Future<String> stopRecording();

  Future<void> cancelRecording();

  /// Live microphone amplitude in dBFS while recording. Empty if unavailable.
  Stream<double> get amplitudeSamples => const Stream.empty();

  Future<void> dispose();
}
