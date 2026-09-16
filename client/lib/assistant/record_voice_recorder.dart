import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:record/record.dart';

import 'voice_recorder.dart';
import 'voice_recorder_exceptions.dart';

class _RecordingFormat {
  const _RecordingFormat({
    required this.config,
    required this.extension,
    required this.contentType,
  });

  final RecordConfig config;
  final String extension;
  final String contentType;
}

/// Production voice recorder backed by the `record` Flutter package.
class RecordVoiceRecorder implements VoiceRecorder {
  RecordVoiceRecorder() : _recorder = AudioRecorder();

  final AudioRecorder _recorder;
  final StreamController<double> _amplitude =
      StreamController<double>.broadcast();
  StreamSubscription<Amplitude>? _amplitudeSubscription;
  _RecordingFormat? _activeFormat;

  static const List<_RecordingFormat> _candidateFormats = [
    _RecordingFormat(
      config: RecordConfig(
        encoder: AudioEncoder.wav,
        sampleRate: 16000,
        numChannels: 1,
      ),
      extension: 'wav',
      contentType: 'audio/wav',
    ),
    _RecordingFormat(
      config: const RecordConfig(
        encoder: AudioEncoder.aacLc,
        sampleRate: 16000,
        numChannels: 1,
        bitRate: 128000,
      ),
      extension: 'm4a',
      contentType: 'audio/mp4',
    ),
    _RecordingFormat(
      config: const RecordConfig(
        encoder: AudioEncoder.opus,
        sampleRate: 16000,
        numChannels: 1,
      ),
      extension: 'ogg',
      contentType: 'audio/ogg',
    ),
  ];

  @override
  String get recordingFileExtension =>
      _activeFormat?.extension ?? _candidateFormats.first.extension;

  @override
  String get recordingContentType =>
      _activeFormat?.contentType ?? _candidateFormats.first.contentType;

  @override
  String get recordingFilename => 'secretary_voice.$recordingFileExtension';

  @override
  String get recordingDebugEncoder =>
      _activeFormat?.config.encoder.name ?? 'wav';

  @override
  Stream<double> get amplitudeSamples => _amplitude.stream;

  @override
  Future<void> prepareRecordingFormat() async {
    _activeFormat = await _selectSupportedFormat();
  }

  @override
  Future<bool> hasPermission() async {
    try {
      return await _recorder.hasPermission();
    } catch (error, stackTrace) {
      _logStartupFailure('hasPermission', error, stackTrace);
      throw const VoiceRecorderDeviceUnavailable();
    }
  }

  @override
  Future<bool> requestPermission() async {
    try {
      return await _recorder.hasPermission();
    } catch (error, stackTrace) {
      _logStartupFailure('requestPermission', error, stackTrace);
      throw const VoiceRecorderDeviceUnavailable();
    }
  }

  @override
  Future<void> startRecording(String filePath) async {
    final format = _activeFormat ?? await _selectSupportedFormat();
    _activeFormat = format;
    try {
      await _recorder.start(format.config, path: filePath);
      await _listenAmplitude();
    } catch (error, stackTrace) {
      _logStartupFailure('start', error, stackTrace);
      throw _mapStartupError(error);
    }
  }

  @override
  Future<String> stopRecording() async {
    await _stopAmplitude();
    try {
      final path = await _recorder.stop();
      if (path == null || path.isEmpty) {
        throw const VoiceRecorderStopFailure();
      }
      return path;
    } on VoiceRecorderStopFailure {
      rethrow;
    } catch (error, stackTrace) {
      _logStartupFailure('stop', error, stackTrace);
      throw const VoiceRecorderStopFailure();
    }
  }

  @override
  Future<void> cancelRecording() async {
    await _stopAmplitude();
    await _recorder.cancel();
  }

  @override
  Future<void> dispose() async {
    await _stopAmplitude();
    await _amplitude.close();
    await _recorder.dispose();
  }

  Future<void> _listenAmplitude() async {
    await _stopAmplitude();
    try {
      _amplitudeSubscription = _recorder
          .onAmplitudeChanged(const Duration(milliseconds: 100))
          .listen((sample) {
            if (!_amplitude.isClosed) {
              _amplitude.add(sample.current);
            }
          });
    } catch (error, stackTrace) {
      _logStartupFailure('onAmplitudeChanged', error, stackTrace);
    }
  }

  Future<void> _stopAmplitude() async {
    await _amplitudeSubscription?.cancel();
    _amplitudeSubscription = null;
  }

  Future<_RecordingFormat> _selectSupportedFormat() async {
    for (final candidate in _candidateFormats) {
      try {
        if (await _recorder.isEncoderSupported(candidate.config.encoder)) {
          return candidate;
        }
      } catch (error, stackTrace) {
        _logStartupFailure('isEncoderSupported', error, stackTrace);
      }
    }
    throw const VoiceRecorderEncoderUnsupported();
  }

  void _logStartupFailure(String stage, Object error, StackTrace stackTrace) {
    if (!kDebugMode) {
      return;
    }
    debugPrint('Voice recorder $stage failed: ${error.runtimeType}: $error');
    debugPrintStack(stackTrace: stackTrace);
  }

  VoiceRecorderException _mapStartupError(Object error) {
    if (error is ProcessException) {
      final command = error.executable;
      if (command.contains('fmedia') ||
          command.contains('parecord') ||
          command.contains('ffmpeg')) {
        return const VoiceRecorderDeviceUnavailable();
      }
    }
    final text = error.toString();
    if (text.contains('fmedia') ||
        text.contains('parecord') ||
        text.contains('ffmpeg')) {
      return const VoiceRecorderDeviceUnavailable();
    }
    return const VoiceRecorderStartFailure();
  }
}
