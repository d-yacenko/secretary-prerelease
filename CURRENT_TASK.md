# Current task — Google Sync Resilience A

## Status

Google Sync Resilience A — PRODUCTION DEPLOY AUTHORIZED.

Record these facts:

- Development/main HEAD after Production Deploy Contract v2 merge:
  6be8616e849ae2979b386cd49e6b71ddc6d25427
- Authorized Google production release SHA:
  5cce4b57b14e0052a038acae1354a2821a2bb77b
- Authorized rollback SHA:
  2c19512d11428920932ffec2267780699ae39d3b
- Remote `production` ref must remain exactly:
  5cce4b57b14e0052a038acae1354a2821a2bb77b
- Expected production runtime before this deploy:
  2c19512d11428920932ffec2267780699ae39d3b
- Production Alembic expected for both release and rollback:
  0041
- Production Deploy Contract v2 is merged into `main` and is the mandatory normal deployment procedure.
- Normal deployment must run from the clean, current local `main` checkout using:
  `ops/production/deploy.py`
- Google Sync Resilience A production deployment is authorized only for the exact release SHA above, with the exact rollback SHA above and expected Alembic `0041`.
- Do not discover or probe alternative production hosts, paths, env files, Compose files, or repositories.
- Do not bypass SSH host-key verification or the committed production target contract.
- Do not use direct production SSH/Compose for the normal rollout.
- If the deployment harness blocks or fails, STOP and report; do not repair production configuration unless Architect issues a separate recovery/BREAK-GLASS task.
- The rollout is application-only and schema-neutral. Database container, database volume, and `/opt/secretary/.env` must remain unchanged.
- Recreate only `api` and `worker` through the deployment harness.
- Yandex Transient Retry Latency hotfix remains DEPLOYED / RUNTIME VERIFIED and must not regress.
- Yandex retryable transient runtime policy remains 10s -> 30s -> 60s, then bounded at 60s.
- The earlier file-backed PostgreSQL password correction is CANCELLED / NOT REQUIRED.
- Root cause of the prior deployment credential incident was implicit Compose environment resolution, not a different PostgreSQL password.
- Telegram Depth A1/A2 remain merged in development and not production deployed.
- Telegram Depth A3 remains CODE ACCEPTED / UNMERGED / NOT DEPLOYED at:
  4777c32deb055f5024f3dbced125b4dd6db97e85
- Telegram A3 remains HOLD and must not be modified during this phase.
- IMAP IDLE remains NOT STARTED.

Google Sync Resilience A permits only this exact production deployment, its verification, and narrow corrections explicitly issued by Architect.

Do not start Telegram, IMAP IDLE, migrations, or unrelated product work.
