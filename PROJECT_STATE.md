# Project state

- Active development repository: `d-yacenko/secretary-prerelease`.
- Production canonical Git repository: `d-yacenko/secretary-prerelease`.
- Yandex Sync Resilience A: DEPLOYED / AWAITING ARCHITECT REVIEW.
- Deployed application SHA:
  `6d69d936a7e5e08c427598bc8d659d3c7fe6b4ae`.
- PostgreSQL data and container were preserved during rollout.
- Pre-deploy backup was created and verified.
- Only api and worker were rebuilt/recreated.
- Production health: PASS.
- Alembic: `0041 / 0041`.
- Yandex Mail and Calendar fresh post-deploy sync: PASS.
- Failed-source rearm: 3600 seconds.
- Telegram Depth: not started.
