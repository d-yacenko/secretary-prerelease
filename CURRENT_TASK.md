# Current task — HOLD

REL1-R1 exact production migration and backend rollout succeeded.

- Launch `main`: `5989492a8ece4f3c0467a8808bb36b1092c6e761`
- Accepted harness: `ed287ed115dda037f94b509b79f76c8ffba2e2ea`
- Accepted recovery corrective: `a7dfe35e68ea6c2af5328cc00c6724b1c0c5963d`
- Production backend/source: `6f802d6959aca40758376a83d5bdfcbbd77fc537`
- Production branch: `6f802d6959aca40758376a83d5bdfcbbd77fc537`
- Rollback, unused: `2314bf72101fbd83d50a7b264154d73740e28db1`
- Alembic: `0054 / 0054`
- Installed client still: `2314bf72101fbd83d50a7b264154d73740e28db1`

`refs/heads/production` fast-forwarded from the rollback SHA to the release SHA. The harness reported `PERSON_ROLE_MIGRATION_DEPLOYMENT=PASS`, `ALEMBIC=0054`, unchanged DB container, DB volume, and `.env`, and recreated `api` and `worker`. Role schema checks passed, including widths 120/360 and 200/600. Both role tables had zero rows before the release runtime started. The health gate passed before success. No role rows were intentionally created. No model or provider call.

The next controlled rollout stage is an exact-release Linux client build/install for human REL1A acceptance. Do not perform that client stage from this HOLD.
