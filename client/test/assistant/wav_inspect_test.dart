import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/assistant/wav_inspect.dart';

import 'pcm_wav_fixture.dart';

void main() {
  test('inspects 80 ms phone-sized PCM WAV without reading samples', () {
    final bytes = pcmWavBytes(durationMs: 80);
    expect(bytes.length, 44 + 16000 * 80 ~/ 1000 * 2);
    final inspect = inspectWav(bytes);
    expect(inspect, isNotNull);
    expect(inspect!.validHeader, isTrue);
    expect(inspect.channels, 1);
    expect(inspect.sampleRate, 16000);
    expect(inspect.bitsPerSample, 16);
    expect(inspect.durationMs, 80);
    expect(shouldRejectWavForTranscription(inspect), isTrue);
  });

  test('accepts WAV at the transcription duration floor', () {
    final bytes = pcmWavBytes(durationMs: minTranscribableWavDurationMs);
    final inspect = inspectWav(bytes)!;
    expect(inspect.validHeader, isTrue);
    expect(inspect.durationMs, minTranscribableWavDurationMs);
    expect(shouldRejectWavForTranscription(inspect), isFalse);
  });

  test('ignores non-RIFF fixtures used by recorder tests', () {
    expect(inspectWav([0, 1, 2, 3, 4]), isNull);
  });
}
