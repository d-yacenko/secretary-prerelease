# Current task — HOLD

## AH2-FIN2 — deterministic temporal display facts for post-approval finalization

Status: complete. Waiting for Architect review. Do not start approval-card UX, Scheduled Activity product integration, or any other remediation item.

- Implementation SHA: `c649981c6342b24eb3eee71c1b727e16b25b1744`
- Authorization base: `8a56eebe8548cf840967025a810edd8a324c9da2`
- AH2-FIN1 implementation: `130066cfecb18bb1ee177c8256483f4c3a2142fc`
- AH2-FIN1 HOLD: `47acbaa4c8d539bc34157b9606597838c1e32ba2`
- AH2-FIN1: ARCHITECT SOURCE-ACCEPTED

Temporal display-fact contract:

- Frozen timestamps are user-facing wording only when they are the same UTC instant as the matching execution-output field.
- A different offset for that same instant is not a different scheduled time.
- Task due calendar date and planned interval come from the approved representation after that check.
- `create_scheduled_activity` narrates frozen `run_at` when it matches `object.due_at`.
- Recurring `local_time` plus IANA `timezone` stay the user-facing schedule. The occurrence instant does not replace them.
- Raw execution results remain in the context and stay authoritative for state and instant.
- AH2-FIN1 language sample behavior is unchanged.

Same instant versus mismatch:

- Same instant: the fact says `approved temporal representation applied` and quotes the frozen text. Due dates also include `calendar date` from that representation.
- Different instant, naive value, or missing output: the fact says `instant mismatch; do not narrate a frozen representation as execution truth` and does not quote the frozen time as applied.
- `update_task changed=false` emits no temporal fact. The no-op effect line remains.

M1 / M2 evidence:

- `2026-10-02T09:00:00+03:00` versus `2026-10-02T08:00:00+02:00` keeps 09:00 +03:00.
- Due `2026-10-09T23:59:00+03:00` versus the same instant in UTC keeps calendar date 2026-10-09.
- Planned `2026-10-06T10:00:00+03:00`–`2026-10-06T12:00:00+03:00` keeps that wall clock against the +02:00 equivalents.
- `2026-10-09T01:00:00+03:00` versus `2026-10-08T22:00:00Z` keeps calendar date 2026-10-09.

Changed files:

- `backend/app/assistant/temporal_finalization.py`
- `backend/app/services/assistant_service.py`
- `backend/app/llm/openai_assistant_provider.py`
- `backend/tests/test_ah2_fin2_temporal_finalization.py`

Test counts:

- `test_ah2_fin2_temporal_finalization.py`: 9 passed
- `test_assistant_action_plans.py`: 45 passed
- Combined gate of those two files plus `test_ah2t_planned_interval.py`, `test_untrusted_prompt_boundary.py`, and the preserved finalization/resume checks: 68 passed
- `test_assistant_conversations.py`: 15 passed
- `git diff --check`: clean
- AH2-M eval contracts were not touched

Production, schema, model, and network:

- Production remains `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`
- Alembic remains `0052 / 0052`
- Health remains PASS
- Model calls: 0
- Real network calls: 0
- No schema change, no storage or job-instant change, and no deploy
