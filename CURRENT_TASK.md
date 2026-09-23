# Current task — Read-only live Search Console meta verification

## Context

Production runtime remains exact `54888ed5797b4b84fa663ff8be11b8b74c64e2a6`, Alembic `0046`.

Google Search Console still reports that ownership of `https://web-itx.duckdns.org/` is not verified, despite the prior rollout reporting that the verification meta tag is live.

## Authorization

Read-only verification only. No production mutation is authorized.

## Required checks

1. Bootstrap canonically and confirm production runtime/ref still equal `54888ed5797b4b84fa663ff8be11b8b74c64e2a6`.
2. Fetch exactly:
   `https://web-itx.duckdns.org/`
   with normal TLS verification and without following redirects.
3. Report only:
   - HTTP status;
   - final effective URL;
   - Content-Type;
   - count of `google-site-verification` meta tags;
   - exact `content` value of each such tag;
   - whether the tag appears inside the HTML `<head>`;
   - whether the returned HTML is the same authorized homepage by comparing its SHA-256 to the exact release object `infra/public/index.html`.
4. Also fetch exactly:
   `http://web-itx.duckdns.org/`
   and report only status and Location header, without following redirects.
5. Do not print page bodies, unrelated headers, cookies, auth data, TLS private material, logs, or config.
6. Do not change nginx, files, Docker, DNS, firewall, Google Cloud, Search Console, env, DB, or application state.
7. Record sanitized findings in `PROJECT_STATE.md`, return `CURRENT_TASK.md` to HOLD, commit/push, and STOP.

## Expected verification token

`hTkY_ZxfZrzsygn-3oU4wxH6zraiRWo28hGXZF_U1Is`

## Goal

Determine whether the live server currently serves the exact verification meta tag in the exact homepage bytes expected by the deployed release.
