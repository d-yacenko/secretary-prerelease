# Current task — Flow Media F2: media-processing contract + Telegram voice/audio transcription

Flow Media F1 is architect-accepted. Implement the next bounded vertical slice: a provider-neutral media processing contract and end-to-end Telegram MTProto voice/audio transcription.

Do not implement Mattermost/Teams media downloads in this task. Do not add UI, proactive behavior, Task Refinement, OCR, image/video understanding, or production deployment.

Known unrelated baseline failures remain outside this task:
- stale Alembic-head expectation in `tests/test_teams_a.py::test_migration_0040_revises_0039`;
- Inbox contract mismatch around `conversation_groups` in `tests/test_inbox_source_chronology.py::test_inbox_api_order_hides_attachments_and_keeps_contract`;
- previously documented Assistant baseline failures around `pending_action_plan` JSON expectation and `ai_traces_user_id_fkey`.

## Goal

A canonical F1 media child Object with `media_kind in {"voice","audio"}` should be processable through one provider-neutral pipeline:

1. validate media Object + parent communication + AI/provider eligibility;
2. fetch bounded media bytes through a provider adapter;
3. transcribe through the existing Secretary transcription provider stack;
4. persist transcript as canonical Representation/evidence on the media child Object;
5. optionally enqueue existing downstream embedding/summarization only where current policy safely allows it;
6. remain idempotent and auditable.

Telegram MTProto is the only real provider adapter required in F2.

## 1. Provider-neutral media processor contract

Add a service/domain boundary such as `CommunicationMediaProcessingService`.

It should accept an existing media child Object id and:
- load same-user active media child;
- require `kind="file"`;
- require F1 metadata with parent communication id, provider, media_kind, descriptor/provenance;
- support only `voice` / `audio` for transcription in F2;
- locate and validate the active parent communication Object;
- delegate byte retrieval to a provider-specific fetch adapter;
- enforce byte/content limits before model call;
- run transcription;
- persist transcript deterministically;
- return a bounded result/status.

Do not put provider HTTP/session logic directly into the generic processor.

## 2. Transcript persistence

Persist the transcript on the **media child Object**, not by overwriting the parent message body.

Prefer the existing Representation model:
- introduce/use a clear representation kind such as `transcript`;
- one effective transcript representation per media Object/version;
- transcript text remains bounded by existing representation/indexing rules;
- metadata records safe provenance such as model identifier and source content hash/revision where available;
- do not store raw provider tokens or decrypted session material.

A repeated run over unchanged bytes/model input must not create duplicate transcript rows.

If bytes/revision change, replace/supersede the effective transcript deterministically using existing representation-generation/content-revision conventions where practical.

Do not create a separate transcript Object unless current architecture proves that necessary.

## 3. Reuse existing transcription stack

Do not create another OpenAI transcription client.

Refactor/reuse current transcription logic so background media processing uses the same:
- `TranscriptionProvider`;
- OpenAI transcription model setting;
- per-user effective OpenAI credential;
- `OpenAIDailyBudgetGuard`;
- AI audit / `WORKLOAD_TRANSCRIPTION` trace semantics;
- provider error taxonomy;
- bounded audio-size constants.

The existing `/assistant/transcribe` endpoint must remain backward compatible.

If useful, extract a shared `transcribe_audio_bytes(...)` primitive from `transcribe_audio_upload` rather than duplicating logic.

## 4. Telegram MTProto fetch adapter

Extend the MTProto transport with one narrow read operation to fetch bytes for an already-known media descriptor.

Required input is derived from persisted F1 provenance, never model text:
- account id;
- peer id;
- message id;
- expected provider media id;
- expected media category.

Requirements:
- fetch exactly that Telegram message through the existing encrypted account/session path;
- verify returned message id / peer / media identity match persisted provenance;
- accept only voice/audio media for F2;
- download at most the configured transcription byte limit (+1 for overflow detection if needed);
- reject empty/oversized/mismatched media;
- do not follow arbitrary URLs;
- do not expose decrypted session/provider references outside transport/service scope;
- classify provider/auth/transient failures consistently with existing MTProto errors.

Prefer Telethon in-memory byte download or a bounded temporary-file path that is deleted immediately. Do not leave provider media files on disk after processing.

## 5. Telegram AI quarantine is a hard prerequisite

This is the most important F2 invariant.

A Telegram media child may be transcribed only when its **parent canonical MTProto message** is currently AI-eligible under the existing `telegram_mtproto_ai_eligible` policy.

Therefore:
- with `TELEGRAM_MTPROTO_AI_ENABLED=false`, inbound Telegram voice/audio must NOT be downloaded or sent to transcription;
- existing permitted self-authored outbound scope may be transcribed if the parent passes the current policy;
- with the gate enabled in a permitted scope, eligible inbound media may be processed;
- do not make the child Object itself AI-visible merely to process it;
- processing eligibility must be derived from the parent message + ownership/scope, not from the fact that the child exists.

Add a dedicated helper if needed, e.g. `telegram_media_processing_eligible(parent)`, but do not weaken `telegram_mtproto_ai_predicate`.

## 6. Job/queue integration

Add a bounded job such as `transcribe_communication_media` for async processing.

Requirements:
- payload contains only media Object id and safe expected revision/signature fields;
- user_id comes from Job ownership;
- enqueue is idempotent for the same media revision;
- worker checks object still active and eligible before provider fetch/model call;
- if parent becomes ineligible before execution, job exits safely without download/model call;
- OpenAI daily budget exhaustion uses the existing worker parking behavior where applicable;
- provider transient failures use normal retry semantics;
- permanent validation/policy mismatch should not retry forever.

Do not make media transcription a recurring source job.

## 7. Automatic enqueue policy

F2 may automatically enqueue transcription only for media children satisfying all of:
- media_kind is voice/audio;
- parent is active;
- provider supports F2 adapter (Telegram only in this task);
- current AI eligibility permits processing.

For Telegram:
- if AI gate is false and message is inbound/non-self-authored, no transcription job should be created;
- later enabling the gate does not require redesign, but backfill/reconciliation may be a later task. F2 does not need a full historical backfill scheduler.

No transcription job for document/photo/video in F2.

## 8. Search/retrieval behavior

After a transcript exists:
- media Object may become semantically useful through its transcript Representation;
- do not add the child as a standalone Inbox item;
- do not overwrite parent message text/title;
- do not automatically inject transcript into Assistant prompts through a special bypass;
- existing representation-aware retrieval/search may use it only under normal AI/privacy eligibility.

For Telegram, any retrieval path using transcript must still require parent-derived AI eligibility. If current generic representation retrieval would expose a Telegram media child despite the parent gate, add a narrow eligibility predicate for media children rather than making all Telegram files globally visible.

## 9. Content revision/idempotency

Compute a stable content revision/hash from downloaded bytes.

Store safe metadata on the media child such as:
- content_hash/revision;
- transcript model/version;
- transcription status timestamps if useful.

If the same media bytes are processed again:
- do not call transcription provider again when an equivalent transcript already exists for the same revision/model;
- do not duplicate representations.

If provider media identity no longer matches descriptor/provenance:
- fail closed;
- do not silently transcribe a different message/file.

## 10. No provider expansion in F2

Mattermost and Teams media children stay metadata-only in F2.

Do not add:
- Mattermost file download endpoint;
- Microsoft Graph attachment/drive download;
- email attachment transcription;
- image/video models.

Those should later plug into the same processing service through separate bounded fetch adapters.

## Focused proof

Add tests proving at minimum:

1. Eligible Telegram voice child -> bounded byte fetch -> one transcript Representation.
2. Eligible Telegram audio child works equivalently.
3. Replay with unchanged bytes/model is idempotent: no second provider transcription call and no duplicate transcript.
4. Changed bytes/revision replaces/updates transcript deterministically.
5. Empty media fails before transcription.
6. Oversized media fails before transcription.
7. Message/media-id mismatch fails closed.
8. Cross-user media child fails closed.
9. Deleted/rejected parent or child is not processed.
10. With Telegram AI gate false, inbound voice/audio causes zero media download and zero transcription call.
11. With gate false, existing self-authored eligible Telegram scope may be processed according to current policy.
12. With gate enabled + eligible scope, inbound voice/audio may be processed.
13. Child remains absent from Inbox.
14. Parent message body/title are unchanged by transcription.
15. Transcript is persisted on child Representation with safe provenance only.
16. Job enqueue is deduplicated by media revision/signature.
17. Job rechecks eligibility at execution time.
18. Daily-budget exhaustion follows existing worker parking behavior.
19. Existing `/assistant/transcribe` tests remain green.
20. F1 media tests remain green.
21. Telegram AI policy tests remain green.
22. Graph Refined focused tests remain green.
23. No Mattermost/Teams media download or Task Refinement/UI/deployment work is introduced.

Prefer no migration if Representation + Object metadata + Job are sufficient.

Run focused media/transcription/Telegram/job tests, existing Assistant transcription tests, F1/provider normalization tests, Graph Refined focused tests, Ruff/compile on touched Python, and `git diff --check`.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.
- Do not begin Mattermost/Teams media-download adapters, Task Refinement, or deploy.
