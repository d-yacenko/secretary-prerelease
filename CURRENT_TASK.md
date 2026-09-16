# Current task — Production Reliability Recovery

## Status

Production Reliability Recovery — ACTIVE.

- Development main: `5f2e7e8efafe8ab0270d0e24319e1ca2b9f5acf3`.
- Remote production release: `2c19512d11428920932ffec2267780699ae39d3b`.
- Actual healthy production runtime application: `6d69d936a7e5e08c427598bc8d659d3c7fe6b4ae`.
- Production Alembic: `0041 / 0041`.
- Yandex Transient Retry Latency Hotfix: CODE ACCEPTED / RELEASE ACCEPTED / NOT DEPLOYED.
- The first deployment attempt rolled back because recreated api/worker received a PostgreSQL password different from the unchanged DB container credential.
- Production baseline health was restored using the existing DB-container credential as a temporary api/worker runtime override.
- Persistent normal Compose recreate is NOT yet verified.
- File-backed production DB password transport is the selected corrective architecture, but no code for that correction has been accepted yet.

Production Reliability Recovery permits only narrow tasks explicitly issued by
Architect: runtime diagnosis, config correction, review, deploy, closure.
Do not start unrelated product work.

- Telegram Depth A3: CODE ACCEPTED / UNMERGED / NOT DEPLOYED.
  Accepted SHA: `4777c32deb055f5024f3dbced125b4dd6db97e85`.
- IMAP IDLE: NOT STARTED.
- Telegram A4: NOT STARTED.
