# Current task — Flow Media F1: provider-neutral media child objects

Graph Refined / People & Identity is architect-accepted. Begin the next roadmap layer: media/voice as Flow ingestion.

Implement only the provider-neutral media foundation in this task.

Do not implement transcription, speech-to-text, media summarization, Assistant media reasoning, UI, proactive behavior, Task Refinement, live provider downloads, or production deployment in this task.

## Goal

Canonical communication Objects should be able to expose bounded provider media/attachment descriptors that materialize as deterministic child Flow Objects with provenance.

The foundation must support later voice/audio transcription without making voice a special parallel subsystem.

## 1. Canonical media child Object model

Introduce/reuse a provider-neutral service such as `CommunicationMediaService` that materializes child Objects for media/attachments belonging to a parent communication Object.

Prefer existing Object/Edge/Representation infrastructure.

For each child media Object, preserve bounded safe metadata such as:
- parent communication object id;
- provider;
- provider-native media/file id or stable descriptor key;
- media kind/category (voice, audio, document/file, photo, video, other as supported);
- filename when available;
- mime/content type when available;
- known byte size when available;
- duration where provider supplies it;
- occurred_at inherited from parent;
- provider provenance needed for a later bounded fetch, but no secrets/tokens.

Use a deterministic provider-scoped `external_id` so repeated sync is idempotent.

Child Object should normally be `kind="file"` or another already-supported resource kind; do not add a new top-level domain entity just for media.

## 2. Parent-child provenance

Create/reuse the existing containment relation used by email attachments:
- parent communication Object contains child media Object;
- relation is idempotent;
- child remains a Flow Object/evidence/resource, not a Task or Person.

Do not duplicate the parent message body into the child.

## 3. Provider-neutral descriptor contract

Add a small immutable descriptor/domain type, for example:
`CommunicationMediaDescriptor`

Suggested fields:
- provider
- descriptor_key
- media_kind
- provider_media_id
- filename
- mime_type
- size
- duration_seconds
- metadata/provenance dict limited to safe bounded route/fetch identifiers

The service should accept descriptors from any connector and perform the same materialization logic.

## 4. Telegram MTProto metadata only in F1

Extend MTProto history normalization/transport representation enough to preserve **media descriptors without downloading bytes**.

At minimum detect:
- voice note;
- audio;
- document/file;
- photo/video where safely identifiable.

For later provider fetch, retain only stable non-secret identifiers such as:
- account id;
- peer id;
- message id;
- media category;
- provider media/document id where available.

Do NOT download media in F1.
Do NOT transcribe it.
Do NOT expose Telegram inbound media/content to the model through a new path.

Telegram AI quarantine remains unchanged.

## 5. Mattermost metadata only in F1

Mattermost already preserves bounded `file_ids`.

Materialize one child media/file Object per bounded file id, with:
- server realm;
- file id;
- parent channel/post provenance;
- filename/mime/size only when already present in stored provider payload without an additional call.

Do NOT call Mattermost file-info/download endpoints in F1.

## 6. Teams metadata only in F1

Support only attachment/file descriptors already present in the canonical message payload without live Microsoft Graph fetches.

Do not treat quoted-message/reference attachments as media files.

If current Teams normalized data does not retain enough non-reference attachment metadata, add conservative bounded normalization for:
- attachment id/key;
- name;
- content type;
- safe content URL/reference identifier only if it contains no credential/token and is actually required for a future fetch.

Do not store expiring auth-bearing URLs or secrets.

## 7. Email parity

Email attachments already materialize child file Objects.

Do not rewrite that working subsystem broadly.

Where practical, reuse the new provider-neutral descriptor/materializer internally or align invariants/tests so email and communication media have the same:
- deterministic child identity;
- contains edge semantics;
- bounded metadata;
- no duplicate child on replay.

Avoid risky refactor if it does not improve correctness.

## 8. Idempotency and lifecycle

Required behavior:
- replay of the same parent/provider descriptor does not create duplicate child Objects or duplicate contains edges;
- metadata refresh may update safe descriptive fields;
- parent soft deletion/rejection does not physically delete historical media child Objects unless existing object lifecycle rules already require it;
- cross-user parent or child mutation fails closed;
- provider-native ids are namespaced enough to avoid collisions across accounts/realms/conversations.

## 9. No content fetch or ML in F1

Absolutely no:
- remote media byte download;
- transcription;
- OCR;
- embeddings caused solely by a descriptor-only media Object unless existing file behavior requires metadata embedding;
- LLM/model call;
- provider directory lookup.

F1 is canonical metadata/provenance only.

## Focused proof

Add tests proving at minimum:

1. One Telegram voice descriptor materializes one deterministic child Flow Object and one contains edge.
2. Telegram replay is idempotent.
3. Telegram audio/document/photo/video categories preserve safe media_kind/provenance metadata.
4. No Telegram media bytes are fetched and no transcription/model call occurs.
5. Telegram AI gate semantics are unchanged and no new model-visible leak is introduced.
6. Mattermost bounded file ids materialize separate deterministic file children.
7. Mattermost replay is idempotent.
8. Teams non-reference attachment descriptor materializes a child; quoted-message/reference attachment does not.
9. Unsafe/auth-bearing Teams attachment URL/token is not persisted.
10. Cross-user parent access fails closed.
11. Parent -> child contains relation is idempotent.
12. Existing email attachment tests remain green.
13. Existing communication sync tests remain green.
14. Existing Graph Refined focused tests remain green.
15. No transcription/UI/Task Refinement/provider download path is introduced.

Prefer no migration unless a schema correction is truly necessary; Object metadata + existing edges should be sufficient.

Run focused media/communication/email attachment tests, existing provider normalization tests, Graph Refined focused tests, Ruff/compile on touched Python, and `git diff --check`.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.
- Do not begin transcription F2, Task Refinement, or deploy.
