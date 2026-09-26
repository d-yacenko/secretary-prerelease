# Relation direction audit — V8D1

Diagnosis only. No stored edge was reversed, no migration was added, and `presentGraphMapEdge` was not changed.

Canonical contract used for current code:

| Type | Source | Target | Arrow |
| --- | --- | --- | --- |
| `related_to` | storage order is not semantic | storage order is not semantic | none |
| `references` | the object that references | the referenced object | source -> target |
| `depends_on` | the dependent | the prerequisite | source -> target |
| `part_of` | the child | the parent | source -> target |
| `contains` | no new meaning assigned | no new meaning assigned | whatever the writer stored |

`GraphService.create_edge` copies `source_id` and `target_id` onto the row. It does not swap endpoints. `part_of` is additionally validated as child -> parent.

## Writer matrix

| Writer | Types | Source | Target | Origin / state | Contract | Tasks canvas | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `GraphService.create_edge` | caller type | caller id | caller id | caller | passthrough; `part_of` validated child -> parent | when the type is map-visible | current |
| `RelationService.create_relation` | `related_to`, `references`, `depends_on`, `part_of` | caller id | caller id | `user` / `confirmed` | passthrough; does not swap | yes, except hidden actor types | current |
| `TaskRelationService.add_dependency` | `depends_on` | the task argument (dependent) | `depends_on_task_id` (prerequisite) | caller, default `user` / `confirmed` | conforms | yes | current |
| `TaskRelationService.attach_evidence` | `references` | the task | the non-task evidence object | caller, default `user` / `confirmed` | conforms | yes | current |
| `TaskRelationService.add_actor` | `requested_by`, `delegated_to`, `waiting_on`, `involves` | the task | the person | caller | actor roles, not the canvas contract | no; these types are hidden | current |
| `DomainToolService._attach_evidence_references` | `references` | the task | each evidence object | `agent` / proposed or approved-confirmed | conforms | yes | current |
| `DomainToolService._attach_explicit_relations` | `depends_on` via `add_dependency` | the task being written | each `depends_on_task_ids` entry | `agent` / proposed or approved-confirmed | conforms | yes | current |
| `DomainToolService.link_objects` | caller type, including `part_of` | caller `source_id` | caller `target_id` | `agent` / proposed or approved-confirmed | does not swap; tool text says `part_of` source is the child | yes when the type is map-visible | current |
| `CaptureService` task capture | `references`, `depends_on` | the new task | pinned context, or the dependency task | `user` / `confirmed` | conforms | yes | current |
| `CorrelationService` proposal write | judge type, allowed `related_to` or `references` | the trigger object | the candidate | `agent` / `proposed` | trigger stays source | yes | current |
| `DeterministicRelationService` RFC `in-reply-to` / `references` | `references` | the citing message | the cited message | `source` / `observed`; metadata `source_fact=mail_reference` | conforms | only if an endpoint is a Task; mail↔mail is flow↔flow and hidden | current |
| `DeterministicRelationService` same Gmail thread | `related_to` | the trigger message | a thread peer | `source` / `observed`; metadata `source_fact=same_thread` | symmetric, so order is not an arrow | same flow↔flow hide | current |
| `CommunicationMediaService._link_contains` | `contains` | parent communication object | media child | `source` / `observed`; metadata `source_fact=communication_media` | legacy containment, container -> member | only if not flow↔flow | legacy |
| `EmailAttachmentService._link_contains` | `contains` | the email | the attachment | `source` / `observed`; metadata `source_fact=email_attachment` | legacy containment, container -> member | mail↔file is flow↔flow and hidden | legacy |
| `FolderContainmentService.link_files_to_folder` | `contains` | the folder | the file | `system` / `confirmed`; metadata `containment=local_root` | legacy containment, container -> member | only if not flow↔flow | legacy |
| Graph detail dialog «Добавить связь» | `related_to`, `references`, `depends_on` | the already selected object | the object chosen in the dialog | sent through `RelationService` as `user` / `confirmed` | the verb is about the selected object («Ссылается на», «Зависит от»); the client does not swap | yes | current |

`part_of` is not in the graph dialog dropdown. No current `contains` writer uses two Tasks. A Task↔Task `contains` row can exist only if an older or generic `create_edge` caller stored it.

Task Profile reads the same orientation: `depends_on` and `evidence` are outgoing targets, `dependent_tasks` are incoming sources, `parent_task` is the outgoing `part_of` target, and `child_tasks` are incoming `part_of` sources.

## Renderer

`presentGraphMapEdge` sets `directed` from the type (`related_to` is the only undirected type in this set). `dashed` is `depends_on`. `proposed` is `state == proposed` and does not change `directed`. The full-edge painter draws from the source border to the target border and places the arrowhead on the target. Compact hairlines set `arrowAtMark` only when the edge is directed and `targetId` is the Flow mark, so a Task->Flow arrow points at the Flow and a Flow->Task arrow points at the Task.

Existing proofs, left in place:

- `client/test/graph/graph_map_relation_test.dart`: `relation grammar keeps canonical direction`
- same file: `detail audit keeps source and target when the selection is either end`
- same file: `proposed relations keep type semantics and a midpoint cue`
- same file: `compact hairline follows the chosen canonical edge`
- `client/test/graph/hybrid_focus_lod_test.dart` audit strings for `references` and `depends_on`

V8D1 adds `compact depends_on arrow follows the canonical target` and the `depends_on` audit lines, including a proposed edge that still prints source -> target.

## Writer proofs already present

- Task evidence and dependency profile orientation: `backend/tests/test_task_relations.py` (`test_dependencies_evidence_and_legacy_edges`) and `test_assistant_profile_and_additive_task_writes` (profile `depends_on` / `evidence` from the tool writers).
- `part_of` tool and API stay child -> parent: `backend/tests/test_task_composition.py`.
- Correlation keeps the trigger as source: `backend/tests/test_correlation_26a.py` (`test_fake_judge_creates_proposed_edge`).
- In-Reply-To stores the citing message -> the cited message: `test_gmail_in_reply_to_creates_references`.

V8D1 adds `test_gmail_references_header_points_from_citing_message` for the RFC `References` header. It stores citing -> cited, `source` / `observed`, `source_fact=mail_reference`, and does not create the reverse edge.

## Local data

The configured database host is local. It contains 7 objects, 0 tasks, and 0 edges of `references`, `depends_on`, `part_of`, `contains`, or `related_to`. The screenshot tasks are not in this database. No production database was opened.

## Classification

`LEGACY_DATA_LIKELY`

The renderer does not reverse canonical direction, and every current specialized writer stores the contract direction. Generic `create_edge`, `RelationService`, and `link_objects` persist the caller’s endpoint order, so an older or manually reversed row remains visible as stored. This audit did not find a current writer that systematically swaps `references`, `depends_on`, or `part_of`. Screenshot rows were not available locally, so this is not a row-level proof that a particular arrow is bad data. It is the classification that follows from the code and tests.
