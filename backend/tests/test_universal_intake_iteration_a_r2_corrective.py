"""Universal Intake Iteration A-R2 regressions."""

import uuid

from app.db.models import Object
from app.resources.constants import PROVIDER_WEB
from app.users.bootstrap import BOOTSTRAP_USER_ID


def test_inbox_recent_source_objects_include_origin(auth_client, db_session) -> None:
    note = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="note",
        title="Origin note",
        body="note body",
        origin="user",
        state="confirmed",
    )
    web = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="web_page",
        title="Origin web",
        origin="explicit",
        state="observed",
        provider=PROVIDER_WEB,
        external_id=f"https://example.org/origin-{uuid.uuid4().hex}",
        canonical_uri="https://example.org/origin",
    )
    email = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="email",
        title="Origin email",
        origin="source",
        state="observed",
        provider="gmail",
        external_id=f"gmail-{uuid.uuid4().hex}",
    )
    db_session.add_all([note, web, email])
    db_session.commit()

    response = auth_client.get("/inbox")
    assert response.status_code == 200
    rows = response.json()["recent_source_objects"]
    by_title = {row["title"]: row for row in rows}

    assert by_title["Origin note"]["origin"] == "user"
    assert by_title["Origin web"]["origin"] == "explicit"
    assert by_title["Origin email"]["origin"] == "source"
