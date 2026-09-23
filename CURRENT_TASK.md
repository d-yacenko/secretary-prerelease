# Current task — Public OAuth branding site for Personal Secretary

## Human request

Make the Google OAuth branding pages self-contained on the Secretary production server.

This is a bounded CODE/TEST-ONLY task.

No production deploy, SSH, provider call, Google Cloud mutation, OAuth reauthorization, firewall change, DNS change, or production ref movement is authorized by this task.

Current production runtime/ref:
`2a5d76ae80d53c13a6581852ef1a0362ad1a3e38`

Current Alembic:
`0046`

Target public hostname already registered in the Google OAuth Authorized domains configuration:
`web-itx.duckdns.org`

Google production-app requirements relevant to this task:
- homepage must be public and accessible without login;
- homepage must describe the app and its use of Google user data;
- homepage must link to the privacy policy;
- privacy policy must be a separate HTML page on the same/authorized domain and disclose access/use/storage/sharing of Google user data;
- terms page will also be provided;
- no third-party hosted pages.

## Architecture

Do NOT introduce a separate application stack or third-party site.

Implement a tiny static public web surface managed by this repository:

- HTTPS domain: `https://web-itx.duckdns.org`
- Caddy as the public TLS/static-file service;
- static pages committed under `infra/public/`;
- Caddy exposes ONLY the static branding pages;
- do NOT reverse-proxy the Secretary API through this public service in this task;
- do NOT expose the internal API port or change `SECRETARY_API_BIND`;
- Caddy obtains/manages TLS normally and persists its own certificate state in named volumes.

Required public URLs:
- `https://web-itx.duckdns.org/`
- `https://web-itx.duckdns.org/privacy`
- `https://web-itx.duckdns.org/terms`

## A. Static pages

Create plain, responsive, accessible HTML/CSS pages with no JavaScript, analytics, cookies, external fonts, trackers, or third-party assets.

### Homepage

Must:
- identify the product as Personal Secretary;
- describe it as a personal/self-hosted productivity assistant;
- describe core functions at a high level: unified inbox/context, search, tasks, calendar/email assistance, files, and optional AI-assisted features;
- transparently explain why Google access is requested:
  - Gmail: read/search/summarize mail and send mail only when the user explicitly asks/approves;
  - Google Calendar: read calendar/events and create calendar events only when the user explicitly asks/approves;
  - Google Drive: read file metadata and, when explicitly requested by the user, fetch/export file content for Secretary context;
- link visibly to `/privacy` and `/terms`;
- be understandable without authentication.

### Privacy policy

Use concise factual language matching the actual implementation. Do not overclaim.

Must disclose:
- categories of Google data accessed: Gmail data, Calendar data, Drive metadata/content as described above;
- purposes: user-requested productivity, search/context, synchronization, task/calendar/email workflows;
- Secretary may store imported source data in its own database to provide those features;
- Google OAuth credentials/tokens are stored encrypted at rest by Secretary;
- Google user data is not sold and is not used for advertising;
- when AI features are enabled/configured, only relevant data needed for the requested feature may be sent to the configured AI provider; this must be stated plainly rather than hidden;
- users can revoke Google access in their Google Account; revocation stops future access, while already imported Secretary data may remain until removed from Secretary/storage;
- reasonable security/access-control statement without promising absolute security;
- contact/privacy questions should use the support contact shown on the Google OAuth consent screen; do NOT commit a personal email address merely because one is visible in Google Cloud UI.

Do not invent a retention period or deletion guarantee not implemented by the product.

### Terms

Keep terms short and suitable for this personal/self-hosted prerelease:
- service purpose;
- user responsibility for connected accounts/data/actions;
- explicit actions remain subject to Secretary approval/safety mechanisms;
- service provided as-is during prerelease;
- user may stop using it and revoke connected provider access;
- link back to Privacy Policy.

No fabricated company identity.

## B. Public web service

Replace the placeholder `infra/Caddyfile` with a minimal production configuration for `web-itx.duckdns.org`.

Requirements:
- automatic HTTPS;
- serve static files from a read-only mounted directory;
- map exactly:
  - `/` -> homepage;
  - `/privacy` and optional trailing slash -> privacy page;
  - `/terms` and optional trailing slash -> terms page;
- unrelated paths should return 404, not proxy to API;
- add conservative security headers suitable for static HTML;
- no secrets in config.

Add a Compose service named `public_web` to `infra/compose.yaml`:
- pinned concrete Caddy 2.x image version, not `latest`;
- publish TCP 80 and 443 only;
- read-only mounts for Caddyfile/static pages;
- named persistent volumes for Caddy data/config;
- restart policy appropriate for production;
- no dependency on DB;
- no access to Secretary secrets;
- do not change DB/API/worker ports or environment.

## C. Safe one-shot production rollout tooling — BUILD ONLY, DO NOT RUN

Normal `ops/production/deploy.py` intentionally manages only api+worker and must not be casually broadened.

Add a dedicated fail-closed public-web rollout entrypoint under `ops/production/` (local + remote helper if needed), reusing the existing production target/SSH trust contract.

It must:
- run only from canonical clean up-to-date local `main`;
- require an exact authorized release SHA;
- require remote origin/path and `origin/production` to equal that exact SHA;
- require the production checkout already be at that exact release SHA;
- require existing DB/API/worker and API health to be healthy before change;
- record DB container identity, DB volume identity, production .env checksum, API container identity, and worker container identity;
- if `public_web` does not yet exist, fail closed if host ports 80 or 443 are already occupied;
- start/recreate ONLY `public_web` through the canonical Compose files;
- never recreate/touch db, api, or worker;
- never modify `.env`;
- verify DB container/volume, .env, API and worker identities remain unchanged;
- verify `public_web` is running;
- verify HTTPS responses for `/`, `/privacy`, `/terms` and that an unrelated path returns 404;
- never print secrets, account identifiers, OAuth tokens, or raw environment values;
- if post-start verification fails on the first rollout, stop/remove only the newly-created `public_web` service and report a sanitized failure; do not improvise firewall/DNS/SSH repair;
- do not alter Git refs.

No live execution in this task.

## D. Documentation

Update `docs/google_oauth.md` with the exact branding values to use AFTER a successful production rollout:

- Application home page: `https://web-itx.duckdns.org/`
- Application privacy policy: `https://web-itx.duckdns.org/privacy`
- Application terms of service: `https://web-itx.duckdns.org/terms`

Also note:
- Google Cloud Publishing status remains an operator action;
- domain ownership/verification in Google Search Console may be required by Google;
- after moving from Testing to In Production, the currently expired Google refresh token still requires one fresh Secretary OAuth authorization.

## Tests / checks

Add focused tests that prove at minimum:
- homepage contains product description plus visible privacy/terms links;
- privacy page contains explicit Gmail/Calendar/Drive disclosure and AI-provider disclosure;
- pages contain no third-party resource URLs/scripts/analytics;
- Caddy config exposes only the three intended page paths and does not reverse-proxy the API;
- Compose config contains `public_web` with only 80/443 public ports and no Secretary secret env;
- rollout helper rejects wrong origin/path/ref/release and occupied ports on first rollout;
- rollout helper invariants ensure db/api/worker/env are untouched;
- no migration files changed.

Run:
- focused tests;
- `docker compose ... config` (or equivalent deterministic compose validation);
- Python compile/Ruff for new production helper;
- any Caddy config validation available without live production mutation;
- `git diff --check`.

When complete:
- update `PROJECT_STATE.md` factually;
- commit + push to main;
- report exact SHA and checks;
- STOP.

## Production boundary

No production SSH.
No public_web start.
No port/firewall mutation.
No DNS mutation.
No Google Cloud mutation.
No OAuth reauthorization.
No production ref movement.
No deploy.