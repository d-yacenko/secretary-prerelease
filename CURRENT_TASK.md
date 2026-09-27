# Current task — HOLD

Task Stabilization S1 is complete.

Implementation: `d95d7086c4b9113fd8896e370308f3f52464a2be`.

Deleted Task mutation is rejected for both tombstone and legacy `status=deleted`. Repeat delete is a no-op and does not write a tombstone onto a legacy row.

Do not start S2.
Do not start H2D.
Do not deploy production.
