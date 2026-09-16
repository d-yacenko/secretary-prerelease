import 'package:flutter/foundation.dart';

/// Debug-only monotonic timings for one Voice Assistant A turn.
///
/// Never records transcript, audio, tokens, or message body.
class VoiceTurnTiming {
  VoiceTurnTiming._();

  static const tag = 'SecretaryVoiceTiming';

  static final Stopwatch _watch = Stopwatch();
  static final Map<String, int> _marks = <String, int>{};
  static String _turnId = '';

  static void startTurn(String reason) {
    if (!kDebugMode) {
      return;
    }
    _watch
      ..reset()
      ..start();
    _marks.clear();
    _turnId = '${_watch.elapsedMicroseconds}-$reason';
    _marks['accepted'] = 0;
    _line('turn_start reason=$reason');
  }

  static void mark(String name) {
    if (!kDebugMode || !_watch.isRunning) {
      return;
    }
    _marks[name] = _watch.elapsedMilliseconds;
    _line('mark=$name t_ms=${_marks[name]}');
  }

  static void interval(String name, int milliseconds) {
    if (!kDebugMode) {
      return;
    }
    _marks[name] = milliseconds;
    _line('interval=$name ms=$milliseconds');
  }

  static void finish() {
    if (!kDebugMode || !_watch.isRunning) {
      return;
    }
    final parts = _marks.entries
        .map((entry) => '${entry.key}=${entry.value}')
        .join(' ');
    _line('turn_summary $parts');
    _watch.stop();
  }

  static void _line(String message) {
    debugPrint('$tag turn=$_turnId $message');
  }
}
