from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Object
from app.domain.labels import KIND_LABEL
from app.domain.object_visibility import object_is_active
from app.services.provenance import REJECTED_STATE

MAX_SEARCH_FACETS_PER_DIMENSION = 64


class SearchFacetService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id

    def _visibility_filter(self):
        return (
            Object.user_id == self._user_id,
            Object.state != REJECTED_STATE,
            object_is_active(),
            Object.kind != KIND_LABEL,
        )

    def facets(self) -> dict[str, list[dict[str, object]]]:
        base = self._visibility_filter()
        kind_rows = self._session.execute(
            select(Object.kind, func.count())
            .where(*base)
            .group_by(Object.kind)
            .order_by(func.count().desc(), Object.kind.asc())
            .limit(MAX_SEARCH_FACETS_PER_DIMENSION)
        ).all()
        provider_rows = self._session.execute(
            select(Object.provider, func.count())
            .where(
                *base,
                Object.provider.is_not(None),
                Object.provider != "",
            )
            .group_by(Object.provider)
            .order_by(func.count().desc(), Object.provider.asc())
            .limit(MAX_SEARCH_FACETS_PER_DIMENSION)
        ).all()
        return {
            "kinds": [
                {"value": kind, "count": int(count)} for kind, count in kind_rows
            ],
            "providers": [
                {"value": provider, "count": int(count)}
                for provider, count in provider_rows
            ],
        }
