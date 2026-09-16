import logging

logger = logging.getLogger(__name__)


def log_transcription_telemetry(
    *,
    model: str,
    input_bytes: int,
    elapsed_ms: int,
    success: bool,
    filename: str | None = None,
    content_type: str | None = None,
    error_category: str | None = None,
) -> None:
    logger.info(
        "assistant_transcription model=%s input_bytes=%d elapsed_ms=%d "
        "success=%s filename=%s content_type=%s error_category=%s",
        model,
        input_bytes,
        elapsed_ms,
        success,
        filename or "",
        content_type or "",
        error_category or "",
    )
