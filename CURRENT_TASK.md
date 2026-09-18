# Current task — Telegram Compliance Re-scope C1

## Status

- Telegram A1–A4.4 implementation: ACCEPTED in code / NOT production deployed.
- Production Migration Rollout M1 harness: ACCEPTED at exact SHA `917eebed4b0ffb6bf55f573a24d99d00dc1f8fbb`.
- M2 production readiness retry: **READY** based on sanitized operator evidence.
- Production runtime/ref remains exact `5cce4b57b14e0052a038acae1354a2821a2bb77b`.
- Production Alembic remains exact `0041`.
- Telegram platform credentials are provisioned in production `/opt/secretary/.env`; values remain secret.
- **M3 migration/deployment is NOT authorized.**
- **Telegram Bot API retirement is NOT authorized.**

## Compliance blocker

Current Telegram API Terms prohibit using/accessing/aggregating Telegram platform data to train, fine-tune, develop, enhance, benchmark, or deploy AI/ML systems.

Telegram Content Licensing terms allow an exception only where all relevant users provide explicit, informed, affirmative, continued consent limited to the specific content/chat/channel/non-global context.

The accepted MTProto A3/A4 design automatically imports selected Telegram dialogs/history and exposes active MTProto objects to assistant/search/retrieval. That is not safe to deploy into the Secretary AI pipeline under the current Telegram terms without a compliant consent model.

This is an external compliance gate, not a code-quality failure.

## Architectural consequence

Do not treat Bot API and MTProto as interchangeable transports anymore.

- MTProto may remain technically useful for non-AI client functionality, but Telegram-derived content must not reach Secretary's LLM/retrieval/embedding/AI context unless the required consent basis is demonstrably satisfied.
- Bot Platform terms explicitly allow use of data submitted directly and voluntarily to the bot by users when intended use is clearly disclosed and users provide individual, explicit, active, revocable consent.
- Therefore the existing Bot API path must remain available for analysis/rework until a compliant canonical Telegram UX is chosen.
- Do not remove bot code, bot schema, webhook, credentials, or production bot configuration in C1.
- Do not deploy the accepted MTProto automatic history/scope ingestion to production in C1.

## Objective

Produce a concrete minimal compliant Telegram architecture for Secretary that preserves a single clear user mental model.

The design must answer:

1. What Telegram data may enter the AI pipeline?
2. What user action constitutes explicit/active/revocable consent?
3. Can directly sent/forwarded bot messages be the canonical AI ingress?
4. If MTProto is retained, what strictly non-AI functions remain useful?
5. How are retrieval, embeddings, assistant context, proactive processing, and recurring sync prevented from consuming non-consented Telegram data?
6. What existing A3/A4 components can be reused safely versus disabled/removed?
7. What is the cleanest single user-facing "Telegram" connection model?
8. What eventual legacy Bot API cleanup, if any, is still appropriate after the compliant path is proven?

## Required C1 work

C1 is design + code-impact analysis only unless an extremely small test-only proof is useful.

Inspect at minimum:

- `backend/app/api/telegram.py`
- `backend/app/api/telegram_mtproto.py`
- `backend/app/connectors/telegram/*`
- Telegram services/scheduler/job handlers
- Telegram materialization metadata
- Retrieval/Search/ObjectQuery/RecentSource/context/graph filtering added by A4.3
- client/profile/source UI references to Telegram
- existing bot/business send path
- configuration/env variables and production deploy implications.

Produce a proposed target architecture with explicit boundaries between:

- platform credentials;
- per-user authorization;
- ingestion;
- AI-visible storage/retrieval;
- outbound sends;
- consent/revocation.

## Constraints

Until Architect accepts C1:

- no production ref move;
- no production deploy;
- no service restart/recreate;
- no production Alembic write;
- no DB mutation;
- no further `.env` mutation;
- no MTProto login against production;
- no Telegram history import against production;
- no bot deletion/disable;
- no destructive cleanup of historical Telegram objects;
- no new migration.

Do not weaken the accepted M1 safety harness.

## Deliverable

Return:

- exact starting SHA;
- inventory of Bot API functionality;
- inventory of MTProto functionality;
- every current path by which Telegram-derived content can reach AI/retrieval/embedding/proactive processing;
- proposed compliant target architecture;
- explicit recommendation for bot retention/retirement under that target;
- smallest implementation phases to reach it;
- expected migrations/config/UI changes;
- test strategy;
- confirmation no production mutation occurred.

Final marker:

`TELEGRAM_COMPLIANCE_RESCOPE_C1_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
