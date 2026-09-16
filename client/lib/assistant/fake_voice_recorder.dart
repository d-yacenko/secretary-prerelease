import 'dart:async';
import 'dart:io';

import 'voice_recorder.dart';
import 'voice_recorder_exceptions.dart';

/// Deterministic recorder for tests without microphone access.
class FakeVoiceRecorder implements VoiceRecorder {
  FakeVoiceRecorder({List<int>? audioBytes}) {
    _audioBytes = audioBytes ?? [0, 1, 2, 3, 4];
  }

  bool permissionGranted = true;
  bool requestPermissionResult = true;
  bool failStart = false;
  bool failStartAfterWrite = false;
  bool failStop = false;
  bool throwOnHasPermission = false;
  bool throwOnRequestPermission = false;
  bool throwEncoderUnsupported = false;
  bool isRecording = false;
  String? lastStartedPath;
  int startCallCount = 0;
  int stopCallCount = 0;
  int cancelCallCount = 0;
  Duration startDelay = Duration.zero;
  Duration stopDelay = Duration.zero;
  List<int>? bytesAfterStop;
  Duration growAfterStopDelay = const Duration(milliseconds: 80);
  void Function()? onStart;

  late List<int> _audioBytes;
  String _extension = 'wav';
  String _contentType = 'audio/wav';
  final StreamController<double> _amplitude =
      StreamController<double>.broadcast();

  @override
  String get recordingFileExtension => _extension;

  @override
  String get recordingContentType => _contentType;

  @override
  String get recordingFilename => 'secretary_voice.$_extension';

  @override
  String get recordingDebugEncoder => _extension;

  @override
  Stream<double> get amplitudeSamples => _amplitude.stream;

  void emitAmplitude(double currentDbfs) {
    if (!_amplitude.isClosed) {
      _amplitude.add(currentDbfs);
    }
  }

  @override
  Future<void> prepareRecordingFormat() async {}

  set recordingFileExtension(String value) => _extension = value;

  set recordingContentType(String value) => _contentType = value;

  @override
  Future<bool> hasPermission() async {
    if (throwOnHasPermission) {
      throw StateError('permission check failed');
    }
    return permissionGranted;
  }

  @override
  Future<bool> requestPermission() async {
    if (throwOnRequestPermission) {
      throw StateError('permission request failed');
    }
    permissionGranted = requestPermissionResult;
    return requestPermissionResult;
  }

  @override
  Future<void> startRecording(String filePath) async {
    if (throwEncoderUnsupported) {
      throw const VoiceRecorderEncoderUnsupported();
    }
    startCallCount += 1;
    lastStartedPath = filePath;
    onStart?.call();
    if (startDelay > Duration.zero) {
      await Future<void>.delayed(startDelay);
    }
    File(filePath).writeAsBytesSync(_audioBytes);
    if (failStartAfterWrite) {
      throw StateError('recording start failed after write');
    }
    if (failStart) {
      throw StateError('recording start failed');
    }
    isRecording = true;
  }

  @override
  Future<String> stopRecording() async {
    stopCallCount += 1;
    if (stopDelay > Duration.zero) {
      await Future<void>.delayed(stopDelay);
    }
    if (failStop) {
      throw StateError('recording stop failed');
    }
    isRecording = false;
    if (lastStartedPath == null) {
      throw StateError('no active recording');
    }
    final delayedBytes = bytesAfterStop;
    if (delayedBytes != null) {
      final path = lastStartedPath!;
      Future<void>.delayed(growAfterStopDelay, () {
        File(path).writeAsBytesSync(delayedBytes);
      });
    }
    return lastStartedPath!;
  }

  @override
  Future<void> cancelRecording() async {
    cancelCallCount += 1;
    isRecording = false;
    if (lastStartedPath != null) {
      final file = File(lastStartedPath!);
      if (file.existsSync()) {
        file.deleteSync();
      }
    }
  }

  @override
  Future<void> dispose() async {
    if (!_amplitude.isClosed) {
      await _amplitude.close();
    }
  }
}
