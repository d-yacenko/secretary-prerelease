"""Provider-neutral descriptors for communication media child Objects."""

from __future__ import annotations

from dataclasses import dataclass

MEDIA_KINDS = frozenset({"voice", "audio", "document", "photo", "video", "other"})
MAX_MEDIA_DESCRIPTORS = 20
MAX_MEDIA_TEXT = 200
_PROVENANCE_KEYS = frozenset(
    {
        "account_id",
        "peer_id",
        "message_id",
        "server_url",
        "channel_id",
        "post_id",
        "chat_id",
        "tenant_id",
        "teams_user_id",
        "content_reference",
        "media_category",
    }
)
_UNSAFE_MARKERS = ("access_token", "refresh_token", "sig=", "signature=", "tempauth", "bearer ")


@dataclass(frozen=True)
class CommunicationMediaDescriptor:
    provider: str
    descriptor_key: str
    media_kind: str
    provider_media_id: str | None = None
    filename: str | None = None
    mime_type: str | None = None
    size: int | None = None
    duration_seconds: int | None = None
    provenance: dict[str, str] | None = None


def stored_media_descriptors(descriptors: list[CommunicationMediaDescriptor]) -> list[dict]:
    stored: list[dict] = []
    seen: set[str] = set()
    for descriptor in descriptors[:MAX_MEDIA_DESCRIPTORS]:
        safe = safe_descriptor(descriptor)
        if safe is None or safe.descriptor_key in seen:
            continue
        seen.add(safe.descriptor_key)
        stored.append(_stored_dict(safe))
    return stored


def parse_stored_descriptor(provider: str, raw: object) -> CommunicationMediaDescriptor | None:
    if not isinstance(raw, dict):
        return None
    provenance = raw.get("provenance")
    return safe_descriptor(
        CommunicationMediaDescriptor(
            provider=provider,
            descriptor_key=str(raw.get("descriptor_key") or ""),
            media_kind=str(raw.get("media_kind") or ""),
            provider_media_id=_text(raw.get("provider_media_id")),
            filename=_text(raw.get("filename")),
            mime_type=_text(raw.get("mime_type")),
            size=_size(raw.get("size")),
            duration_seconds=_duration(raw.get("duration_seconds")),
            provenance=provenance if isinstance(provenance, dict) else None,
        )
    )


def safe_descriptor(descriptor: CommunicationMediaDescriptor) -> CommunicationMediaDescriptor | None:
    provider = _text(descriptor.provider)
    key = _text(descriptor.descriptor_key)
    kind = _text(descriptor.media_kind)
    if provider is None or key is None or kind not in MEDIA_KINDS:
        return None
    if _unsafe(provider) or _unsafe(key):
        return None
    media_id = _text(descriptor.provider_media_id)
    if media_id is not None and _unsafe(media_id):
        media_id = None
    filename = _text(descriptor.filename)
    mime_type = _text(descriptor.mime_type)
    provenance = _safe_provenance(descriptor.provenance)
    return CommunicationMediaDescriptor(
        provider=provider,
        descriptor_key=key,
        media_kind=kind,
        provider_media_id=media_id,
        filename=filename,
        mime_type=mime_type,
        size=_size(descriptor.size),
        duration_seconds=_duration(descriptor.duration_seconds),
        provenance=provenance or None,
    )


def _stored_dict(descriptor: CommunicationMediaDescriptor) -> dict:
    payload: dict = {
        "descriptor_key": descriptor.descriptor_key,
        "media_kind": descriptor.media_kind,
    }
    if descriptor.provider_media_id is not None:
        payload["provider_media_id"] = descriptor.provider_media_id
    if descriptor.filename is not None:
        payload["filename"] = descriptor.filename
    if descriptor.mime_type is not None:
        payload["mime_type"] = descriptor.mime_type
    if descriptor.size is not None:
        payload["size"] = descriptor.size
    if descriptor.duration_seconds is not None:
        payload["duration_seconds"] = descriptor.duration_seconds
    if descriptor.provenance:
        payload["provenance"] = descriptor.provenance
    return payload


def _safe_provenance(raw: dict | None) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    safe: dict[str, str] = {}
    for key in sorted(_PROVENANCE_KEYS):
        if key not in raw:
            continue
        value = _text(raw.get(key))
        if value is None or _unsafe(value):
            continue
        safe[key] = value
    return safe


def _text(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:MAX_MEDIA_TEXT]


def _size(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or value > 2_000_000_000:
        return None
    return value


def _duration(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or value > 86_400:
        return None
    return value


def _unsafe(value: str) -> bool:
    folded = value.casefold()
    return any(marker in folded for marker in _UNSAFE_MARKERS) or "?" in value or "#" in value
