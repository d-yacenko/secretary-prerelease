# Current task — HOLD

REL1A, REL1A.1, REL1A.2, and REL1A.2.1 are **ARCHITECT SOURCE-ACCEPTED**.

The emergent Person role vocabulary, reversible role assignments, consolidation preservation, Unicode lexical-identity hardening, and query-bound reuse-first role autocomplete are complete in source.

Do not deploy, migrate production, install/replace the client, or start REL1B/REL1C/REL1D from this HOLD without fresh explicit user/Architect authorization.

## Accepted implementation

- REL1A: `e7f1e79dd83e3007bc97a6dff7aa1bd083128d93`
- REL1A.1 consolidation corrective: `9de2cccd218b76c04e98049b7bcc86c36a4058fe`
- REL1A.2 Unicode lexical-identity hardening: `5b2e19c8f386225c262be4b3a551096f0427d6fc`
- REL1A.2.1 query-bound autocomplete corrective: `783d574264239b868a5fae9644cd76b00ad38236`
- Executor HOLD after REL1A.2.1: `d14e016ce1dd73e8ceab37b1918a5faa476c44ad`
- Repository Alembic head: `0054`

## Architect acceptance notes

REL1A semantics remain:

- RoleTerm is an emergent user-scoped reusable vocabulary, not a closed dictionary;
- exact lexical identity is trim + Unicode whitespace collapse + Unicode `casefold()`;
- semantic near-duplicates remain distinct;
- role context is separate free text;
- active assignment cap remains 16 per Person;
- retract preserves history;
- role facts are not graph edges, Task actor roles, hierarchy, authority, salience, or deterministic importance weights;
- Person consolidation preserves missing active role assignments with reversible audited copy/undo semantics.

REL1A.2 is accepted:

- additive Alembic `0054` widens `normalized_key` to 360 and `context_key` to 600;
- display bounds remain 120 and 200;
- `0053` was not rewritten;
- full canonical case-fold keys are stored, not truncated;
- runtime canonical-key overflow fails before persistence;
- server search exposes authoritative `exact_match_term_id` independently of bounded suggestion-page inclusion.

REL1A.2.1 is accepted:

- changing role text immediately invalidates prior-query suggestions and exact-match state;
- while the current query is unresolved, no previous suggestion is shown and create-new is hidden;
- create-new is shown only after the current non-empty query has an authoritative server result with no exact match;
- stale older responses cannot publish terms or exact-match state over a newer query;
- failed search does not restore stale prior-query truth;
- backend remains the sole lexical-identity authority.

Architect review confirmed the REL1A.2.1 implementation changed only:

- `client/lib/graph/person_roles_section.dart`;
- `client/test/graph/person_roles_section_test.dart`;

plus ledger files. Backend/schema were not changed.

## Accepted verification evidence

REL1A.2 backend-focused regression:

- 124 passed, 0 failed.

REL1A.2 client evidence:

- 17 passed, 0 failed before the final query-binding corrective;
- focused analyze: 0 errors;
- Linux debug build: PASS, not installed.

REL1A.2.1 client evidence:

- role + People overview/create tests: 21 passed, 0 failed;
- `flutter analyze client/lib/graph/person_roles_section.dart`: no issues;
- `flutter build linux --debug`: PASS, not installed;
- `git diff --check`: clean.

## Production boundary

Production remains unchanged:

- backend/source: `2314bf72101fbd83d50a7b264154d73740e28db1`;
- Alembic: `0052 / 0052`;
- installed Linux client source: `2314bf72101fbd83d50a7b264154d73740e28db1`.

No production deploy, production migration, client install, real model call, or provider action was performed by REL1A.2 / REL1A.2.1.

## Explicitly not yet done

- production migration `0052 -> 0054`;
- backend deployment containing REL1A;
- exact-release Linux client rebuild/install containing REL1A;
- human UI acceptance of role reuse/create/context/retract;
- REL1B role-aware personal relevance / importance evidence;
- REL1C Assistant role read/write;
- REL1D grounded screenshot/document role import;
- Organization ontology.

## Recommended next decision

The next product step remains a **controlled REL1A rollout**, but it requires fresh explicit production authorization.

After rollout, perform human acceptance of:

1. reuse an existing role;
2. create a genuinely new role;
3. add optional context;
4. verify Unicode/exact lexical reuse;
5. retract a role;
6. verify Person card/detail presentation.

Only after that human gate should REL1B start unless the user explicitly chooses another order.

## HOLD

Do not deploy, migrate, install client, or start another product slice until explicitly authorized.
