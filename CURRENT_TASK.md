# Current task — HOLD

AH2-ROLL1 succeeded. Production backend now runs `943281190b386bbe22c4631709635883c950b459`. Alembic remains `0052`. The next action belongs to the human tester. Do not start another Executor slice from this HOLD.

## AH2-ROLL1 — schema-neutral backend rollout

- Release: `943281190b386bbe22c4631709635883c950b459`
- Rollback: `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`
- Production ref promotion: `aa3f475..9432811`, fast-forward, no force
- `origin/production` equals the release SHA
- Harness: `RELEASE_HEAD=943281190b386bbe22c4631709635883c950b459`; `HEALTH=PASS`; `ALEMBIC=0052`; `DB_CONTAINER_UNCHANGED=true`; `DB_VOLUME_UNCHANGED=true`; `ENV_FILE_UNCHANGED=true`; `API_RECREATED=true`; `WORKER_RECREATED=true`; `DEPLOYMENT=PASS`
- No migration. DB container, DB volume, and `.env` unchanged. Only `api` and `worker` were recreated.
- No client build or install. No model or external provider call. Rollback was not used.

## AH2-PER1

AH2-PER1 remains ARCHITECT SOURCE-ACCEPTED. Implementation `ece2bdfd8a3b80e8ab5fc438372408429253e7ac`, Executor HOLD `6efcb6b914a9526bd679211aa8690950e3c2a613`, acceptance ledger `943281190b386bbe22c4631709635883c950b459`.

## Manual real-product gate

Executor does not perform this gate.

Use an existing Task context and send exactly:

`Жду ответ от Оли Володько по черновику`

Expected first-turn behavior:

- no approval card;
- no Task mutation;
- no `waiting_on` relation yet;
- Secretary names `Ольга Володько` as a candidate;
- Secretary asks whether that is the intended Person;
- it does not claim that `Оли` and `Ольга` are already the same identity.

Do not continue to the confirmation turn until the first-turn behavior is reviewed.

## HOLD

Do not start Scheduled Activity integration, stale-eval maintenance, another remediation slice, a client rollout, or a further production change. Wait for Architect authorization after the manual AH2-PER1 behavior check.
