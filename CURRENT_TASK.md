# CURRENT_TASK

HOLD

## REL1D-HG1.5.1 — source ready for Architect review

Implementation: `547169d5ebde1b52860eb554a6fc78c3d5be8181`.

HG1.5 `8f3c748a805956eeed137d67ee1c75b81e49fb25` and HG1.5.1 are ready for Architect source review.

Approve-time mention revalidation now calls `evidence_for` once for the unique selected mention-backed names. A batch without those rows does not scan.

Production, backend runtime, and the installed Linux client remain `67e8f14ba7ced8408086bd1ea57c2fa9f7b049dc`.

Alembic remains `0054 / 0054`.

Human REL1D acceptance remains paused.

Do not rollout and do not start another slice.
