# Current task — Telegram MTProto M4AU1 accepted: await deploy authorization

## Status

M4AU1 manual-only ordinary visibility semantics are accepted and integrated to canonical main.

Implementation commit:
`2db36510fe884eadc40d63fed8661ed3627f1cbb`

Current canonical main after state recording:
`d7b7ff3054fb8501a8fd62701d54e1ca494b3e52`

Production remains unchanged at:
`b7fbdc71584cfde042a998fbfefb06015175a205`

Production Alembic remains:
`0046`

Accepted semantics:
- manual=true, scope=false -> ordinary visible;
- manual=false, scope=true -> ordinary visible;
- manual=true, scope=true -> ordinary visible;
- manual=false, scope=false -> hidden;
- manual-only visibility does not mutate `scope_active`;
- AI eligibility/retrieval remains scope-only and production flag remains `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- recurring sync remains `scope_active=true` only;
- no migration / no `0047`;
- Bot API untouched.

Validation note:
- DB-backed test collection was available but execution could not initialize because the local executor DB host was unavailable;
- static/policy-fragment checks, Python compile, Ruff and diff-check passed;
- production DB must not be used to compensate for the missing local DB.

## Authorization state

NO production deploy is currently authorized.

Do NOT:
- move `production` ref;
- run `ops/production/deploy.py`;
- use production SSH;
- click Sync;
- Apply Scope;
- change Telegram selections/folders;
- login/re-login;
- change AI flag;
- change Bot API;
- mutate production.

Await explicit human authorization for a schema-neutral deploy of the accepted M4AU1 change.

The separately recorded future folder-bootstrap preference (roughly 10–20 latest messages per chat, then incremental sync) is NOT part of this deploy candidate and remains a future task.

`CURRENT_TASK.md` is the source of active authorization.
