# Current task — Production SSH M4ADH2: local OpenSSH known_hosts/algorithm consistency diagnosis

## Status

Telegram M4AD still has no live production evidence because strict SSH did not start a session.

M4ADH proved the production trust anchor has NOT disappeared:

Canonical target:
`root@web-itx.duckdns.org:22`

Pinned fingerprint:
`SHA256:VSSBeGqYXy8GGruKZhPJ2WZu8dP38i5ldE6FH+etoRs`

Three independent `ssh-keyscan` runs returned a stable key set and the pinned fingerprint reappeared each time as:
`ssh-ed25519`.

DNS was stable.

Therefore:
- do NOT change `ops/production/target.json`;
- do NOT replace the pin;
- do NOT bypass host verification.

The remaining problem is local OpenSSH consistency: a strict session attempt reported that no known key was available even though keyscan/fingerprint verification succeeded.

This task authorizes only **M4ADH2 — local/no-auth diagnosis of temporary known_hosts matching, SSH config effects, and host-key algorithm negotiation**.

No production authentication or remote command is authorized in this task.

## Hard safety rules

Do NOT:
- authenticate to production;
- send SSH credentials;
- use `StrictHostKeyChecking=no`;
- accept keys interactively;
- edit `~/.ssh/config` or `~/.ssh/known_hosts`;
- edit repository files;
- mutate production;
- run Telegram/provider calls;
- print private key contents.

Public host-key fingerprints and non-secret SSH effective-config fields are allowed.

## Step 1 — reproduce the repository helper output locally

From current `origin/main`, import/reuse the exact:
`ops/production/deploy.py::_verified_known_hosts`

with:
- target `root@web-itx.duckdns.org`;
- port `22`;
- pinned fingerprint above.

Write its returned content to a temporary file with restrictive permissions.

Do not manually substitute a different keyscan implementation for this step.

Report:
- helper succeeded yes/no;
- number of known_hosts lines;
- key type(s) only;
- fingerprint(s) only.

Do not print base64 key material.

## Step 2 — prove OpenSSH parser can find the host entry

Against that exact temporary file, run parser-only checks such as:
- `ssh-keygen -F web-itx.duckdns.org -f <temp>`;
- if needed, `ssh-keygen -F '[web-itx.duckdns.org]:22' -f <temp>`.

Report only:
- hostname form that matched;
- key type;
- fingerprint.

If neither hostname form matches, STOP with:
`PRODUCTION_SSH_M4ADH2_KNOWN_HOSTS_FORMAT_BLOCKED`

No remote connection.

## Step 3 — inspect effective SSH config without connecting

Run `ssh -G` for the canonical target using:
A. normal inherited user SSH config;
B. `-F /dev/null`.

Report only these effective fields:
- hostname;
- port;
- canonicalizehostname;
- hostkeyalias if set;
- checkhostip;
- proxyjump presence yes/no;
- proxycommand presence yes/no;
- whether `ssh-ed25519` appears in effective hostkeyalgorithms;
- userknownhostsfile values sanitized to basename/temporary-vs-user config only.

Do not report identity key contents. Identity file paths are not needed.

Determine whether user SSH config changes hostname/alias/port/proxy/canonicalization in a way that could invalidate the generated known_hosts entry.

## Step 4 — no-auth host-key handshake probes

Use a temporary known_hosts file from Step 1.

Every probe MUST disable authentication attempts:
- `PreferredAuthentications=none`;
- `PubkeyAuthentication=no`;
- `PasswordAuthentication=no`;
- `KbdInteractiveAuthentication=no`;
- `BatchMode=yes`.

Every probe MUST keep:
- `StrictHostKeyChecking=yes`;
- exact temporary `UserKnownHostsFile`;
- `GlobalKnownHostsFile=/dev/null`.

A probe is considered HOST-KEY PASS if it gets past host-key verification and then fails only because no authentication method is allowed. Do NOT run a remote command after authentication; authentication is intentionally impossible.

Run:

Probe A — harness-like inherited SSH config, no forced host-key algorithm.

Probe B — same as A plus:
`HostKeyAlgorithms=ssh-ed25519`

Probe C — `-F /dev/null` plus:
`HostKeyAlgorithms=ssh-ed25519`

Use short connect timeout.

If needed use verbose SSH only to extract sanitized lines showing:
- server host-key algorithm/type;
- server host-key fingerprint;
- known_hosts match/found-key fact;
- host-key verification success/failure;
- final no-auth failure.

Do not report IPs/usernames beyond the canonical target already committed, identity files, environment, or unrelated SSH config.

## Classification

Choose one:

A. temporary known_hosts formatting/hostname-token mismatch;
B. inherited user SSH config changes target identity/matching;
C. host-key algorithm negotiation chooses a non-pinned key unless ED25519 is forced;
D. no-auth strict probes accept the pin; prior failure was invocation-specific/transient;
E. still insufficient evidence.

Return the exact probe matrix:
`probe -> host-key pass/fail -> final reason`.

## No corrective yet

Do NOT edit `deploy.py` in M4ADH2.

If B or C is proven, propose the smallest deterministic harness change and tests, but STOP for Architect authorization.

If D is proven, propose the exact strict SSH invocation to use for the read-only M4AD retry, without changing repository trust data.

## Completion report

Return:
- helper generated line count/key type/fingerprint;
- parser match hostname form;
- effective-config comparison;
- Probe A/B/C matrix;
- classification A/B/C/D/E;
- smallest next step;
- confirmation no SSH authentication occurred;
- confirmation no host-key bypass occurred;
- confirmation no user SSH config/known_hosts was changed;
- confirmation no repository/production mutation occurred.

Final marker:
`PRODUCTION_SSH_M4ADH2_DIAGNOSIS_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
