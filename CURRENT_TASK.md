# Current task — HOLD

AH2-M is BLOCKED before the first real-model call because no local eval OpenAI API key is available to the Executor process.

No model was called.
No semantic eval batch exists.
No AH2-M run artifacts were produced.
No product prompt/tool/runtime code changed.
No production DB or production credential was read.
AH2-C was not started.

## Completed AH2-M preflight

Verified before the blocked gate:

- `backend/app` matches production release `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`;
- production contracts under evaluation are therefore the deployed AH2-P + AH2-D + AH2-T contracts;
- local/disposable DB identity: `localhost / secretary`;
- executable scenario catalogue validates;
- AH2-M guard tests pass;
- scripted-provider dry-run completed with zero model/network calls and no live external transports;
- total deterministic preflight/contract tests: 64 passed.

Blocking condition:

`BLOCKED=local_eval_openai_key_unavailable`

`OPENAI_API_KEY` was empty in the Executor process environment and no local eval secret source was available.

## Production remains unchanged

- production runtime/ref: `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`;
- Alembic: `0052 / 0052`;
- health: PASS.

## Resume gate

Resume AH2-M only after the workstation/Executor environment has a dedicated eval OpenAI API key available through a local secret/environment mechanism.

Security constraints:

- never commit the key;
- never write it into `CURRENT_TASK.md`, `PROJECT_STATE.md`, eval artifacts, logs, or chat;
- do not read/decrypt a production user's stored OpenAI credential;
- do not use production DB as a workaround.

Once the local eval key is available:

1. update to current `main`;
2. re-read this HOLD and the AH2-M authorization/history in `PROJECT_STATE.md`;
3. re-run the AH2-M deterministic safety/preflight guards;
4. execute the authorized bounded real-model batch:
   - 15-scenario smoke first;
   - if infrastructure is sound, two additional trials per primary scenario;
   - terminal-T2 ×2;
   - chat-F2 ×2;
   - maximum 49 semantic trials;
5. use only synthetic/disposable data and fake external transports;
6. commit sanitized run artifacts + structural report + summary;
7. return to HOLD for Architect manual answer review;
8. STOP without implementing behavior fixes.

Do not start another product slice while AH2-M is blocked unless Architect explicitly changes the roadmap.
