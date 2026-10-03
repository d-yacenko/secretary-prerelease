# Current task — HOLD

AH2-CLI1 installed the Linux client built from production source `2314bf72101fbd83d50a7b264154d73740e28db1`. The next action belongs to the human tester. Do not start another Executor slice from this HOLD.

## AH2-CLI1 — exact-production Linux client

- Client source and production backend: `2314bf72101fbd83d50a7b264154d73740e28db1`
- Alembic remains `0052 / 0052`
- Flutter 3.47.5, Dart 3.13.4
- Focused tests: 101 passed, 0 failed
- Analyze of the seven remediation libraries: 0 errors, 1 pre-existing warning, 7 pre-existing infos
- Staged artifact: `/home/d.yacenko/tmp/cli1-2314bf7-artifact/bundle`
- Executable SHA-256: `cab8fdfa2df4beab79bcfa9271ae2b619cc646217475c2f67ff23867ede9a793`
- Kernel SHA-256: `bbdb7f1bc8337da9ec41cd7e92948fbd4463f07af513dccf19200668bdda2a46`
- Previous bundle, kept as rollback: `/home/d.yacenko/.local/share/personal-secretary-preview/19228c9d84bbc0350b78e2d0600710dc3ddf368f/bundle.rollback-ah2-cli1`
- Installed bundle: `/home/d.yacenko/.local/share/personal-secretary-preview/19228c9d84bbc0350b78e2d0600710dc3ddf368f/bundle`
- Startup smoke: process alive, window present
- Config, secure storage, API URL, and tokens were not read or changed
- No backend deploy, migration, or production-ref change

## Human regression

Executor does not perform this gate. The first test is the semantic approval card.

1. Select an existing Task and open Secretary through `Спросить секретаря`.
2. Stage a `waiting_on` update through the already accepted PER1/CTX1 flow.
3. The approval card should show semantic text such as `Изменить задачу: <title>` and `Ожидает: Ольга Володько`. A raw UUID must not be the primary label.
4. The staged turn must not claim the change already happened, and the approval card must stay visible.
5. Abandon a contextual capture, then open global `+ Задача`; the abandoned context must not leak into the fresh capture.

## HOLD

Do not deploy, migrate, rebuild the client again, or start Scheduled Activity work or another remediation slice. Wait for Architect authorization after the human client regression.
