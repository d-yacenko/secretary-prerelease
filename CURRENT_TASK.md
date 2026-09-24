# Current task — Persistent/resumable Assistant conversations MVP

## Authorization

Implement GitHub issue #8 as the next major product stage: server-owned persistent Assistant conversations, explicit `Новый диалог`, lightweight conversation history, and one-click resume of an older thread.

This task includes backend + migration + Flutter client work.

No production deploy is authorized.
No live provider/LLM calls are required for verification.
Telegram MTProto AI activation/quarantine must remain unchanged.

Current production baseline:
- server runtime/ref: `42db393be50a4c3f20ce86dadc280d77bada3959`
- Alembic: `0046 / 0046`

Task parent must be exactly:
`ed3cfdfb50ede0356704c4f0c394a7631eda60af`

Expected migration:
- `0047` from exact current head `0046`

If repository state disagrees with any pinned baseline, STOP and report before implementation.

## Product semantics

The Secretary Assistant must stop being a process-memory-only chat.

MVP behavior:

1. Each user may have multiple persisted Assistant conversations.
2. Exactly one conversation is current/selected at a time for the new persistent client flow.
3. Closing/restarting the Flutter app does not end the current conversation.
4. Reopening Secretary restores the current transcript in the same chat presentation.
5. Follow-up turns use bounded history from that exact current conversation.
6. `Новый диалог` creates a fresh current conversation with empty conversational context.
7. Creating a new dialog does NOT delete/archive/hide prior normal conversations.
8. A user can open conversation history and select an older conversation with one click/tap; that exact thread becomes current and can be continued.
9. Typed and hands-free/voice turns use the same current conversation.
10. No automatic topic splitting. The user explicitly controls when a new conversation starts.

## Critical separation: persisted transcript vs model context

Persisted UI history may be longer than model context.

- The server is the canonical owner of persistent conversation history for the new flow.
- The model must NOT receive the full lifetime transcript automatically.
- Preserve the current bounded-history spirit for MVP: use at most the recent `maxAssistantHistoryMessages` tail (currently 12 messages), loaded by the server from the selected conversation.
- Client-supplied `history` must no longer be the canonical source in persistent mode.
- Do not add rolling summaries in this task.
- Do not add cross-conversation memory in this task.

## Backward compatibility during server/client stagger

The canonical server deploy does not distribute Flutter clients, so backend and client may be upgraded at different times.

Preserve the existing legacy `POST /assistant/message` request path sufficiently that the currently installed old client continues to function until the new Flutter build is installed.

Recommended compatibility:
- keep existing `history` request field accepted for legacy requests;
- add optional persistent-mode identifiers such as `conversation_id` and `client_turn_id`;
- when the new client supplies persistent identifiers, server-owned conversation history is authoritative;
- do not silently reinterpret an old client's in-memory history as a different persisted conversation.

The new client must always use persistent mode after initialization.

## Data model / migration 0047

Introduce dedicated models rather than storing chat history as generic Objects.

### AssistantConversation

At minimum:
- `id UUID PK`
- `user_id FK users`, indexed
- `title` nullable/compact
- `is_current` boolean or equivalent deterministic current-selection mechanism
- `created_at`
- `updated_at` / `last_message_at`
- optional `archived_at` only if useful internally; do NOT archive merely because another conversation becomes current

Enforce at most one current conversation per user at DB/service level (partial unique index or equivalent robust invariant).

### AssistantMessage

At minimum:
- `id UUID PK`
- `conversation_id FK assistant_conversations`, indexed
- `user_id` if useful for direct isolation/indexing; otherwise isolation must be enforced through the conversation join
- `role` limited to user/assistant for persisted conversational transcript
- `content`
- `turn_id` / client idempotency identifier for normal user-assistant turns
- `created_at`
- persisted structured presentation needed to restore current UI:
  - references with exact object ids/title/kind/provider/canonical_uri/primary_at as returned at that time;
  - affected objects;
  - inbox review receipt if the existing UI presents it;
  - link to `pending_action_plans.id` when the Assistant response staged a plan.

Use JSONB for bounded presentation snapshots where that avoids unnecessary schema churn, but keep action-plan identity as an explicit nullable FK if practical.

Do not persist secrets/tool internals/chain-of-thought.

## Turn idempotency

The new client must generate a stable UUID `client_turn_id` per send attempt.

Persistent-mode `POST /assistant/message` must be idempotent for the same:
- user
- conversation
- client_turn_id

If a complete persisted turn already exists, return/reconstruct the stored Assistant response without another paid model call or duplicate action staging.

Avoid persisting duplicate user/assistant messages when a network timeout causes the client to retry.

A partially persisted/inconsistent turn must fail safely; do not silently create a second action plan.

## Conversation service/API

Implement a focused service layer with strict user scoping.

Required API capabilities (exact route naming may follow repository style):

- list current user's conversations ordered by `last_message_at DESC`, then deterministic tie-break;
- get current conversation;
- create a new current conversation;
- select/resume an existing user-owned conversation;
- read one conversation's messages, paginated/bounded;
- send Assistant message in persistent mode against an exact conversation.

Suggested routes:
- `GET /assistant/conversations`
- `GET /assistant/conversations/current`
- `POST /assistant/conversations`
- `POST /assistant/conversations/{conversation_id}/select`
- `GET /assistant/conversations/{conversation_id}/messages`

A different clean REST shape is acceptable if documented and tested.

Do not implement delete/archive/rename endpoints in this MVP.

## Conversation titles

Do not add a paid AI call merely to name a conversation.

MVP:
- empty conversation displays `Новый диалог`;
- on first successful user turn, derive a deterministic title from the first user message:
  - normalize whitespace;
  - single line;
  - compact bounded length (roughly 60–80 visible chars);
  - no model/provider call;
- title generation never blocks sending.

Manual rename and AI title improvement are future scope.

## New dialog / switching safety

Do not orphan mutation approvals.

Server:
- before creating a new current conversation or selecting another one, inspect the current conversation for any linked canonical action plan still in unresolved pending/approval-required state;
- if unresolved, return deterministic conflict instead of switching;
- expired/rejected/executed plans do not block.

Client:
- disable/block `Новый диалог` and conversation switching while approve/reject/resume operation is locally in flight;
- display a concise explanation when the server reports an unresolved pending plan;
- do not silently cancel/reject an action plan as a side effect of switching.

Starting a new dialog clears transient per-turn context:
- object/notification context selection;
- retry/error state;
- voice approval binding/transient voice-turn state.

It must NOT alter:
- user settings/model selection;
- source objects;
- bookmarks;
- labels;
- unrelated app data.

## Action-plan presentation and canonical status

Persisted chat presentation must not become an alternate authority for action-plan state.

For a persisted Assistant message linked to `pending_action_plans.id`:
- message history API should rehydrate the action-plan card from the current canonical plan row/status where possible;
- stored snapshots are presentation/audit fallback only;
- approve/reject continue using existing canonical action-plan endpoints.

When `resume_action_plan` produces the post-execution Assistant summary:
- persist that Assistant summary into the same conversation when the plan is linked to a persistent conversation;
- make retry/resume persistence idempotent so a retry does not append duplicate completion summaries.

Legacy action plans without a conversation link may keep current behavior.

## Assistant send persistence

For persistent mode:

1. Verify conversation belongs to current user.
2. Load server-owned bounded recent history from that conversation.
3. Preserve existing explicit UI context behavior for `context_object_id` / notification context.
4. Call existing AssistantService/provider/tool flow.
5. Persist the completed user + assistant turn and structured presentation.
6. Update conversation `last_message_at` and first-turn title if needed.
7. Return response including `conversation_id` and persisted message ids if useful to client.

Keep:
- Cost Guard;
- exact-object tool allowlists;
- prompt-injection DATA/evidence invariant;
- approval protocol;
- per-user model settings.

Do not change model selection semantics.

## Flutter client

### Controller

Move the new flow away from process-only ownership:
- initialize Secretary by loading current conversation;
- if none exists, create one;
- load its persisted messages;
- send new turns with `conversation_id` + stable `client_turn_id`;
- do not send client history as canonical history in persistent mode;
- after app restart, reconstruct `AssistantChatMessage` including references/affected objects/action-plan card state;
- selecting/new conversation resets only transient turn/voice context, not global settings.

Keep the existing in-memory list as the rendered cache if convenient, but backend persistence is canonical.

### New dialog

Add a clear compact `Новый диалог` action in Secretary UI.

On success:
- fresh current conversation;
- empty transcript/input context;
- history list retains previous conversation.

### Conversation history UI

Desktop wide layout:
- lightweight narrow/collapsible side panel inside/adjacent to Secretary chat;
- show conversation title and subdued last activity date/time;
- current conversation visibly selected;
- clicking a row loads/selects that conversation.

Mobile/narrow layout:
- do not permanently consume horizontal width;
- use a history button opening drawer/sheet/menu with the same list and selection behavior.

Keep Secretary as the primary experience; do not build a ChatGPT-style management product.

## Pagination / size

Do not load an unbounded lifetime history in one API response.

- conversation list: reasonable bounded page/list for MVP (e.g. recent 50) with deterministic ordering;
- messages: cursor or limit-based pagination with a sane bound;
- client may initially load the most recent page and support loading older messages if straightforward.

At minimum, a long conversation must not create an unbounded response.

## Strict isolation/security

Test that:
- user A cannot list/read/select/send into user B conversation;
- message ids/action-plan links cannot cross user boundaries;
- conversation titles/content/references are never leaked cross-user;
- stored/external content remains DATA/evidence, not instructions;
- no credentials/tokens/tool internals are persisted into transcript presentation.

## Migration / rollback discipline

Migration `0047` must:
- be additive;
- create only conversation/message persistence structures/indexes/FKs needed for this feature;
- not rewrite generic Objects;
- have a valid downgrade;
- preserve existing users/data.

No production migration/deploy is authorized by this task.

## Focused verification

Backend tests must cover at minimum:

1. 0046 -> 0047 upgrade and 0047 -> 0046 downgrade.
2. current conversation create/select uniqueness per user.
3. list ordering by recent activity.
4. strict cross-user isolation.
5. deterministic first-message title.
6. server-owned bounded history passed to Assistant in persistent mode.
7. legacy Assistant request compatibility remains functional.
8. persistent turn stores user + assistant response + references/affected objects.
9. restart/read reconstructs structured presentation.
10. `client_turn_id` retry returns stored response without second provider/tool call.
11. new/select blocked by unresolved pending action plan.
12. executed/rejected/expired plan no longer blocks.
13. action-plan card status is hydrated from canonical plan state.
14. resume summary persists once in the same conversation.
15. Cost Guard/tool/approval invariants remain green.

Flutter tests must cover at minimum:

16. startup restores current conversation and messages.
17. first run with no conversation creates/loads a fresh one.
18. `Новый диалог` empties current transcript but prior conversation remains in history.
19. selecting old history restores exact messages/references and future send uses that conversation id.
20. desktop history panel layout at representative/narrow wide widths without overflow.
21. mobile history surface does not consume permanent chat width.
22. pending/in-flight action-plan state blocks new/switch with clear UX.
23. typed and voice send paths use the same current conversation.
24. network retry reuses the same client_turn_id.

Run relevant backend focused suites, migration check, Ruff/compile, Flutter focused suites/analyze, and `git diff --check`.

## Non-goals

Do NOT implement in this task:
- rolling conversation summaries;
- AI-generated titles requiring a new provider call;
- cross-conversation memory/retrieval;
- automatic topic detection/splitting;
- folders/projects/tags for chats;
- full-text chat-history search;
- conversation delete/archive/retention UI;
- group label aggregation;
- Telegram voice-note STT;
- Telegram AI activation;
- production deploy/client distribution.

## Completion

Record in `PROJECT_STATE.md`:
- exact implementation SHA;
- migration `0047` status;
- data/API/client design actually implemented;
- compatibility behavior;
- focused backend/Flutter test results;
- confirmation no live provider calls;
- confirmation production remains `42db393be50a4c3f20ce86dadc280d77bada3959`;
- confirmation Telegram AI gate unchanged.

Return `CURRENT_TASK.md` to HOLD, push, and STOP.
