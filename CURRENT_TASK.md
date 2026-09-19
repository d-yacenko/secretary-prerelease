# Current task — Production SSH M4ADH3: exact invocation transport proof

## Status

Telegram M4AD remains blocked before live read-only production inspection.

M4ADH2 proved locally:
- exact repository `_verified_known_hosts()` returns one `ssh-ed25519` line;
- fingerprint is exactly `SHA256:VSSBeGqYXy8GGruKZhPJ2WZu8dP38i5ldE6FH+etoRs`;
- `ssh-keygen -F web-itx.duckdns.org` matches;
- inherited SSH config does not alter target/port/proxy/canonicalization;
- no-auth probes A/B/C all pass host-key verification.

Yet the later M4AD authenticated read-only invocation again failed before remote execution with a "no known key"/host-key verification failure.

Therefore this task authorizes only **M4ADH3 — prove the exact SSH argv/temp-file lifecycle used for the M4AD session**.

Do not run Telegram diagnostics yet.

## Safety

Allowed:
- local repository helper execution;
- temporary files;
- sanitized `ssh -G` / `ssh -vvv`;
- one strict authenticated SSH transport proof that runs only remote `true` or `printf M4ADH3_OK`.

Forbidden:
- any production data inspection beyond the transport proof;
- DB/log/docker commands;
- production writes;
- Telegram/provider calls;
- host-key bypass;
- changing `target.json`, SSH config, known_hosts, code, env, refs.

Do not print private key paths/contents, tokens, IPs, credentials, or unrelated SSH config.

## Step 1 — construct exact temp known_hosts

In the SAME process/session that will launch SSH:
- import/reuse current `ops/production/deploy.py::_verified_known_hosts()`;
- target `root@web-itx.duckdns.org`, port 22;
- expected fingerprint `SHA256:VSSBeGqYXy8GGruKZhPJ2WZu8dP38i5ldE6FH+etoRs`;
- write returned line to a temp file;
- keep the temp file alive/open until AFTER ssh exits.

Before ssh exec, prove:
- temp path exists = yes;
- temp file size > 0 = yes;
- `ssh-keygen -F web-itx.duckdns.org -f <temp>` matches = yes;
- fingerprint from that matched line = pinned fingerprint.

Do not print base64 key material.

## Step 2 — print sanitized exact argv

Build exactly one SSH argv list, no shell-string reconstruction:

- `ssh`
- `-p 22`
- `-o BatchMode=yes`
- `-o StrictHostKeyChecking=yes`
- `-o UserKnownHostsFile=<temp>`
- `-o GlobalKnownHostsFile=/dev/null`
- `-o HostKeyAlgorithms=ssh-ed25519`
- `-o ConnectTimeout=5`
- `root@web-itx.duckdns.org`
- remote command `true`

Report sanitized argv preserving option names/order, but replace temp path with `<temp>`.

Do not invoke through `sh -c` or nested quoting.

## Step 3 — parser/effective config for this exact argv

Before connection, run `ssh -G` with the SAME option set and target.

Report only:
- hostname;
- port;
- strictHostKeyChecking;
- hostKeyAlgorithms contains ssh-ed25519 yes/no;
- userKnownHostsFile resolves to exact temp file yes/no;
- globalKnownHostsFile is /dev/null yes/no;
- hostKeyAlias;
- proxyjump/proxycommand presence.

If any field differs from the intended contract, STOP and classify INVOCATION_CONSTRUCTION_DEFECT.

## Step 4 — one authenticated transport proof

Run the exact argv from Step 2.

Success criterion:
- host-key verification passes;
- SSH authentication succeeds;
- remote `true` exits 0.

No other remote command is authorized.

If it succeeds:
return `PRODUCTION_SSH_M4ADH3_TRANSPORT_PASS` and STOP.

If it fails:
- rerun the SAME argv once with `-vvv`;
- capture only sanitized lines needed to determine:
  - exact host used for key lookup;
  - server host-key type;
  - server host-key fingerprint;
  - which UserKnownHostsFile OpenSSH opened;
  - whether a matching key was found;
  - final host-key/auth failure reason.
- do not print identity file paths, IPs, environment, private keys, or unrelated config.

Also record immediately after failure:
- temp file still exists yes/no;
- parser still matches yes/no;
- fingerprint still equals pin yes/no.

No more retries.

## Classification

Choose one:
A. temp-file lifecycle defect;
B. argv/option construction defect;
C. shell/wrapper quoting defect;
D. SSH identity/auth failure after host-key PASS;
E. transient host-key/network inconsistency;
F. transport proof PASS; previous M4AD invocation path was defective/transient;
G. insufficient evidence.

## Completion report

Return:
- temp lifecycle checks;
- sanitized exact argv;
- exact `ssh -G` contract checks;
- transport proof result;
- sanitized decisive verbose evidence if failed;
- classification;
- smallest next step;
- confirmation no production data inspection occurred;
- confirmation no Telegram/provider call occurred;
- confirmation no host-key bypass or production mutation occurred.

Final marker:
- success: `PRODUCTION_SSH_M4ADH3_TRANSPORT_PASS`
- failure: `PRODUCTION_SSH_M4ADH3_DIAGNOSIS_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
