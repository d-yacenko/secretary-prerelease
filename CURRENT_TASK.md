# Current task — HOLD

Graph G1 is complete.

Implementation:
`057e5a649f89b97d41bfa6158f6477dddd0e4592`

The human Graph symptom was bounded projection, not deletion of confirmed user relations. Ordinary neighbors are ordered by creation time, a Task admitted that way closes its confirmed `part_of` component before later optional neighbors, and the selected object's direct relation list comes from `GET /objects/{id}/neighbors`.

No schema change. Production was not deployed and remains:
`fd45df20ff53ad973f22e461ff84f3cb5c251b8a`

S2R and G1 can be rolled out together schema-neutrally. That rollout is not authorized here.

Do not start S3 or H2D.
