from datetime import UTC, datetime
from uuid import uuid4

from app.api.assistant import AssistantReferenceOut
from app.db.models import Object
from app.services.assistant_service import AssistantReference, _reference_provenance
from app.services.object_primary_date import object_primary_search_datetime


def _object(**kwargs) -> Object:
    now = datetime(2026, 9, 2, tzinfo=UTC)
    values = {
        "id": uuid4(),
        "user_id": uuid4(),
        "kind": "note",
        "title": "Note",
        "origin": "user",
        "state": "active",
        "created_at": now,
        "updated_at": now,
        "metadata_": {},
    }
    values.update(kwargs)
    return Object(**values)


def test_email_provenance_uses_provider_and_occurred_at() -> None:
    occurred = datetime(2026, 3, 4, 15, 0, tzinfo=UTC)
    row = _object(kind="email", provider=" google ", occurred_at=occurred, title="Hello")
    user_id = row.user_id

    class _Rows:
        def all(self):
            return [row]

    class _Session:
        def scalars(self, _statement):
            return _Rows()

        def close(self):
            return None

    import app.services.assistant_service as service

    original = service.SessionLocal
    service.SessionLocal = lambda: _Session()
    try:
        found = _reference_provenance(user_id, [row.id])
    finally:
        service.SessionLocal = original

    assert found[row.id][0] == "google"
    assert found[row.id][1] == object_primary_search_datetime(row)
    assert found[row.id][1] == occurred


def test_task_primary_at_prefers_due_at() -> None:
    due = datetime(2026, 4, 1, 9, 0, tzinfo=UTC)
    updated = datetime(2026, 4, 2, 9, 0, tzinfo=UTC)
    row = _object(kind="task", due_at=due, updated_at=updated)
    assert object_primary_search_datetime(row) == due


def test_reference_out_keeps_identity_and_adds_provenance() -> None:
    when = datetime(2026, 3, 4, 15, 0, tzinfo=UTC)
    ref = AssistantReference(
        object_id=uuid4(),
        title="Hello",
        kind="email",
        canonical_uri="https://example.com/ref",
        provider="yandex",
        primary_at=when,
    )
    payload = AssistantReferenceOut(
        object_id=ref.object_id,
        title=ref.title,
        kind=ref.kind,
        canonical_uri=ref.canonical_uri,
        provider=ref.provider,
        primary_at=ref.primary_at,
    ).model_dump(mode="json")
    assert payload["title"] == "Hello"
    assert payload["kind"] == "email"
    assert payload["canonical_uri"] == "https://example.com/ref"
    assert payload["provider"] == "yandex"
    assert payload["primary_at"].startswith("2026-03-04T15:00:00")


def test_blank_provider_is_omitted() -> None:
    row = _object(provider="  ")
    user_id = row.user_id

    class _Rows:
        def all(self):
            return [row]

    class _Session:
        def scalars(self, _statement):
            return _Rows()

        def close(self):
            return None

    import app.services.assistant_service as service

    original = service.SessionLocal
    service.SessionLocal = lambda: _Session()
    try:
        found = _reference_provenance(user_id, [row.id])
    finally:
        service.SessionLocal = original
    assert found[row.id] == (None, object_primary_search_datetime(row))
