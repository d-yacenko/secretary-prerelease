# Current task — Add Google Search Console verification meta tag

## Context

Production runtime remains exact `caab6f1825f69635f88724207ccf173b808dafa4`, Alembic `0046`.

Google branding verification is blocked because Google does not yet recognize ownership of `https://web-itx.duckdns.org/`.

The human supplied the public Search Console verification tag:

`<meta name="google-site-verification" content="hTkY_ZxfZrzsygn-3oU4wxH6zraiRWo28hGXZF_U1Is" />`

## Authorization

Code/test/documentation only. Do NOT deploy or run the production branding publisher in this task.

## Required change

1. Add the exact verification meta tag above to the `<head>` of `infra/public/index.html`.
2. Keep it on the public homepage permanently unless a later explicit task removes/replaces it.
3. Do not add the tag to privacy/terms pages unless required by the implementation; the homepage is the verification target.
4. Do not modify OAuth client secrets, Google credentials, production env, nginx, DNS, or Search Console settings.
5. Add/update a focused test proving:
   - the homepage contains exactly one `google-site-verification` meta tag;
   - its `content` value is exactly the supplied token;
   - privacy/terms pages do not gain the tag.
6. Run the focused branding test suite, `git diff --check`, and any directly relevant formatting/lint checks.

Record the implementation result and exact commit SHA in `PROJECT_STATE.md`, return `CURRENT_TASK.md` to HOLD, push, and STOP.

## Not authorized

No production deploy, production ref movement, branding publisher execution, nginx action, DNS/firewall change, Google Cloud/Search Console mutation, OAuth reauthorization, DB write, or Telegram work.
