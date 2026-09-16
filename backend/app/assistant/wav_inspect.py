"""Structural WAV checks. Never logs or returns audio samples."""

MIN_TRANSCRIBABLE_WAV_DURATION_MS = 500


def inspect_wav(data: bytes) -> dict | None:
    if len(data) < 44:
        return None
    if data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    offset = 12
    channels = 0
    sample_rate = 0
    bits = 0
    data_bytes = 0
    found_fmt = False
    found_data = False
    length = len(data)
    while offset + 8 <= length:
        chunk_id = data[offset : offset + 4]
        size = int.from_bytes(data[offset + 4 : offset + 8], "little")
        next_offset = offset + 8 + size + (size % 2)
        if chunk_id == b"fmt " and size >= 16 and offset + 24 <= length:
            found_fmt = True
            channels = int.from_bytes(data[offset + 10 : offset + 12], "little")
            sample_rate = int.from_bytes(data[offset + 12 : offset + 16], "little")
            bits = int.from_bytes(data[offset + 22 : offset + 24], "little")
        elif chunk_id == b"data":
            found_data = True
            data_bytes = size
        if next_offset <= offset:
            break
        offset = next_offset
    byte_rate = sample_rate * channels * (bits // 8) if bits else 0
    duration_ms = (data_bytes * 1000) // byte_rate if byte_rate else 0
    valid_header = found_fmt and found_data and channels > 0 and sample_rate > 0
    return {
        "valid_header": valid_header,
        "channels": channels,
        "sample_rate": sample_rate,
        "bits_per_sample": bits,
        "data_bytes": data_bytes,
        "file_bytes": length,
        "duration_ms": duration_ms,
    }


def should_reject_wav_for_transcription(inspect: dict) -> bool:
    return (not inspect["valid_header"]) or inspect["duration_ms"] < MIN_TRANSCRIBABLE_WAV_DURATION_MS
