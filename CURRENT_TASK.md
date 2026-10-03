# Current task — HOLD

REL1A + REL1A.1 are **ARCHITECT SOURCE-ACCEPTED**. The emergent Person role vocabulary and manual assignment surface are complete in source. Do not deploy, migrate production, install the client, or start REL1B/REL1C/REL1D from this HOLD without fresh user/Architect authorization.

## Accepted implementation

- REL1A implementation: `e7f1e79dd83e3007bc97a6dff7aa1bd083128d93`
- REL1A.1 consolidation corrective: `9de2cccd218b76c04e98049b7bcc86c36a4058fe`
- Executor HOLD before Architect acceptance: `75134209312d614c8a78ae5320a07e5ea653ed25`
- Schema head: Alembic `0053`
- Production backend remains: `2314bf72101fbd83d50a7b264154d73740e28db1`
- Production Alembic remains: `0052 / 0052`
- Installed Linux client remains production-source build `2314bf72101fbd83d50a7b264154d73740e28db1`

## Accepted product semantics

Person roles are an emergent user-scoped vocabulary, not a closed application dictionary and not a hierarchy.

Canonical model:

- `person_role_terms` — reusable per-user RoleTerm vocabulary;
- `person_role_assignments` — durable Person -> RoleTerm assignment with optional context and provenance.

Examples:

- `директор`
- `студент`
- `заведующий кафедрой`
- `главный бухгалтер`

A new real-world role requires no application code/schema change.

### Lexical identity

Exact lexical identity only:

- trim;
- collapse whitespace;
- case-fold normalized key.

Thus `Директор`, ` директор `, and `ДИРЕКТОР` reuse one RoleTerm.

Semantic near-duplicates remain distinct:

- `директор`
- `генеральный директор`
- `директор компании`

No stemming, fuzzy matching, embeddings, translation, or automatic synonym merge defines RoleTerm identity.

### Assignment semantics

- one Person may have multiple active roles;
- one RoleTerm may be reused by many Persons;
- same role in different contexts is allowed;
- exact normalized role + context repeat is idempotent;
- optional context remains free text;
- active assignment cap is 16 per Person;
- retract preserves assignment history and leaves RoleTerm reusable;
- role facts create no graph Edge;
- role facts do not change salience, importance, Task actor semantics, approval authority, or hierarchy.

### People UX

Rooted Person detail has a `Роли` section.

Manual entry is reuse-first:

- autocomplete/search existing RoleTerms;
- exact existing lexical term is reused;
- genuinely new text has explicit `Создать роль «…»`;
- no separate role-dictionary administration screen is required;
- optional context can be entered;
- compact Person presentation can show role summary without changing graph topology.

### Person consolidation

REL1A.1 makes roles part of reversible Person consolidation truth:

- active duplicate roles missing on survivor are copied using the same RoleTerm;
- semantic identity is `role_term_id + context_key`;
- exact overlap creates no duplicate survivor assignment;
- different contexts remain distinct;
- no new RoleTerm and no graph Edge is created during merge;
- merge preflight fails before mutation if resulting active role count would exceed 16;
- duplicate's original role assignment rows remain untouched under the tombstoned Person;
- merge audit records created survivor assignments;
- undo retracts only merge-created survivor copies;
- survivor assignments that pre-existed the merge remain untouched;
- undo fails closed if a merge-created role row is missing/retracted/diverged from its audited fields;
- repeated established merge does not copy roles again.

### API truth

Typed role assignment responses/projection expose:

- assignment id;
- owning `person_id`;
- RoleTerm id;
- display role;
- context;
- origin;
- state.

Public role retract requires an active current-user Person. Rejected, deleted, foreign, or merged-away Persons fail closed.

## Verification accepted

Executor evidence:

- REL1A initial role test: 12 passed;
- REL1A.1 consolidation + role tests: 30 passed;
- combined backend focused regression after corrective: 119 passed;
- Flutter role/People tests: 16 passed;
- focused Flutter analyze: 0 errors; 7 pre-existing infos in `graph_workspace_screen.dart`;
- Linux debug build: PASS, not installed;
- Ruff: PASS;
- `git diff --check`: PASS.

Architect source review additionally verified:

- role projection is batched rather than per-Person N+1;
- merge copies role assignment fields including context, origin, provenance, and source_object_id;
- no RoleTerm recreation in merge;
- undo audit compares full merge-created role payload;
- public retract checks active Person boundary;
- `person_id` is present in backend/client typed assignment model.

## Explicitly not yet done

- production migration `0052 -> 0053`;
- backend deployment containing REL1A;
- Linux client rebuild/install containing REL1A;
- human UI acceptance of role autocomplete/create/retract;
- REL1B role-aware importance evidence;
- REL1C Assistant role read/write;
- REL1D screenshot/document import;
- Organization ontology.

## Recommended next decision

Because the user's immediate goal is to actively populate the People graph, the next useful step is a controlled REL1A rollout:

1. explicit production authorization;
2. production migration `0052 -> 0053` + backend rollout;
3. exact-release Linux client build/install under separate/explicit authorization if required by rollout contract;
4. human acceptance:
   - add existing/reused role;
   - create genuinely new role;
   - add optional context;
   - verify duplicate lexical reuse;
   - retract;
   - verify Person card/detail presentation.

Only after that human gate should REL1B be started unless the user explicitly chooses a different order.

## HOLD

Do not deploy, migrate, install client, or start another slice until explicitly authorized.
