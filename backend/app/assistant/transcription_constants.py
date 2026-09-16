MAX_TRANSCRIPTION_AUDIO_BYTES = 10 * 1024 * 1024

ALLOWED_TRANSCRIPTION_SUFFIXES = frozenset(
    {
        ".m4a",
        ".wav",
        ".webm",
        ".mp3",
        ".ogg",
        ".mp4",
        ".mpeg",
        ".mpga",
        ".oga",
        ".flac",
    }
)

AUDIO_TOO_LARGE = "audio exceeds size limit"
AUDIO_EMPTY = "audio is empty"

TRANSCRIPTION_PROVIDER_NOT_CONFIGURED = "transcription_provider_not_configured"
TRANSCRIPTION_PROVIDER_FAILED = "transcription_provider_failed"
TRANSCRIPTION_AUDIO_INVALID = "transcription_audio_invalid"
TRANSCRIPTION_UNRECOGNIZED = "transcription_unrecognized"

TRANSCRIPTION_PROVIDER_NOT_CONFIGURED_MESSAGE = (
    "Провайдер распознавания речи не настроен."
)
TRANSCRIPTION_PROVIDER_FAILED_MESSAGE = (
    "Не удалось распознать речь. Попробуйте ещё раз."
)
TRANSCRIPTION_AUDIO_INVALID_MESSAGE = (
    "Запись слишком короткая или не распознана. Повторите фразу."
)
TRANSCRIPTION_UNRECOGNIZED_MESSAGE = (
    "Речь не распознана. Повторите фразу."
)
