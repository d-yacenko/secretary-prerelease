import re
from pathlib import Path

from fastapi import UploadFile

from app.assistant.transcription_constants import (
    ALLOWED_TRANSCRIPTION_SUFFIXES,
    AUDIO_EMPTY,
    AUDIO_TOO_LARGE,
    MAX_TRANSCRIPTION_AUDIO_BYTES,
)
from app.services.errors import ValidationError


def sanitize_transcription_filename(filename: str | None) -> str:
    raw = Path(filename or "audio.bin").name
    safe = re.sub(r"[^\w.\-]+", "_", raw).strip("._")
    return safe[:200] if safe else "audio.bin"


async def read_bounded_transcription_audio(upload: UploadFile) -> tuple[bytes, str]:
    filename = sanitize_transcription_filename(upload.filename)
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_TRANSCRIPTION_SUFFIXES:
        raise ValidationError(f"unsupported audio format: {suffix or '(none)'}")

    max_read_bytes = MAX_TRANSCRIPTION_AUDIO_BYTES + 1
    audio_bytes = await upload.read(max_read_bytes)
    if len(audio_bytes) > MAX_TRANSCRIPTION_AUDIO_BYTES:
        raise ValidationError(AUDIO_TOO_LARGE)
    if not audio_bytes:
        raise ValidationError(AUDIO_EMPTY)

    return audio_bytes, filename
