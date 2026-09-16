from fastapi import Request

from app.services.errors import ValidationError


async def read_bounded_body(request: Request, max_bytes: int, limit_message: str) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError:
            raise ValidationError(limit_message) from None
        if declared > max_bytes:
            raise ValidationError(limit_message)

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise ValidationError(limit_message)
        chunks.append(chunk)
    return b"".join(chunks)
