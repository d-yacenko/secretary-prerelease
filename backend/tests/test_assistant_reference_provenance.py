from datetime import UTC, datetime
from uuid import uuid4

from app.api.assistant import AssistantReferenceOut
from app.db.models import Object
from app.services.assistant_service import AssistantService, _reference_provider
from app.services.object_primary_date import (
    object_primary_search_datetime,
    primary_search_datetime_from_object_snapshot,
)


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


def test_snapshot_primary_date_matches_object_rule() -> None:
    occurred = datetime(2026, 3, 4, 15, 0, tzinfo=UTC)
    updated = datetime(2026, 9, 2, tzinfo=UTC)
    row = _object(kind="email", provider="google", occurred_at=occurred, updated_at=updated)
    snapshot = {
        "kind": "email",
        "occurred_at": "2026-03-04T15:00:00+00:00",
        "updated_at": "2026-09-02T00:00:00+00:00",
        "metadata": {},
    }
    assert primary_search_datetime_from_object_snapshot(snapshot) == object_primary_search_datetime(
        row
    )


def test_task_snapshot_prefers_due_at() -> None:
    due = datetime(2026, 4, 1, 9, 0, tzinfo=UTC)
    when = primary_search_datetime_from_object_snapshot(
        {
            "kind": "task",
            "due_at": "2026-04-01T09:00:00Z",
            "updated_at": "2026-04-02T09:00:00Z",
            "metadata": {},
        }
    )
    assert when == due


def test_file_snapshot_prefers_metadata_modified_at() -> None:
    when = primary_search_datetime_from_object_snapshot(
        {
            "kind": "file",
            "metadata": {"modified_at": "2026-05-01T10:00:00+00:00"},
            "occurred_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-06-01T00:00:00+00:00",
        }
    )
    assert when == datetime(2026, 5, 1, 10, tzinfo=UTC)


def test_serialize_references_uses_get_object_snapshot_only(monkeypatch) -> None:
    object_id = uuid4()

    def _refuse_session():
        raise AssertionError("reference serialization opened a second database session")

    monkeypatch.setattr("app.services.assistant_service.SessionLocal", _refuse_session)

    def _get_object(_user_id, tool_name, arguments):
        assert tool_name == "get_object"
        assert arguments["object_id"] == str(object_id)
        return type(
            "Result",
            (),
            {
                "success": True,
                "output": {
                    "object": {
                        "id": str(object_id),
                        "title": "Hello",
                        "kind": "email",
                        "canonical_uri": "https://user:secret@example.com/ref",
                        "provider": " yandex ",
                        "occurred_at": "2026-03-04T15:00:00+00:00",
                        "updated_at": "2026-09-02T00:00:00+00:00",
                        "metadata": {},
                    }
                },
            },
        )()

    monkeypatch.setattr("app.services.assistant_service.run_assistant_tool", _get_object)
    service = AssistantService(uuid4(), provider=None)  # type: ignore[arg-type]
    references = service._serialize_references([object_id])
    assert len(references) == 1
    ref = references[0]
    assert ref.object_id == object_id
    assert ref.title == "Hello"
    assert ref.kind == "email"
    assert ref.canonical_uri == "https://example.com/ref"
    assert ref.provider == "yandex"
    assert ref.primary_at == datetime(2026, 3, 4, 15, 0, tzinfo=UTC)
    payload = AssistantReferenceOut(
        object_id=ref.object_id,
        title=ref.title,
        kind=ref.kind,
        canonical_uri=ref.canonical_uri,
        provider=ref.provider,
        primary_at=ref.primary_at,
    ).model_dump(mode="json")
    assert payload["provider"] == "yandex"
    assert payload["primary_at"].startswith("2026-03-04T15:00:00")


def test_blank_provider_is_omitted() -> None:
    assert _reference_provider("  ") is None
    assert _reference_provider(None) is None
    assert (
        primary_search_datetime_from_object_snapshot(
            {"kind": "note", "provider": "  ", "metadata": {}}
        )
        is None
    )
