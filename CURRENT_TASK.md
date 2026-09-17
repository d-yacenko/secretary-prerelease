# Current task — Google Sync Resilience A

## Status

Google Sync Resilience A — ACTIVE.

Record these facts:

- Development base:
  5f2e7e8efafe8ab0270d0e24319e1ca2b9f5acf3
- Development Alembic head:
  0043
- Production application release/runtime:
  2c19512d11428920932ffec2267780699ae39d3b
- Production Alembic:
  0041 / 0041
- Yandex Transient Retry Latency hotfix:
  DEPLOYED / RUNTIME VERIFIED
- Yandex retryable transient runtime policy:
  10s -> 30s -> 60s, then bounded at 60s.
- Production Compose must explicitly use:
  /opt/secretary/.env
- Explicit production PostgreSQL authentication using that env has been
  verified successfully.
- The earlier file-backed PostgreSQL password correction is CANCELLED /
  NOT REQUIRED.
- Root cause of the deployment credential incident was implicit Compose
  environment resolution, not a different PostgreSQL password.
- Google Gmail and Google Calendar retryable recurring sync can currently
  exhaust the generic retry path and fall into the long recurring failed
  cooldown.
- Google Sync Resilience A is explicitly authorized to correct that behavior,
  including bounded transient retry and provider Retry-After handling.
- No Google production deployment is authorized by this ledger task.
- Telegram Depth A1/A2 remain merged in development and not production
  deployed.
- Telegram Depth A3:
  CODE ACCEPTED / UNMERGED / NOT DEPLOYED
  SHA:
  4777c32deb055f5024f3dbced125b4dd6db97e85
- Telegram A3 remains HOLD and must not be modified during this phase.
- IMAP IDLE:
  NOT STARTED.

Google Sync Resilience A permits only narrow implementation, tests, review,
release preparation and deployment steps explicitly issued by Architect.

Do not start Telegram, IMAP IDLE or unrelated product work.
