/// Shortest WAV we will send to the transcription API.
///
/// This is defensive validation, not a recorder-truncation fix. Android
/// capture must still produce a wall-clock-length recording.
const int minTranscribableWavDurationMs = 500;

/// Structural WAV checks. Never logs or returns audio samples.
class WavInspect {
  const WavInspect({
    required this.validHeader,
    required this.channels,
    required this.sampleRate,
    required this.bitsPerSample,
    required this.dataBytes,
    required this.fileBytes,
  });

  final bool validHeader;
  final int channels;
  final int sampleRate;
  final int bitsPerSample;
  final int dataBytes;
  final int fileBytes;

  int get durationMs {
    final byteRate = sampleRate * channels * (bitsPerSample ~/ 8);
    if (byteRate <= 0) {
      return 0;
    }
    return (dataBytes * 1000) ~/ byteRate;
  }

  Map<String, Object> get debugFields => {
    'wav_header_ok': validHeader,
    'wav_channels': channels,
    'wav_sample_rate': sampleRate,
    'wav_bits': bitsPerSample,
    'wav_data_bytes': dataBytes,
    'file_bytes': fileBytes,
    'duration_ms': durationMs,
  };
}

bool shouldRejectWavForTranscription(WavInspect inspect) {
  return !inspect.validHeader ||
      inspect.durationMs < minTranscribableWavDurationMs;
}

WavInspect? inspectWav(List<int> bytes) {
  if (bytes.length < 44) {
    return null;
  }
  if (!_eq(bytes, 0, 'RIFF') || !_eq(bytes, 8, 'WAVE')) {
    return null;
  }
  var offset = 12;
  var channels = 0;
  var sampleRate = 0;
  var bits = 0;
  var dataBytes = 0;
  var foundFmt = false;
  var foundData = false;
  while (offset + 8 <= bytes.length) {
    final id = String.fromCharCodes(bytes.sublist(offset, offset + 4));
    final size = _u32(bytes, offset + 4);
    final next = offset + 8 + size + (size.isOdd ? 1 : 0);
    if (id == 'fmt ' && size >= 16 && offset + 24 <= bytes.length) {
      foundFmt = true;
      channels = _u16(bytes, offset + 10);
      sampleRate = _u32(bytes, offset + 12);
      bits = _u16(bytes, offset + 22);
    } else if (id == 'data') {
      foundData = true;
      dataBytes = size;
    }
    if (next <= offset) {
      break;
    }
    offset = next;
  }
  return WavInspect(
    validHeader: foundFmt && foundData && channels > 0 && sampleRate > 0,
    channels: channels,
    sampleRate: sampleRate,
    bitsPerSample: bits,
    dataBytes: dataBytes,
    fileBytes: bytes.length,
  );
}

bool _eq(List<int> bytes, int offset, String ascii) {
  for (var i = 0; i < ascii.length; i++) {
    if (bytes[offset + i] != ascii.codeUnitAt(i)) {
      return false;
    }
  }
  return true;
}

int _u16(List<int> bytes, int offset) =>
    bytes[offset] | (bytes[offset + 1] << 8);

int _u32(List<int> bytes, int offset) =>
    bytes[offset] |
    (bytes[offset + 1] << 8) |
    (bytes[offset + 2] << 16) |
    (bytes[offset + 3] << 24);
