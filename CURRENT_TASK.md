# Current task — Production SSH M4ADH: re-establish canonical host-key trust

## Status

Telegram M4AD read-only production diagnosis is BLOCKED before SSH authentication because the canonical strict host-key check fails.

Canonical production target:
`root@web-itx.duckdns.org:22`

Repository-pinned fingerprint:
`SHA256:VSSBeGqYXy8GGruKZhPJ2WZu8dP38i5ldE6FH+etoRs`

This same fingerprint was present in:
- accepted M1 harness SHA `917eebed4b0ffb6bf55f573a24d99d00dc1f8fbb`;
- deployed release SHA `8091736337689b68b4510126e74d9e409397f696`.

M3 previously succeeded through the strict SSH harness. Therefore a current mismatch must be treated as a production trust-anchor event, not bypassed.

This task authorizes only **M4ADH — non-authenticating host-key discovery and independent human verification preparation**.

It does NOT authorize changing `target.json`, connecting with relaxed host-key checking, logging into production, or continuing M4AD yet.

## Hard safety rules

Do NOT:
- use `StrictHostKeyChecking=no`;
- use `UserKnownHostsFile=/dev/null` without an independently verified temporary known_hosts entry;
- accept a new key interactively;
- edit/remove user's normal `~/.ssh/known_hosts`;
- update `ops/production/target.json`;
- SSH-authenticate to production while the key is unverified;
- mutate production or Telegram;
- print private keys or credentials.

Public SSH host-key fingerprints are safe to report.

## Step 1 — DNS observation

Without SSH authentication:
- resolve `web-itx.duckdns.org` using the local resolver;
- if practical, also query at least one independent public resolver;
- report sanitized A/AAAA addresses;
- repeat resolution at least twice separated by a short interval to detect rotation;
- compare whether results are stable.

DNS agreement is supporting evidence only, NOT sufficient host identity proof.

## Step 2 — advertised SSH host keys

Use `ssh-keyscan` only; do not authenticate.

For every advertised key type returned on port 22:
- compute SHA256 fingerprint using `ssh-keygen -lf ... -E sha256`;
- report key type + fingerprint;
- never print full key material unless necessary; fingerprints are enough.

Repeat the scan at least 3 times.

Determine:
- whether the repository-pinned fingerprint `SHA256:VSSBeGqYXy8GGruKZhPJ2WZu8dP38i5ldE6FH+etoRs` appears on ANY scan;
- whether presented fingerprints are stable across scans;
- whether different DNS addresses present different key sets.

If the pinned fingerprint appears again:
- STOP and report that the mismatch may have been transient/routing-related;
- do not update the repository;
- final marker `PRODUCTION_SSH_M4ADH_PIN_REAPPEARED`.

If it does not appear:
continue to Step 3.

## Step 3 — independent verification handoff

Because network keyscan cannot prove identity after a mismatch, do NOT trust or commit any newly observed fingerprint yet.

Return the candidate fingerprints and ask the human to independently verify the actual server host key using a trusted out-of-band path, preferably the hosting/provider console attached to the production machine.

Human console command for ED25519 if available:

`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256`

If ED25519 is absent, inspect the public `/etc/ssh/ssh_host_*_key.pub` files and compute fingerprints for the key types actually advertised.

The human should return ONLY:
- key type;
- SHA256 fingerprint.

Do not ask for any private key content.

If the human has an already-open SSH session that was established before the mismatch and is unquestionably the production host, that session may also be used only to run the same read-only fingerprint command.

## Step 4 — no automatic trust update

Do not edit `target.json` even if one candidate looks plausible.

Once the human supplies an independently verified fingerprint matching one of the observed advertised fingerprints, STOP for Architect authorization of a separate tiny repository trust-anchor update.

## Completion report

Return:
- current pinned fingerprint;
- DNS observations/stability;
- advertised SSH key type/fingerprint set for each scan;
- whether pinned fingerprint reappeared;
- whether candidate set is stable;
- exact human console command needed for independent verification;
- confirmation no SSH authentication occurred;
- confirmation no host-key bypass occurred;
- confirmation no production/repository mutation occurred.

If independent human verification is required:
`PRODUCTION_SSH_M4ADH_HUMAN_HOSTKEY_CONFIRM_REQUIRED`

If pinned key reappeared:
`PRODUCTION_SSH_M4ADH_PIN_REAPPEARED`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
