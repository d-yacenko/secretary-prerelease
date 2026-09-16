import 'dart:async';

import 'voice_capture_diagnostics.dart';

/// Adaptive dBFS VAD for Driving Mode. Does not treat amplitude 0 as speech.
class DrivingAmplitudeVad {
  DrivingAmplitudeVad({
    this.speechRiseDb = 10,
    this.minSpeechDbfs = -50,
    this.floorAdapt = 0.05,
  });

  final double speechRiseDb;
  final double minSpeechDbfs;
  final double floorAdapt;

  double? _noiseFloor;

  bool isSpeech(double current) {
    if (current.isNaN || current.isInfinite) {
      return false;
    }
    if (_noiseFloor == null) {
      _noiseFloor = current;
      return _classify(current);
    }
    if (current < _noiseFloor!) {
      _noiseFloor = current;
    } else {
      _noiseFloor = _noiseFloor! + (current - _noiseFloor!) * floorAdapt;
    }
    return _classify(current);
  }

  bool _classify(double current) {
    final floor = _noiseFloor!;
    return current >= minSpeechDbfs && current >= floor + speechRiseDb;
  }

  void reset() {
    _noiseFloor = null;
  }
}

/// Arms a 3.0s silence timer only after speech has been heard at least once.
class DrivingSilenceMonitor {
  DrivingSilenceMonitor({
    required Stream<double> amplitudeSamples,
    required Future<void> Function() onAutoStop,
    this.silenceHold = const Duration(seconds: 3),
  }) : _amplitudeSamples = amplitudeSamples,
       _onAutoStop = onAutoStop;

  final Stream<double> _amplitudeSamples;
  final Future<void> Function() _onAutoStop;
  final Duration silenceHold;

  final DrivingAmplitudeVad _vad = DrivingAmplitudeVad();
  StreamSubscription<double>? _subscription;
  Timer? _silenceTimer;
  int _generation = 0;
  bool _active = false;
  bool _speechHeard = false;

  bool get isActive => _active;

  void start() {
    cancel(emitCancelled: false);
    final generation = ++_generation;
    _active = true;
    _speechHeard = false;
    _vad.reset();
    VoiceCaptureDiagnostics.event('silence_monitor_started');
    _subscription = _amplitudeSamples.listen((current) {
      if (generation != _generation || !_active) {
        return;
      }
      _onAmplitude(current, generation);
    });
  }

  void _onAmplitude(double current, int generation) {
    if (_vad.isSpeech(current)) {
      if (!_speechHeard) {
        VoiceCaptureDiagnostics.event('speech_detected');
      }
      _speechHeard = true;
      _silenceTimer?.cancel();
      _silenceTimer = null;
      return;
    }
    if (!_speechHeard) {
      return;
    }
    _silenceTimer ??= Timer(silenceHold, () {
      if (generation != _generation || !_active) {
        return;
      }
      VoiceCaptureDiagnostics.event('silence_auto_stop_triggered');
      cancel(emitCancelled: true);
      unawaited(_onAutoStop());
    });
  }

  void cancel({bool emitCancelled = true}) {
    _silenceTimer?.cancel();
    _silenceTimer = null;
    _subscription?.cancel();
    _subscription = null;
    _vad.reset();
    _speechHeard = false;
    if (_active && emitCancelled) {
      VoiceCaptureDiagnostics.event('silence_monitor_cancelled');
    }
    _active = false;
    _generation++;
  }
}
