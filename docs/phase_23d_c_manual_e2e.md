# PHASE 23D-C — deployment evidence & manual E2E readiness

Status: **ready for manual testing** (manual scenarios A–H **NOT YET RUN**).

## Integration

| Item | Value |
|------|-------|
| `origin/main` SHA | `b30b95e152656fbbec3e7a3028216ae05ad35659` |
| Branch | `main` fast-forward, no squash/rebase |

## VDS verification (`/opt/secretary`)

Captured 2026-08-30 from `root@185.233.107.66`.

| Check | Result |
|-------|--------|
| `git rev-parse HEAD` | `b30b95e152656fbbec3e7a3028216ae05ad35659` |
| Branch | `main` |
| Tracked modifications | none (`git status --porcelain` empty) |
| Deployed | 2026-08-30 |

## Database migration

| Check | Result |
|-------|--------|
| Alembic current | `0018 (head)` |
| Alembic heads | `0018 (head)` |
| `pending_action_plans` migration | applied (`0018_pending_action_plans.py`, revision `0018`) |

## Backend health

| Check | Result |
|-------|--------|
| `curl -sS http://127.0.0.1:18080/health` | `{"status":"ok"}` |
| `infra-api-1` | Up |
| `infra-db-1` | Up (healthy) |
| `infra-worker-1` | Up |

API bind: `127.0.0.1:18080` (localhost on VDS host only).

## Production smoke checks (pass/fail only)

Ephemeral operator token issued and revoked; no bearer tokens, personal content, or transcripts recorded.

| Check | Pass |
|-------|------|
| Authentication (`GET /me`) | yes |
| Read-only Assistant (`POST /assistant/message`) | yes |
| Search API (`GET /search`) | yes |
| Object API (`GET /objects/{id}` responds) | yes |
| `/assistant/transcribe` reachable (`POST` without body → 422) | yes |

No mutating Assistant smoke data created.

## Client build proof (commit `b30b95e`, not re-run for this doc step)

Executed earlier against accepted `main` / `b30b95e`.

| Check | Result |
|-------|--------|
| `flutter analyze` | PASS (no issues) |
| `flutter test` | PASS (112 tests) |
| `flutter build apk --debug` | PASS |
| APK local path | `/home/d.yacenko/work/secretary/client/build/app/outputs/flutter-apk/app-debug.apk` |
| APK SHA-256 | `bc07649bf70cb03791ae20062802eb68b857261e99cb84446288c445f947763f` |
| `minSdk` in `client/android/app/build.gradle.kts` | `23` |

APK binary not committed. Configure server URL and bearer token in app setup (existing flow).

## Manual E2E (first run — 2026-08-30)

| Scenario | Result |
|----------|--------|
| Read-only Assistant | **PASS** |
| Create task → proposal → Approve → confirmed task | **PASS** |
| Reject → no execution | **PASS** |
| Double Approve protection | **PASS** |
| Prompt-injection sanity | **PASS** |
| Retrieval + ambiguity clarification | **PASS** |
| Unknown/unavailable operation | **PASS** — Secretary correctly reported task deletion is not an available Agent operation |
| Voice input | **FAIL** — Linux: «Voice recording could not start.»; Android: microphone control not practically visible/reachable in compact UI |
| Mobile compact layout | **FAIL / major UX** |
| Reject conversational continuity | **FAIL** — after rejecting `TEST-REJECT-23D`, later ambiguous message caused Secretary to refer again to confirming the rejected task |

PHASE 23D-C status: **manual core Agent E2E completed**; core Agent flow **PASS**; runtime/UX findings moved to **PHASE 23D-D**.

PHASE 23D-C completion is **not claimed** until 23D-D closure and re-validation.
