"""Isolated Mattermost repair for a missing human author display.

The service reads current profiles for author ids already stored on legacy
Objects. It does not fetch posts or move Mattermost sync state.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.mattermost.credentials import MattermostAccountStore, MattermostSyncSnapshot
from app.connectors.mattermost.errors import MattermostConnectorError, MattermostTransportError
from app.connectors.mattermost.normalize import author_human_display
from app.connectors.mattermost.transport import MattermostHttpTransport, MattermostTransport
from app.db.models import MattermostAccount, Object
from app.domain.object_visibility import is_object_hidden_from_active_reads

AUTHOR_REPAIR_SCAN_LIMIT = 100
AUTHOR_REPAIR_MAX_AUTHOR_IDS = 100


@dataclass(frozen=True)
class MattermostAuthorRepairSummary:
    candidates_scanned: int
    unique_author_ids: int
    provider_calls: int
    updated: int
    profile_missing: int
    no_human_display: int
    invalid_provenance: int
    hidden_skipped: int
    next_cursor: UUID | None
    exhausted: bool


class MattermostAuthorRepairService:
    def __init__(
        self,
        session: Session,
        encryption: CredentialEncryption,
        transport_factory: Callable[[MattermostSyncSnapshot], MattermostTransport] | None = None,
    ) -> None:
        self._session = session
        self._accounts = MattermostAccountStore(session, encryption)
        self._transport_factory = transport_factory

    def repair_author_display(
        self,
        user_id: UUID,
        account_id: UUID,
        *,
        cursor: UUID | None = None,
    ) -> MattermostAuthorRepairSummary:
        account = self._accounts.get_by_id_for_user(account_id, user_id)
        if account is None:
            raise MattermostConnectorError("mattermost account not found")

        display = Object.metadata_["author_display_name"].as_string()
        filters = [
            Object.user_id == user_id,
            Object.provider == "mattermost",
            Object.kind == "chat_message",
            Object.deleted_at.is_(None),
            Object.metadata_["account_id"].as_string() == str(account.id),
            Object.metadata_["server_url"].as_string() == account.server_url,
            display.is_(None) | (func.btrim(display) == ""),
        ]
        if cursor is not None:
            filters.append(Object.id > cursor)
        rows = list(
            self._session.scalars(
                select(Object).where(*filters).order_by(Object.id).limit(AUTHOR_REPAIR_SCAN_LIMIT)
            )
        )

        scanned = 0
        updated = 0
        profile_missing = 0
        no_human_display = 0
        invalid_provenance = 0
        hidden_skipped = 0
        next_cursor = cursor
        author_ids: list[str] = []
        seen_authors: set[str] = set()
        repairable: list[tuple[Object, str]] = []
        stopped_early = False

        for obj in rows:
            if is_object_hidden_from_active_reads(obj):
                hidden_skipped += 1
                scanned += 1
                next_cursor = obj.id
                continue
            author_id = _author_id(obj.metadata_ or {})
            if author_id is None:
                invalid_provenance += 1
                scanned += 1
                next_cursor = obj.id
                continue
            if author_id not in seen_authors and len(author_ids) >= AUTHOR_REPAIR_MAX_AUTHOR_IDS:
                stopped_early = True
                break
            if author_id not in seen_authors:
                seen_authors.add(author_id)
                author_ids.append(author_id)
            repairable.append((obj, author_id))
            scanned += 1
            next_cursor = obj.id

        profiles: dict[str, dict] = {}
        provider_calls = 0
        if author_ids:
            profiles = self._load_profiles(account, author_ids)
            provider_calls = 1

        for obj, author_id in repairable:
            profile = profiles.get(author_id)
            if profile is None:
                profile_missing += 1
                continue
            human = author_human_display(profile)
            if human is None:
                no_human_display += 1
                continue
            metadata = dict(obj.metadata_ or {})
            metadata["author_display_name"] = human
            obj.metadata_ = metadata
            updated += 1

        exhausted = not stopped_early and len(rows) < AUTHOR_REPAIR_SCAN_LIMIT
        return MattermostAuthorRepairSummary(
            candidates_scanned=scanned,
            unique_author_ids=len(author_ids),
            provider_calls=provider_calls,
            updated=updated,
            profile_missing=profile_missing,
            no_human_display=no_human_display,
            invalid_provenance=invalid_provenance,
            hidden_skipped=hidden_skipped,
            next_cursor=next_cursor,
            exhausted=exhausted,
        )

    def _load_profiles(
        self, account: MattermostAccount, author_ids: list[str]
    ) -> dict[str, dict]:
        snapshot = MattermostSyncSnapshot(
            account_id=account.id,
            user_id=account.user_id,
            server_url=account.server_url,
            normalized_server_url=account.server_url,
            remote_user_id=account.remote_user_id,
            username=account.username,
            access_token=self._accounts.get_access_token(account),
            sync_state=dict(account.sync_state or {}),
        )
        owned = self._transport_factory is None
        transport = (
            self._transport_factory(snapshot)
            if self._transport_factory is not None
            else MattermostHttpTransport(
                base_url=snapshot.normalized_server_url,
                access_token=snapshot.access_token,
            )
        )
        try:
            payload = transport.get_users_by_ids(author_ids)
        finally:
            if owned:
                transport.close()
        requested = set(author_ids)
        found: dict[str, dict] = {}
        if not isinstance(payload, list):
            raise MattermostTransportError("mattermost users response malformed")
        for profile in payload:
            if not isinstance(profile, dict):
                continue
            profile_id = profile.get("id")
            if not isinstance(profile_id, str) or profile_id not in requested:
                continue
            found.setdefault(profile_id, profile)
        return found


def _author_id(metadata: dict) -> str | None:
    value = metadata.get("author_user_id")
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
