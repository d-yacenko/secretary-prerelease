# Current task — Telegram MTProto M4BA1: one-folder save + preview, no Apply Scope

## Status

M4AZ1 production deploy is PASS.

Production runtime/ref:
`cbd5e7dbe5b8030a1ad100f97bcd2d12f9dccfaa`

Alembic:
`0046`

Deploy invariants reported:
- health PASS;
- DB container unchanged;
- DB volume unchanged;
- production `.env` unchanged;
- API recreated;
- worker recreated;
- no migration / no `0047`.

The shallow folder bootstrap code is now live, but no folder-derived scope has been activated yet.

## Goal

HUMAN UI ONLY.

Configure exactly ONE small Telegram folder and preview its derived scope.

Do NOT Apply Scope in this task.

This is a breadth/safety checkpoint before activation.

## Client

Use the persistent Secretary preview client:

```bash
"$HOME/.local/share/personal-secretary-preview/8091736337689b68b4510126e74d9e409397f696/bundle/personal_secretary"
```

Keep the terminal open while the client is running.

## Procedure

1. Open Account / Telegram MTProto.
2. Confirm the existing Telegram account is still connected.
3. In "Папки синхронизации", choose exactly ONE deliberately small folder.
4. Keep "Исключать заглушенные чаты" enabled.
5. Click "Сохранить папки" exactly once.
6. Click "Предпросмотр области" exactly once.
7. Wait for the preview to complete.
8. Report:
   - selected folder name;
   - preview count: `В области: N`;
   - configured folder count;
   - skipped-count summary shown by the UI;
   - whether preview says truncated;
   - screenshot of the preview if convenient.

## Stop condition

After preview, STOP.

Do not click "Применить область" yet.

The Architect must inspect preview breadth before activation.

## Strictly forbidden

Do NOT:
- Apply Scope / "Применить область";
- click any Telegram Sync button;
- change manual group selections;
- login/re-login;
- select more than one folder;
- disable "Исключать заглушенные чаты";
- use production SSH;
- run provider probes outside the UI flow;
- mutate production by any other path;
- enable MTProto AI;
- change Bot API.

## Interpretation

- Small, expected preview breadth and not truncated -> next phase may authorize one Apply Scope.
- Unexpectedly broad scope or truncated preview -> do not activate; adjust/diagnose first.
- Provider/auth error -> stop and report the sanitized UI message; do not relogin unless separately authorized.

Final marker after successful preview:

`TELEGRAM_MTPROTO_M4BA1_ONE_FOLDER_PREVIEW_COMPLETE`

`CURRENT_TASK.md` is the source of active authorization.
