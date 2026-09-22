# Current task — Final one-shot container startup hardening for Telegram rehearsal

## Context

Second authorized wrapper invocation reached the one-shot container launch and returned:

`REHEARSAL_REMOTE_BLOCKED=oneshot_failed`

No retry is authorized in this task.

Static review found a deterministic container-layout defect:

- production backend image has `WORKDIR /app`;
- application package is copied to `/app/app`;
- normal API/worker run from the canonical `/app` import root;
- remote wrapper mounts the streamed helper at
  `/opt/rehearsal/telegram_production_rehearsal.py`;
- it executes
  `python3 /opt/rehearsal/telegram_production_rehearsal.py`;
- direct script execution makes the script directory the primary Python import root instead of the canonical `/app` layout;
- therefore a top-level `from app...` failure can occur before helper `main()` and produce stderr-only exit, which the outer remote program maps to `oneshot_failed`.

The helper imports themselves were checked against exact production release
`8ad52f0653f9f90e1932c49532dc4f993ea1a9cc`; all named symbols exist.

## Goal

Make the one-shot container start from the exact production import layout and eliminate the next predictable provider-configuration false failure before another live attempt.

CODE/TEST ONLY. Do not execute production rehearsal.

## Required correction A — canonical import root

Change the isolated one-shot execution so the reviewed helper is mounted/executed from `/app`, for example:

- bind source helper to a unique read-only destination under `/app`, and
- execute `python3 /app/<rehearsal-helper>.py ...`.

Requirements:
- `sys.path[0]` must be `/app` for the helper process;
- do not overwrite any existing production module/file;
- use a unique rehearsal-only filename;
- mount remains read-only;
- no Docker socket;
- production checkout remains untouched;
- no second deploy.

Do not solve this by adding a broad arbitrary PYTHONPATH inherited by long-running services. The change is one-shot only.

## Required correction B — provider-config preflight

The rehearsal creates a separate synthetic user. Real provider resolution for that user can use the deployment OpenAI fallback when no per-user credential exists.

Before synthetic DB writes, the remote host/container path must prove only the boolean condition:

`OPENAI_API_KEY is non-empty in the one-shot production environment`

Requirements:
- never print the key or its length/hash/prefix;
- emit only a fixed sanitized block marker such as
  `REHEARSAL_REMOTE_BLOCKED=provider_config`
  if absent;
- do not copy/decrypt another user's credential;
- do not mutate credentials;
- long-running service env remains unchanged.

If deployment fallback is absent, STOP rather than allowing the synthetic user to fail deep inside a paid-provider handler.

## Required correction C — startup protocol

Add a one-shot startup marker emitted only after:
- Python successfully imports the helper and backend `app` package;
- live confirmation is present;
- long-running AI false values are present.

Example:
`REHEARSAL_STARTUP=PASS`

It must contain no secrets.

If startup/import fails before business execution, remote wrapper must still produce a fixed sanitized marker rather than raw stderr.

## Required regressions

At minimum prove:

1. one-shot helper destination is under `/app` and is read-only;
2. command executes the helper from `/app`;
3. generated/constructed one-shot environment does not modify long-running services;
4. deployment OpenAI fallback present => startup may proceed;
5. deployment OpenAI fallback absent => fixed `provider_config` block before fixture creation;
6. no credential value appears in stdout;
7. helper startup/import success emits `REHEARSAL_STARTUP=PASS`;
8. simulated import/startup failure becomes fixed sanitized marker;
9. all existing remote-program/Telegram-transport/failure-cleanup tests remain green;
10. fake local rehearsal remains green.

Prefer an execution-level test that reproduces the production image import layout (`/app/app` plus helper under its intended destination) instead of only inspecting command strings.

## Production facts to preserve

- production runtime/ref:
  `8ad52f0653f9f90e1932c49532dc4f993ea1a9cc`;
- Alembic 0046;
- long-running API/worker Telegram AI=false;
- no deploy/ref movement;
- no restart/recreate;
- no Telegram transport;
- no production env mutation.

## Authorization

AUTHORIZED:
- local wrapper/helper/tests correction;
- update PROJECT_STATE.md;
- commit/push canonical main.

NOT AUTHORIZED:
- live rehearsal;
- production SSH;
- deploy/ref movement;
- provider calls;
- synthetic DB writes;
- credential mutation/copy;
- Telegram calls.

## Required report

Return:
- commit SHA;
- exact import-root correction;
- provider-config boolean preflight;
- startup protocol;
- execution-level import-layout test;
- focused tests / py_compile / Ruff / diff-check;
- live rehearsal executed=0.

Final marker:

`TELEGRAM_REHEARSAL_ONESHOT_STARTUP_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
