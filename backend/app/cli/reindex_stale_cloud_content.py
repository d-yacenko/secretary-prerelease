"""Bounded maintenance: re-extract explicit cloud objects on stale extraction version."""

import argparse
import sys
from uuid import UUID

from sqlalchemy import select

from app.connectors.google.constants import GOOGLE_DRIVE_PROVIDER
from app.connectors.yandex.constants import YANDEX_DISK_PROVIDER
from app.content_extraction.constants import EXTRACTION_VERSION
from app.content_extraction.content_invalidation import invalidate_object_content_immediately
from app.content_extraction.metadata_keys import CONTENT_EXTRACTION_STATUS
from app.content_extraction.revision import metadata_extraction_version
from app.db.models import Object
from app.db.session import SessionLocal
from app.services.pipeline_enqueue import enqueue_extract_explicit_resource_content
from app.users.bootstrap import BOOTSTRAP_USER_ID

CLOUD_PROVIDERS = (GOOGLE_DRIVE_PROVIDER, YANDEX_DISK_PROVIDER)
MAX_AUTO_REINDEX = 50


def _is_stale_eligible(obj: Object) -> bool:
    if obj.provider not in CLOUD_PROVIDERS:
        return False
    metadata = obj.metadata_ or {}
    if not metadata.get("content_revision"):
        return False
    return metadata_extraction_version(metadata) != EXTRACTION_VERSION


def _stale_objects(session, user_id: UUID) -> list[Object]:
    objects = session.scalars(
        select(Object).where(
            Object.user_id == user_id,
            Object.provider.in_(CLOUD_PROVIDERS),
        )
    ).all()
    return [obj for obj in objects if _is_stale_eligible(obj)]


def run(user_id: UUID, dry_run: bool = False) -> int:
    session = SessionLocal()
    try:
        stale = _stale_objects(session, user_id)
        count = len(stale)
        print(f"stale_eligible_count={count}")
        if count == 0:
            return 0
        if count > MAX_AUTO_REINDEX:
            print(
                f"STOP: stale count {count} exceeds max {MAX_AUTO_REINDEX}; "
                "report before mass reindex",
                file=sys.stderr,
            )
            return 2
        if dry_run:
            for obj in stale:
                print(f"would_reindex object_id={obj.id} title={obj.title!r}")
            return 0

        jobs_enqueued = 0
        for obj in stale:
            invalidate_object_content_immediately(session, obj)
            revision = (obj.metadata_ or {}).get("content_revision")
            enqueue_extract_explicit_resource_content(
                session,
                obj.id,
                user_id,
                revision,
                EXTRACTION_VERSION,
            )
            metadata = dict(obj.metadata_ or {})
            metadata[CONTENT_EXTRACTION_STATUS] = "pending"
            obj.metadata_ = metadata
            jobs_enqueued += 1
            print(f"reindex_enqueued object_id={obj.id} title={obj.title!r}")
        session.commit()
        print(f"jobs_enqueued={jobs_enqueued}")
        return 0
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reindex stale explicit cloud content")
    parser.add_argument("--user-id", default=str(BOOTSTRAP_USER_ID))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    return run(UUID(str(args.user_id)), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
