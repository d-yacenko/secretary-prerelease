# Project state

- Active development repo and canonical production repo: `d-yacenko/secretary-prerelease`.
- Development main: `5f2e7e8efafe8ab0270d0e24319e1ca2b9f5acf3`.
- Remote production release: `2c19512d11428920932ffec2267780699ae39d3b`.
- Actual production runtime app: `6d69d936a7e5e08c427598bc8d659d3c7fe6b4ae`.
- Production Alembic: `0041 / 0041`.
- Production currently healthy after rollback recovery.
- Yandex retry-latency hotfix accepted but not successfully deployed.
- PostgreSQL credential drift diagnosed between normal Compose resolution and the existing DB container.
- DB container/data/password itself was not changed.
- Telegram A1/A2 remain not production deployed.
- Telegram A3 code accepted/unmerged/not deployed at `4777c32deb055f5024f3dbced125b4dd6db97e85`.
- IMAP IDLE not started.
