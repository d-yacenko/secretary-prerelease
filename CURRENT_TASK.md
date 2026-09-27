# Current task — HOLD: human Direction visual validation

Task Stabilization S2 is accepted.

Implementation: `60c5157f8781dad82b555bf3b1642dd30267f430`.
Executor HOLD: `34aabf1ac2e6b24ea9ab22d9c4aa23ee8c0f559f`.

No coding task is active.

Human visual gate on current main:

- create several Tasks as `Направление` (ongoing) through the manual Capture screen;
- create several ordinary finite Tasks;
- edit one finite Task to `Направление`;
- edit one ongoing Direction back to finite;
- verify save succeeds and mode persists after refresh;
- compose finite Tasks under Directions using confirmed `part_of`;
- create at least one ongoing Direction under another ongoing Direction using confirmed `part_of`;
- open Graph overview and rooted views and inspect:
  - ongoing circle vs finite card distinction;
  - hierarchy readability;
  - parent/child direction;
  - spacing and overlap;
  - spatial stability after refresh/re-root;
  - behavior with several Directions at once.

Please capture screenshots and concrete observations, especially anything that feels confusing or visually wrong.

Important environment boundary:
- use current-main backend + current-main client;
- do not point this validation at production, which remains on the older production ref/schema.

Do not start S3.
Do not start H2D.
Do not deploy production.

STOP until the human visual gate is reviewed.
