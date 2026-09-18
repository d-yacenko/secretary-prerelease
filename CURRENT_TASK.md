# Current task — PROJECT-WIDE HOLD pending Telegram API Terms clarification

## Status

- Telegram A1–A4.4 implementation: ACCEPTED in code / NOT production deployed.
- Production Migration Rollout M1 harness: ACCEPTED at exact SHA `917eebed4b0ffb6bf55f573a24d99d00dc1f8fbb`.
- M2 production readiness retry: READY.
- Production runtime/ref remains exact `5cce4b57b14e0052a038acae1354a2821a2bb77b`.
- Production Alembic remains exact `0041`.
- Telegram platform credentials are provisioned in production `/opt/secretary/.env`; values remain secret.
- M3 migration/deployment is NOT authorized.
- Telegram Bot API retirement is NOT authorized.
- No agent implementation/design task is currently authorized.
- **All project development is paused** until Telegram answers the API Terms clarification request and Architect/operator choose the resulting direction.

## HOLD reason

Before any further engineering, Architect and operator must resolve whether the intended personal-use MTProto + AI assistant scenario is permitted under current Telegram API Terms and Content Licensing / AI terms.

The intended scenario is:

- the user authenticates their own Telegram account via MTProto;
- Secretary reads messages/chats already accessible to that user;
- processing is for that user's own personal assistant experience;
- the purpose is summarization, prioritization, retrieval and contextual assistance;
- there is no model training/fine-tuning, dataset creation, public indexing, global search, resale, investigation, or unrelated data exploitation;
- production may use an external LLM API for inference unless a compliant architecture requires otherwise.

Open contractual questions include:

1. whether current Telegram prohibitions on using Telegram-derived data for AI/ML "deployment" cover ordinary private inference/summarization for the recipient;
2. whether the "ordinary, legitimate, and intended use" language creates any usable personal-use/client-feature allowance despite API Terms section 1.5;
3. whether processing only locally/self-hosted materially changes the Telegram contractual analysis;
4. whether a recipient's own consent is sufficient for received messages, or whether "all relevant users" requires consent from message authors/participants;
5. whether Telegram offers or will provide written clarification for this exact use case.

## Alternative surfaces to evaluate only if needed

If MTProto + AI is not permitted or remains materially ambiguous, do not assume Bot API and MTProto are the only options. Future research may include officially supported or user-controlled client-side integration surfaces such as:

- Android share intents / explicit "Share to Secretary" flows;
- Android notification-listener based ingestion, subject to Android permissions, Telegram behavior, and legal/contractual review;
- Telegram-documented Android intents/deep links or export/share mechanisms;
- Linux desktop notifications / freedesktop D-Bus surfaces exposed by Telegram Desktop;
- other explicit local user-triggered export/copy/share mechanisms;
- Bot API / Business Bot where the user directly and voluntarily submits content with clear consent.

These are only research candidates, not approved architectures. Prefer official, least-privilege, user-controlled surfaces and avoid brittle screen scraping, private database reverse engineering, or invasive accessibility capture unless later explicitly justified and permitted.

## Current authorization

STOP.

Until Telegram's answer is reviewed, do not:

- assign or execute any coding/design task, Telegram-related or otherwise;
- modify application/domain/UI code;
- move `production`;
- deploy;
- restart/recreate production services;
- run production Alembic writes;
- mutate production DB;
- modify production `.env`;
- perform production MTProto login or history import;
- delete/disable the existing bot;
- remove Bot API code/config/schema;
- begin an unrelated development branch merely to stay busy.

Discussion/research only.

`CURRENT_TASK.md` is the source of active authorization.
