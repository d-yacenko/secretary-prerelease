import 'dart:io';

/// Bounded wait until a just-stopped recording file stops growing.
///
/// One 50 ms sample detects growth. Extra polls happen only if the file grew.
/// Never logs or returns audio bytes.
Future<List<({int elapsedMs, int bytes})>> waitUntilRecordingFileFinalized(
  File file, {
  Duration poll = const Duration(milliseconds: 50),
  Duration timeout = const Duration(milliseconds: 500),
}) async {
  final samples = <({int elapsedMs, int bytes})>[];
  final watch = Stopwatch()..start();

  Future<void> sample() async {
    var bytes = 0;
    try {
      if (await file.exists()) {
        bytes = await file.length();
      }
    } catch (_) {
      bytes = 0;
    }
    samples.add((elapsedMs: watch.elapsedMilliseconds, bytes: bytes));
  }

  await sample();
  await Future<void>.delayed(poll);
  await sample();
  if (samples.last.bytes == samples.first.bytes) {
    return samples;
  }

  while (watch.elapsed < timeout) {
    await Future<void>.delayed(poll);
    final previous = samples.last.bytes;
    await sample();
    if (samples.last.bytes == previous) {
      return samples;
    }
  }
  return samples;
}
