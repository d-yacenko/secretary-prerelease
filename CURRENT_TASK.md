# CURRENT_TASK

HOLD

## REL1D-HG4C — COMPLETE

### Result

Complete bounded People overview windowing via the existing graph window contract.

Implementation SHA: `ecad122956185e24c039215184aa0ca8e2cedb5e`

Files:
- `backend/app/services/person_graph_workspace_service.py`
- `backend/app/api/routes/graph_workspace.py`
- `backend/app/api/schemas.py`
- `backend/tests/test_person_graph_workspace.py`
- `client/lib/api/secretary_api_client.dart`
- `client/lib/graph/graph_workspace_controller.dart`
- `client/lib/graph/graph_workspace_screen.dart`
- `client/test/graph/people_overview_window_test.dart`

### Behavior

- Unrooted People overview pages by `seed_limit` (default 12): salience-ranked positive prefix first, then remaining active People by title/id.
- Window metadata (`window_index` / `window_count` / previous/next) and `truncated` for multi-window overviews.
- Out-of-range `window_index`, and nonzero window with `root_id` or search `q`, return HTTP 422 containing `window index is out of range`.
- Client passes `window_index` only for unrooted People overview; Tasks and People keep independent overview window indexes; UI uses People wording (`Люди · страница N из M`).
- Shared OOR fallback in overview load recovers to page 0.
- `DEFAULT_SEED_LIMIT` / `MAX_RANKED_PEOPLE` unchanged; rooted/search/HG4B actor feedback unchanged.

### Checks

- `python3 -m pytest tests/test_person_graph_workspace.py`: 12 passed
- Focused Flutter suite (`people_overview_window`, `person_task_bridge`, `graph_semantic_window`, `relation_target_label`, `graph_relation_target_disambiguation`): 45 passed, 0 failed
- Ruff on touched backend files: PASS
- `dart analyze` on touched client files: 0 errors (pre-existing info only)
- `git diff --check` clean

### Boundaries

No production deploy, schema/Alembic, salience redesign, role-import image extraction, or next phase.

No next coding phase is authorized by this HOLD.
