# Current task — HOLD after public OAuth branding site acceptance

## Architect acceptance

Commit:

`3930c4b4c026a2e1fc9acb31c0d8fea1b9422b5c`

is ACCEPTED / DEPLOY-READY / NOT DEPLOYED.

Current production runtime/ref remains:

`2a5d76ae80d53c13a6581852ef1a0362ad1a3e38`

Alembic remains:

`0046`

No migration files changed.

## Accepted public branding surface

Target public hostname:

`web-itx.duckdns.org`

Accepted URLs after rollout:
- `https://web-itx.duckdns.org/`
- `https://web-itx.duckdns.org/privacy`
- `https://web-itx.duckdns.org/terms`

Accepted architecture:
- static pages live in `infra/public/`;
- Caddy serves only the public branding pages;
- no Secretary API reverse proxy is exposed through Caddy;
- unrelated paths return 404;
- `public_web` uses pinned `caddy:2.10.2`;
- only host TCP 80/443 are published;
- no Secretary secret environment and no DB dependency;
- Caddy data/config persist in named volumes.

## Accepted page content

Homepage:
- identifies Personal Secretary;
- explains self-hosted/personal productivity use;
- discloses Gmail, Google Calendar, and Google Drive access and purposes;
- links Privacy Policy and Terms.

Privacy:
- discloses Google data categories and purposes;
- states imported source data may be stored by Secretary;
- states OAuth credentials/tokens are encrypted at rest;
- states Google user data is not sold or used for advertising;
- discloses relevant data may be sent to the configured AI provider when AI features are enabled;
- explains Google access revocation and that already imported data may remain until removed;
- avoids fabricated retention/deletion guarantees.

Terms:
- appropriate for the prerelease/self-hosted product;
- no fabricated company identity.

## Accepted rollout helper

Dedicated rollout entrypoint:
`ops/production/public_web_rollout.py`

Remote helper:
`ops/production/remote_public_web.py`

Accepted safety properties:
- canonical clean up-to-date main required;
- exact authorized release SHA required;
- production checkout and origin/production must equal exact release;
- pinned host-key/target contract reused;
- DB/API/worker/API-health verified before mutation;
- only `public_web` may be changed;
- db/api/worker/.env identities must remain unchanged;
- first rollout fails closed if ports 80/443 are already occupied;
- temporary HTTPS/TLS startup failures are retried within a bounded 45-second window;
- no insecure TLS bypass;
- first-rollout post-start failure cleans up only newly-created `public_web`;
- pre-existing `public_web`, including stopped/exited containers, is preserved on failed update;
- pre-existing detection uses all-state Compose lookup;
- post-start validation remains running-only and requires a running container;
- successful rollout verifies homepage/privacy/terms = 200 and unrelated path = 404;
- Git refs are not moved by the helper.

## Verification reported on exact accepted commit

- focused tests: 24 passed;
- `py_compile`: passed;
- Ruff check: passed;
- Ruff format --check: passed;
- `docker compose config --quiet`: passed;
- `git diff --check`: clean;
- migration files changed: none.

## Next operational step

A live first rollout of `public_web` is a separate production action and requires explicit human authorization.

After successful rollout, the Google OAuth branding fields can be set to:
- Application home page: `https://web-itx.duckdns.org/`
- Application privacy policy: `https://web-itx.duckdns.org/privacy`
- Application terms of service: `https://web-itx.duckdns.org/terms`

Google Cloud Publishing status change and fresh Google OAuth authorization remain separate operator actions after the site is live.

## Authorization state

No production/public_web/Google Cloud/OAuth action is currently authorized.

Do not:
- move production ref;
- run public_web rollout;
- deploy/restart/recreate;
- change ports/firewall/DNS;
- change Google Cloud OAuth settings;
- perform Google OAuth reauthorization;
- run direct production SSH/manual Docker/Compose;
- change production env;
- perform production DB writes.

STOP and await explicit human authorization.
