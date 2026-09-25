# Current task

HOLD

Graph Refined P6R concrete route-preference correction is implemented at `900b130db448721be20154a28050002f2036baf6`.

A `user_route_choice` marks only the concrete route whose provenance key matches. Another conversation of the same identity stays unpreferred. Recording a choice uses the route category implied by that key, so unrelated routes cannot hide it.

Focused checks: `tests/test_person_routes.py` 14 passed; `tests/test_person_assistant.py` 36 passed; `tests/test_person_enrichment.py` 20 passed; `tests/test_person_salience.py` 9 passed; `tests/test_person_evidence_ledger.py` 6 passed; `tests/test_person_identity.py` 12 passed; `tests/test_tool_gateway.py` 28 passed. Combined with `tests/test_safe_external_actions_a.py`, `tests/test_unified_communications_a.py`, and `tests/test_exact_object_email_reply.py`: 236 passed. Ruff and compile of touched Python passed. `git diff --check` clean.

No migration. Production remains `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`.

Do not deploy. Do not choose the next roadmap stage.
