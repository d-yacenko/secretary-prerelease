# Current task — Executor bootstrap standardization recorded

## Status

The repeated Git/SSH environment churn has been converted from phase-specific troubleshooting into a persistent Executor bootstrap invariant.

Canonical bootstrap policy is now recorded in:

- `AGENTS.md`
- `docs/executor_bootstrap.md`
- `docs/deploy.md`
- `PROJECT_STATE.md`
- `secretary_architect_context_encrypted.md` (encrypted recovery context, password supplied by Architect)

## Canonical bootstrap

Before every Executor work cycle:

1. Use only the canonical repository:
   `https://github.com/d-yacenko/secretary-prerelease.git`
2. If the current checkout is wrong-origin, unrelated, dirty, or contains unknown local state, do not repair/clean/repoint it; leave it untouched and use a fresh temporary canonical clone.
3. Fetch/read the active authorization from canonical `origin/main`.
4. Verify exact task-authorized SHAs/refs.
5. For production/runtime work, use the canonical target/pinned host-key contract and the pre-existing Executor/workstation SSH credential integration.
6. Do not create/copy/request new production private-key material as a workaround.
7. Git/worktree/SSH readiness is plumbing and occurs in the same work cycle as the actual task; do not create separate product phases for each bootstrap stop.
8. If bootstrap cannot be established, emit one concise sanitized `EXECUTOR_BOOTSTRAP_BLOCKED=<reason>` and STOP.
9. A local/bootstrap/pre-SSH stop is not a product/provider result and does not consume a one-shot live/provider authorization before its defined start marker.

## Current M4 position

- Production runtime/ref remains exact `23fa07df213d5a70a6dc1d3c8b32af39228107eb`.
- M4AK manual Sync produced provider-neutral 503, while account/group discovery remained usable.
- M4AM2R2 provider-sequence diagnostic was executed exactly once but stopped structurally at `STAGE_1_DB_SESSION` with `TELEGRAM_NETWORK_CALLS=0`.
- M4AN1 zero-provider structural localization later failed before authenticated SSH because the then-current Executor environment lacked the previously available SSH credential path.
- These Executor-environment failures are not Telegram/auth conclusions.

## Runtime authorization

This task records process/context only.

It does NOT authorize:
- production SSH;
- M4AN retry;
- M4AM retry;
- Telegram provider calls;
- Secretary Sync retry;
- re-login;
- Apply Scope;
- DB/production mutation.

The next runtime task, when explicitly authorized, should use the canonical bootstrap and then resume the zero-provider structural localization of the broad `STAGE_1_DB_SESSION` without creating intermediate Git/SSH phases.

Final marker for this documentation task:
`EXECUTOR_BOOTSTRAP_STANDARDIZED`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
