import 'package:flutter/foundation.dart';

import 'voice_invocation_source.dart';
import 'wav_inspect.dart';

/// Debug-only Voice capture metadata. Never records audio, transcript, or tokens.
class VoiceCaptureDiagnostics {
  VoiceCaptureDiagnostics._();

  static const tag = 'SecretaryVoiceCapture';
  static const cueMode = 'no_media_during_capture';

  static String _turnId = '';
  static VoiceInvocationSource _source = VoiceInvocationSource.typed;
  static final Stopwatch _watch = Stopwatch();
  static final List<Map<String, Object?>> events = <Map<String, Object?>>[];

  static String get turnId => _turnId;

  static int get elapsedMs => _watch.isRunning ? _watch.elapsedMilliseconds : 0;

  static void resetForTest() {
    _turnId = '';
    _source = VoiceInvocationSource.typed;
    _watch.stop();
    _watch.reset();
    events.clear();
  }

  static void startTurn({
    required String turnId,
    required VoiceInvocationSource source,
  }) {
    _turnId = turnId;
    _source = source;
    _watch
      ..reset()
      ..start();
    event('turn_start', {'source': source.name, 'cue_mode': cueMode});
  }

  static void event(String name, [Map<String, Object?> fields = const {}]) {
    final payload = <String, Object?>{
      'turn': _turnId,
      'source': _source.name,
      'event': name,
      't_ms': elapsedMs,
      ...fields,
    };
    events.add(Map<String, Object?>.from(payload));
    final rendered = payload.entries
        .map((entry) => '${entry.key}=${entry.value}')
        .join(' ');
    debugPrint('$tag $rendered');
  }

  static void trigger({
    required VoiceInvocationSource source,
    required String state,
  }) {
    event('handleVoiceTrigger', {
      'invoked_source': source.name,
      'state': state,
    });
  }

  static void recordingInterval({
    required int wallClockMs,
    required int fileBytes,
    WavInspect? wav,
  }) {
    event('recording_result', {
      'wall_clock_ms': wallClockMs,
      'file_bytes': fileBytes,
      if (wav != null) ...wav.debugFields,
    });
  }
}
