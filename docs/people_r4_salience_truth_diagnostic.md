# People R4-H1 salience truth diagnostic

Diagnostic only. No product behavior, schema, cap, candidate rule, or production data was changed.

Checked against `main` at the H1 authorization `86bd1a8525ba1788ff3d321ff3fe0b4bc4319c97`. Production/runtime and `origin/production` remain `8cf5f3a14dd2eb70dc754d87b2f90a7589aa8b4f`. Rollback remains `1b851f91bd37d0e79531ef740b02febb3c3af69d`. Alembic remains `0050`.

The observed human symptom is explained by code and by a local synthetic reproduction. No production row was read.

## 1. Exact paths and limits

Rooted People detail is `PersonGraphWorkspaceService._presentation` with `include_truth`. That one read does three different communication/salience things:

| Surface | Path | Window | Row cap |
| --- | --- | --- | --- |
| `recent_communication_count` | `PersonAssistantService.count_attributable_communications(..., include_quarantined_telegram=True)` | `PERSON_LOOKBACK_DAYS = 90` | `MAX_PERSON_SCAN_ROWS = 400` (`PERSON_SCAN_CHUNK * 10`) |
| `recent_communications` | `find_communications` with limit 8, same Telegram flag | same 90 days | same 400 examined rows |
| salience components | `PersonSalienceService.evaluate` | `WINDOW_DAYS = 90` | `MAX_SCAN_ROWS = 200` newest communication Objects globally |

`evaluate` and overview `rank` share `_load_communication`. It orders by `coalesce(occurred_at, created_at)` descending, then object id, and keeps 200 rows. If a 201st in-window row exists, `truncated` is true and that row is not scored.

`score_person` always emits the five communication components even when every hit was dropped: `directness`, `reciprocity`, `frequency`, `recency`, `public_exposure`. Confirmation adds `user_attention` 20 (`CONFIRMATION_POINTS`). A route choice would add 8 more. `task_calendar` is 16 only when `_task_calendar_people` finds an edge. `claims_object_importance` stays false.

Per-person hit caps inside the scanned rows are `MAX_DIRECT_HITS = 8` and `MAX_PUBLIC_HITS = 8`. Those caps set `truncated` only after some hits have already been kept, so they cannot by themselves turn every communication component to zero.

Email and Yandex direction is one function, `person_salience._email_direction`, used by both salience hits and `PersonAssistantService._direct_role`.

## 2. Reproduction

A temporary local test drove `PersonGraphWorkspaceService.get_workspace` for a fresh user. It was not committed, because it would freeze today's misleading split as a desired assertion. Each case used one effective exact email, one explicit confirmation, and synthetic Yandex messages only.

Scan position, with the attributable inbox message strictly older than N unrelated newer inbox messages:

| Newer unrelated rows | Count | Recent Flow rows | `salience.truncated` | Communication components | `user_attention` |
| --- | --- | --- | --- | --- | --- |
| 199 (message is row 200) | 1 | 1 | false | non-zero (`directness` 32) | 20 |
| 200 (message is row 201) | 1 | 1 | true | all zero | 20 |
| 399 (message is row 400) | 1 | 1 | true | all zero | 20 |
| 400 (message is row 401) | 0 | 0 | true | all zero | 20 |

The 199/200 pair is the off-by-one boundary. Row 200 is still scored. Row 201 is visible to the assistant scan and invisible to salience. Row 401 disappears from both.

Single-message Yandex cases, with no newer noise, so scan position is not the cause:

| Stored shape | Assistant count / Flow | Salience |
| --- | --- | --- |
| `folder=inbox`, one recipient | 1 / 1 | direct inbound, `directness` 32 |
| `folder=inbox`, two recipients | 1 / 1 | public inbound, `public_exposure` 4, `directness` 0 |
| `folder=inbox`, sender only | 1 / 1 | public inbound, `public_exposure` 4 |
| `folder=sent`, Person is the sole recipient | 1 / 1 | direct outbound, `directness` 32 |
| `folder=Отправленные`, Person is only the sender | 0 / 0 | no hit |
| `folder=Archive` | 0 / 0 | no hit |
| `folder=Входящие` | 0 / 0 | no hit |

Task/calendar cases on the same rooted read:

| Stored shape | `task_calendar` | Rooted task involvement |
| --- | --- | --- |
| Task title/body and calendar body mention the address; no edge | 0 | empty |
| Confirmed Task→Person `involves` on an open Task | 16 | one row |
| Person→`calendar_event` `related_to` | 16 | empty |
| Task→Person `waiting_on` on a `done` Task | 16 | empty |

Existing suites after the temporary test was removed: `test_person_salience.py`, `test_person_assistant.py`, `test_person_truth_surface.py`, `test_person_graph_workspace.py`, `test_person_c3_communication_count.py` — 67 passed.

## 3. 400-versus-200 hypothesis

Confirmed for the reported shape.

A rooted card can show `recent_communication_count = 1`, one recent Flow row, `user_attention = 20`, and zeros for directness, reciprocity, frequency, recency, and public exposure, with `salience.truncated = true`, exactly when that message is among global communication rows 201..400. It is not an off-by-one illusion: row 200 still scores, row 201 does not.

This is sufficient. It is not the only way a component can be zero, but it is the way all communication components become zero while the message remains visible.

## 4. Other attribution mismatches

For email/Yandex, a message the assistant accepts is a message salience would also accept if the row is inside the 200. Both paths use the same folder rule and the same sender/from versus to/cc/recipients normalization. Archive, a non-`inbox` localized inbox name, and a sent copy where the Person is only the sender are absent from both surfaces. They do not explain a visible message with a zero public component.

The remaining differences do not produce that symptom:

- Two recipients, or an inbound message with an empty audience, still count as one assistant communication, but salience records `public_exposure` rather than `directness`. Public exposure is non-zero when the row is scanned.
- Assistant conversation-anchor matching applies to Mattermost DMs and Teams one-on-one chats, not to email.
- The per-person hit cap can set `truncated` while leaving earlier hits scored. It cannot zero every communication component and still show the only attributable message.

No candidate-rule defect was found. An identity already attached to the rooted Person is skipped by `find_identity_candidates`. Absence of «Возможные контакты» is expected under the current conservative rules and is not evidence that R4 should widen matching.

## 5. Meaning of `task_calendar = 0`

`task_calendar` is 16 when any non-rejected edge connects this active Person to an active `task`, `event`, or `calendar_event`, in either direction, of any edge type. `evaluate` does not apply the rank-pool cap of 20, and it does not exclude terminal Tasks.

It is 0 when no such edge exists. A Task or calendar Object whose title or body mentions the Person or the email does not count. Textual co-occurrence is not a relationship.

Rooted «Участие в задачах» is narrower. It lists only non-terminal Task→Person edges of type `requested_by`, `delegated_to`, `waiting_on`, or `involves`. A reverse or non-actor edge, and an actor edge on a terminal Task, can still set `task_calendar` to 16 while that list stays empty. The opposite is not true: an empty involvement list plus `task_calendar = 0` means the service found no Person-work edge at all. That reading is semantically correct. Remembered Task context without an explicit edge must stay zero.

## 6. Hidden `truncated`

`salience.truncated` is already on `PersonSalience` and on the rooted API object (`truncated`, plus `window_days`). `PersonSalienceSummary` parses it. The rooted activity section does not read it. It prints the tier, the score, the disclaimer, and each component as `label: value`. A bounded miss therefore looks like a measured zero: «Прямые диалоги: 0», «Общие каналы: 0», and the other communication lines, next to a real recent message and next to «Подтверждение: 20».

`recent_communications_truncated` is shown («Показаны не все сообщения»). Salience has no equivalent sentence.

## 7. Smallest correction options

These are options, not an implementation.

1. Disclosure only. When rooted `salience.truncated` is true, say the activity numbers come from a bounded scan. Leave the 200/400 split in place. Zeros stay numerically wrong relative to the visible message, but they stop looking complete.
2. Rooted scan alignment. For the rooted `evaluate` read only, score communication hits from the same 90-day, 400-row examination the recent-Flow projection already uses. Leave overview `rank` on the existing 200-row scan. Keep `truncated` when either the shared examination or the per-person hit cap is incomplete, and show that flag. Do not raise the assistant cap. Do not change Yandex folder rules.
3. Do not infer Task or calendar salience from titles, bodies, or email strings. If a later slice wants remembered work to count, it has to use an explicit edge, which is a separate decision.

Option 2 plus the disclosure in option 1 is still a truthfulness correction. It is not a new salience model.

## 8. Recommended next slice

Authorize one narrow rooted-truth slice only:

- score the rooted Person's communication salience from the communication rows the rooted projection already examines (`MAX_PERSON_SCAN_ROWS`, 90 days);
- leave `rank` and overview ordering on the current 200-row scan;
- show `salience.truncated` on the rooted activity section when the scan or hit cap is incomplete;
- do not change folder rules, candidate rules, Task inference, caps above 400, schema, or production.

No broader redesign is required to explain or to correct this discrepancy.
