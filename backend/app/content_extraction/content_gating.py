"""Current-content gating for cloud explicit resources."""

from app.connectors.google.constants import GOOGLE_DRIVE_PROVIDER
from app.connectors.yandex.constants import YANDEX_DISK_PROVIDER
from app.content_extraction.constants import EXTRACTION_VERSION
from app.content_extraction.metadata_keys import CONTENT_EXTRACTION_STATUS, STATUS_READY
from app.db.models import Object, Representation

CLOUD_EXPLICIT_PROVIDERS = frozenset({GOOGLE_DRIVE_PROVIDER, YANDEX_DISK_PROVIDER})


def object_has_current_indexed_content(obj: Object) -> bool:
    provider = obj.provider
    if provider not in CLOUD_EXPLICIT_PROVIDERS:
        return True
    metadata = obj.metadata_ or {}
    if metadata.get(CONTENT_EXTRACTION_STATUS) != STATUS_READY:
        return False
    if metadata.get("content_extraction_version") != EXTRACTION_VERSION:
        return False
    return bool(metadata.get("content_revision"))


def filter_current_representations(obj: Object, reps: list[Representation]) -> list[Representation]:
    if object_has_current_indexed_content(obj):
        return reps
    return []
