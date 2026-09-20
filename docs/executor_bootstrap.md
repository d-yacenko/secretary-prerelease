# Executor bootstrap

This runbook defines the reusable local/bootstrap procedure for every Executor work cycle. It is infrastructure plumbing, not a project phase and not evidence about Secretary, production, or any provider.

## Canonical repository

The only canonical active repository is:

`https://github.com/d-yacenko/secretary-prerelease.git`

Never treat these as the active project checkout:
- `https://github.com/d-yacenko/secretary.git`
- `secretary_alpha`
- arbitrary mirrors/forks.

## Fresh-checkout rule

Before implementation or runtime work, verify the current checkout.

If any of the following is true:
- origin is not the canonical repository;
- checkout belongs to another project;
- branch/worktree state is unrelated to the task;
- unknown dirty or untracked files are present;
- required refs cannot be resolved because the checkout is wrong/stale;

then do **not** repair, repoint, clean, reset, stash, delete files, or reuse that checkout.

Leave it untouched and create a fresh temporary clone of the canonical repository.

Example:

```bash
root="$(mktemp -d)"
repo_dir="$root/secretary-prerelease"
git clone --no-checkout https://github.com/d-yacenko/secretary-prerelease.git "$repo_dir"
cd "$repo_dir"
```

Fetch only the refs required by the current task.

## Mandatory task inputs

From canonical `origin/main`, read:
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `AGENTS.md`
- `docs/executor_bootstrap.md`

Then read only files directly required by the authorized task.

Verify every authorized SHA/ref exactly before execution.

## Production SSH bootstrap

For production/runtime tasks:

1. Use only `ops/production/target.json`.
2. Verify the pinned SSH host key according to the production runbook.
3. Authentication must use the pre-existing workstation/Executor credential integration already used for prior successful production work.
4. Do not create a new production key as a workaround.
5. Do not copy private keys into the repository.
6. Do not ask the user to paste private keys, passwords, passphrases, tokens, recovery codes, or key material into chat.
7. Do not probe alternative hosts, aliases, directories, or credentials.

Git/bootstrap readiness and the actual authorized production/runtime task should occur in the **same work cycle**.

## Failure handling

Do not create separate architecture/product phases for:
- wrong local origin;
- stale/missing local remote refs caused by the wrong checkout;
- dirty unrelated worktree;
- missing SSH-agent forwarding;
- unavailable ambient SSH credential path.

If bootstrap cannot be established, report one concise sanitized blocker and stop, for example:

`EXECUTOR_BOOTSTRAP_BLOCKED=canonical_repo_unavailable`

or

`EXECUTOR_BOOTSTRAP_BLOCKED=ssh_credentials_unavailable`

Do not perform credential archaeology unless the Architect explicitly authorizes it.

## One-shot authorization semantics

A one-shot live/provider authorization is consumed only after the task's defined remote/provider start marker is reached.

These do **not** consume it:
- wrong local repository;
- dirty checkout;
- missing local ref;
- host-key/pre-SSH bootstrap stop;
- failed SSH authentication before the remote helper starts.

Such stops are Executor-bootstrap facts, not product/provider diagnostic results.

## Reporting

Bootstrap success should be summarized compactly:
- canonical repo: PASS;
- authorized refs/SHAs: PASS;
- clean/exact checkout: PASS;
- production target/pin: PASS when applicable;
- SSH credential/auth path: PASS when applicable.

Then continue directly into the actual authorized task.

Bootstrap failure should be a single sanitized blocker plus confirmation that no product/provider/production action occurred.
