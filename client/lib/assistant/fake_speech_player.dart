import 'dart:async';

import 'speech_player.dart';

/// Deterministic player for tests. Completes immediately unless [holdPlay] is set.
class FakeSpeechPlayer implements SpeechPlayer {
  FakeSpeechPlayer({this.completeImmediately = true});

  bool completeImmediately;
  bool failNextPlay = false;
  final List<String> playedPaths = [];
  int playCount = 0;
  int stopCount = 0;
  int disposeCount = 0;
  Completer<void>? _held;

  @override
  Future<void> playFile(String path) async {
    playCount += 1;
    playedPaths.add(path);
    if (failNextPlay) {
      failNextPlay = false;
      throw StateError('speech playback failed');
    }
    if (completeImmediately) {
      return;
    }
    _held = Completer<void>();
    await _held!.future;
  }

  void completeHeldPlay() {
    final held = _held;
    if (held != null && !held.isCompleted) {
      held.complete();
    }
  }

  @override
  Future<void> stop() async {
    stopCount += 1;
    completeHeldPlay();
  }

  @override
  Future<void> dispose() async {
    disposeCount += 1;
    completeHeldPlay();
  }
}
