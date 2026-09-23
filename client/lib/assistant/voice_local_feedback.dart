import 'dart:async';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// Network-independent local Voice cues. Never persists files.
///
/// [playAck] means only "invocation recognized" (haptic; no media).
/// [playReady] is an audible hands-free "speak after the tone" cue. It must
/// complete and release the player before the microphone starts.
/// [playStop] means stop / processing and must run only after recorder stop.
abstract class VoiceLocalFeedback {
  Future<void> playAck();

  Future<void> playReady();

  Future<void> playStop();

  /// One local failure cue. Must not loop or call a provider.
  Future<void> playError();

  /// Release any media audio focus before the microphone starts.
  Future<void> releasePlayback();

  Future<void> dispose();
}

class NoopVoiceLocalFeedback implements VoiceLocalFeedback {
  const NoopVoiceLocalFeedback();

  @override
  Future<void> playAck() async {}

  @override
  Future<void> playReady() async {}

  @override
  Future<void> playStop() async {}

  @override
  Future<void> playError() async {}

  @override
  Future<void> releasePlayback() async {}

  @override
  Future<void> dispose() async {}
}

class RecordingVoiceLocalFeedback implements VoiceLocalFeedback {
  RecordingVoiceLocalFeedback({this.isRecorderActive});

  bool Function()? isRecorderActive;
  int ackCount = 0;
  int readyCount = 0;
  int stopCount = 0;
  int errorCount = 0;
  int releaseCount = 0;
  final List<String> mediaWhileRecording = <String>[];
  final List<String> sequence = <String>[];

  void _noteMedia(String name) {
    sequence.add(name);
    if (isRecorderActive?.call() == true) {
      mediaWhileRecording.add(name);
    }
  }

  @override
  Future<void> playAck() async {
    ackCount += 1;
    sequence.add('ack');
  }

  @override
  Future<void> playReady() async {
    readyCount += 1;
    _noteMedia('ready');
  }

  @override
  Future<void> playStop() async {
    stopCount += 1;
    _noteMedia('stop');
  }

  @override
  Future<void> playError() async {
    errorCount += 1;
    sequence.add('error');
  }

  @override
  Future<void> releasePlayback() async {
    releaseCount += 1;
    sequence.add('release');
  }

  @override
  Future<void> dispose() async {}
}

class AssetVoiceLocalFeedback implements VoiceLocalFeedback {
  AssetVoiceLocalFeedback({
    AudioPlayer? player,
    Future<void> Function()? haptic,
  }) : _player = player ?? AudioPlayer(),
       _haptic = haptic ?? (() => HapticFeedback.lightImpact());

  final AudioPlayer _player;
  final Future<void> Function() _haptic;
  bool _failed = false;
  Completer<void>? _playDone;

  @override
  Future<void> playAck() async {
    try {
      await _haptic();
    } catch (_) {}
  }

  @override
  Future<void> playReady() async {
    await _play('sounds/voice_start.wav');
  }

  @override
  Future<void> playStop() async {
    await _play('sounds/voice_stop.wav');
  }

  @override
  Future<void> playError() async {
    try {
      await SystemSound.play(SystemSoundType.alert);
    } catch (_) {}
  }

  @override
  Future<void> releasePlayback() async {
    await _stopPlayer();
  }

  Future<void> _play(String asset) async {
    if (_failed) {
      return;
    }
    try {
      await _stopPlayer();
      final done = Completer<void>();
      _playDone = done;
      late final StreamSubscription<void> completed;
      completed = _player.onPlayerComplete.listen((_) {
        if (!done.isCompleted) {
          done.complete();
        }
      });
      try {
        await _player.play(AssetSource(asset));
        await done.future;
      } finally {
        await completed.cancel();
        if (_playDone == done) {
          _playDone = null;
        }
      }
      await _stopPlayer();
    } catch (error) {
      _failed = true;
      if (kDebugMode) {
        debugPrint('SecretaryVoiceTiming cue_failed ${error.runtimeType}');
      }
    }
  }

  Future<void> _stopPlayer() async {
    final pending = _playDone;
    try {
      await _player.stop();
    } catch (_) {}
    if (pending != null && !pending.isCompleted) {
      pending.complete();
    }
  }

  @override
  Future<void> dispose() async {
    try {
      await _stopPlayer();
      await _player.dispose();
    } catch (_) {}
  }
}
