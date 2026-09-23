# Current task — Terminate the currently running Telegram E2E attempt only

## Human authorization

Explicit human authorization received to terminate the currently running live self-authored Telegram E2E attempt.

This authorization is ONLY for termination of the already-running attempt.

It does NOT authorize:
- any retry;
- any second invocation;
- direct production SSH;
- manual production Docker/Compose;
- provider diagnostics;
- production DB writes;
- deploy/restart/recreate;
- production env changes;
- production ref movement.

Known local process chain from the human's read-only inspection:

- wrapper Python PID: `2940596`;
- child SSH PID: `2940620`;
- Cursor shell parent PID: `2940552`.

At inspection time, wrapper and SSH had been alive for about 1h44m, both sleeping in `do_sys_poll`, with the SSH TCP session still ESTABLISHED.

## Authorized termination

Terminate only the current child SSH process first so the existing remote execution channel is closed.

Use exact PID targeting only:

```bash
kill -TERM 2940620
sleep 2
ps -o pid,ppid,etime,stat,wchan:24,cmd -p 2940620,2940596
```

If PID `2940620` is gone, do not send any stronger signal to it.

If PID `2940620` is still present after the TERM grace period, a targeted:

```bash
kill -KILL 2940620
```

is authorized for that PID only.

After the SSH child is gone, allow the wrapper PID `2940596` a short opportunity to return naturally.

Then inspect:

```bash
ps -o pid,ppid,etime,stat,wchan:24,cmd -p 2940596
```

If PID `2940596` remains after its SSH child is gone, a targeted:

```bash
kill -TERM 2940596
```

is authorized for that PID only.

Do not signal the Cursor shell PID `2940552` unless separately instructed.

## Report

Return:
- which signals were actually sent;
- final `ps` output for PIDs 2940620 and 2940596;
- any stdout/exit-status that the existing shell emitted after termination.

Then STOP.

No retry is authorized.
