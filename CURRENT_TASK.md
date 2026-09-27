# Current task — HOLD: rerun Direction visual gate on current-main backend

Task Stabilization S2 remains accepted at the code/test level.

The first human visual attempt is INCONCLUSIVE because the client was connected to an older backend contract.

Observed symptoms:
- editing to `ongoing` returned `extra_forbidden` for `completion_mode`;
- manual create with `Направление` produced an effective finite Task;
- Task profile failed to load.

These match the old production backend exactly:
- production ref `296b4735f9473ea60ef22f1827ed94260603128e` does not accept `completion_mode` in Task PATCH;
- old Capture request does not know the field and can silently ignore it;
- old tasks router has no Task profile endpoint.

Do not treat this as an S2 code failure.

Human gate must be rerun with:
- backend from current `main`;
- DB upgraded to current head / Alembic 0050;
- client from current `main`;
- client configured to that current-main backend, NOT production.

Then verify:
- create `Направление` persists `completion_mode=ongoing`;
- edit finite -> ongoing succeeds and survives refresh;
- edit ongoing -> finite succeeds and survives refresh;
- ongoing renders as the Direction/circle presentation even though its canonical Object `kind` remains `task`;
- Task profile loads;
- several Directions plus finite child Tasks can be inspected visually;
- ongoing -> ongoing `part_of` hierarchy is readable.

Capture screenshots/observations after the environment is corrected.

Do not start S3.
Do not start H2D.
Do not deploy production.

STOP until the rerun is reviewed.
