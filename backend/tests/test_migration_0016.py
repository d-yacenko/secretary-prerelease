import importlib.util
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.db.models import Object, User

_MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "alembic/versions/0016_object_occurred_at_retrieval_indexes.py"
)
_spec = importlib.util.spec_from_file_location("migration_0016", _MIGRATION_PATH)
_migration = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_migration)


@pytest.fixture
def migration_user_id(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="Migration 0016 user"))
    db_session.flush()
    return user_id


def _insert_email_row(
    db_session,
    user_id: uuid.UUID,
    timestamp_value: str,
) -> uuid.UUID:
    object_id = uuid.uuid4()
    db_session.add(
        Object(
            id=object_id,
            user_id=user_id,
            kind="email",
            title="migration backfill email",
            origin="source",
            state="confirmed",
            provider="gmail",
            metadata_={"timestamp": timestamp_value},
        )
    )
    db_session.flush()
    return object_id


def test_migration_0016_parse_metadata_timestamp_malformed() -> None:
    parser = _migration._parse_metadata_timestamp
    assert parser("2024-99-99") is None
    assert parser("nonsense") is None
    assert parser("") is None
    assert parser("   ") is None
    assert parser(None) is None


def test_migration_0016_email_backfill_malformed_timestamps(db_session, migration_user_id) -> None:
    malformed_ids = [
        _insert_email_row(db_session, migration_user_id, "2024-99-99"),
        _insert_email_row(db_session, migration_user_id, "nonsense"),
        _insert_email_row(db_session, migration_user_id, ""),
    ]
    valid_id = _insert_email_row(
        db_session,
        migration_user_id,
        "2024-06-15T10:30:00+00:00",
    )

    _migration._backfill_email_occurred_at(db_session.connection())

    for object_id in malformed_ids:
        obj = db_session.get(Object, object_id)
        assert obj is not None
        assert obj.occurred_at is None

    valid_obj = db_session.get(Object, valid_id)
    assert valid_obj is not None
    assert valid_obj.occurred_at == datetime(2024, 6, 15, 10, 30, tzinfo=UTC)


def test_migration_0016_backfill_terminates_with_many_malformed(
    db_session, migration_user_id
) -> None:
    valid_early_id = _insert_email_row(
        db_session,
        migration_user_id,
        "2024-01-01T00:00:00+00:00",
    )
    malformed_ids = [
        _insert_email_row(db_session, migration_user_id, "bad-timestamp")
        for _ in range(600)
    ]
    valid_late_id = _insert_email_row(
        db_session,
        migration_user_id,
        "2024-02-01T00:00:00+00:00",
    )

    _migration._backfill_email_occurred_at(db_session.connection())

    for object_id in malformed_ids:
        obj = db_session.get(Object, object_id)
        assert obj is not None
        assert obj.occurred_at is None

    valid_early = db_session.get(Object, valid_early_id)
    valid_late = db_session.get(Object, valid_late_id)
    assert valid_early is not None
    assert valid_late is not None
    assert valid_early.occurred_at == datetime(2024, 1, 1, tzinfo=UTC)
    assert valid_late.occurred_at == datetime(2024, 2, 1, tzinfo=UTC)
