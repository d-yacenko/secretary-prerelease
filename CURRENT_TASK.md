# Current task

HOLD

Graph Refined P6 Person-aware route discovery and safe send-by-person is implemented at `1f8279a9c282ed150f384c5a9a62658eae1beb68`.

A resolved Person exposes bounded exact email and 1:1 chat routes. Several routes stay a choice. Existing `send_email` and `send_message` stage the exposed destination into the frozen pending action plan. Approval executes that frozen destination.

Focused checks: `tests/test_person_routes.py` 11 passed; `tests/test_person_assistant.py` 36 passed; `tests/test_person_enrichment.py` 20 passed; `tests/test_person_salience.py` 9 passed; `tests/test_person_evidence_ledger.py` 6 passed; `tests/test_person_identity.py` 12 passed; `tests/test_tool_gateway.py` 28 passed. Combined with `tests/test_safe_external_actions_a.py`, `tests/test_unified_communications_a.py`, and `tests/test_exact_object_email_reply.py`: 233 passed. Ruff and compile of touched Python passed. `git diff --check` clean.

No migration. Production remains `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`.

Do not deploy. Do not choose the next roadmap stage.
