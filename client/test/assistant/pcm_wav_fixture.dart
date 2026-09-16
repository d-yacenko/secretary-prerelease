List<int> pcmWavBytes({required int durationMs, int sampleRate = 16000}) {
  final samples = (sampleRate * durationMs) ~/ 1000;
  if (samples <= 0) {
    throw ArgumentError.value(durationMs, 'durationMs');
  }
  final dataBytes = samples * 2;
  final byteRate = sampleRate * 2;
  final bytes = <int>[
    ..._ascii('RIFF'),
    ..._u32(36 + dataBytes),
    ..._ascii('WAVE'),
    ..._ascii('fmt '),
    ..._u32(16),
    ..._u16(1),
    ..._u16(1),
    ..._u32(sampleRate),
    ..._u32(byteRate),
    ..._u16(2),
    ..._u16(16),
    ..._ascii('data'),
    ..._u32(dataBytes),
    ...List<int>.filled(dataBytes, 0),
  ];
  return bytes;
}

List<int> _ascii(String value) => value.codeUnits;

List<int> _u16(int value) => [value & 0xff, (value >> 8) & 0xff];

List<int> _u32(int value) => [
  value & 0xff,
  (value >> 8) & 0xff,
  (value >> 16) & 0xff,
  (value >> 24) & 0xff,
];
