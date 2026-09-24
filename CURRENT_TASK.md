# Current task — Inbox Conversation Stack bookmark visibility

## Authorization

One narrow Flutter-only Inbox UI fix is authorized.

Production mutation is NOT authorized.

Production baseline:
- runtime/ref: `fe81a13c8887da73b743f5f5c9a4f8830aafa943`
- Alembic: `0046 / 0046`

No live provider calls. No backend/API/DB schema work is expected.

## Problem

Conversation messages are usefully collapsed into `InboxConversationStack` cards.

A bookmark on an individual child message is visible when the stack is expanded, but the collapsed stack card currently shows no bookmark indication. This hides user-marked important messages in the normal collapsed view.

The user-provided screenshots are the acceptance baseline:
- expanded stack: one child visibly has a red bookmark;
- collapsed stack: the parent stack currently appears unmarked.

## Existing architecture to reuse

Do not invent a stack bookmark entity.

Current client already has:
- `InboxConversationStackEntry.children`: the exact source objects represented by the rendered stack;
- `ObjectBookmarkController`: bookmark colors keyed by child object ID;
- Inbox loading/pagination already reconciles bookmark state for visible child object IDs;
- existing bookmark glyph/palette color helpers in `object_bookmark.dart`.

Use these existing values only.

## Required behavior

### Derived aggregate

For each rendered Conversation Stack card, derive bookmark state from its `children` / represented display object IDs:

- ignore children without a bookmark;
- deduplicate bookmark color tokens for visual summary;
- do not read unrelated/non-rendered conversation history;
- do not create, PUT, DELETE, or otherwise persist any bookmark for `stackId`.

### Presentation

The aggregate indicator must be visible on the stack card in both collapsed and expanded states.

- no bookmarked children: show no aggregate bookmark indicator;
- exactly one distinct bookmark color: show one filled bookmark glyph using that existing color token;
- multiple distinct colors: show a compact sequence of distinct filled bookmark glyphs;
- cap the visible distinct-color glyphs at 3;
- if more than 3 distinct colors exist, show a compact `+N` overflow indication;
- preserve deterministic order based on first occurrence in the rendered `children` order; do not invent a semantic priority between red/orange/yellow/etc.;
- reuse existing `ObjectBookmarkGlyph` and bookmark color helpers rather than drawing a second bookmark visual language;
- include Tooltip/Semantics that communicates that these bookmarks belong to messages inside the conversation. If useful, include per-color counts in accessibility text.

The aggregate indicator is read-only:
- it must not open a bookmark palette;
- it must not set/clear a bookmark on the stack;
- normal tap on the stack card continues only to expand/collapse it.

Keep the indicator compact and avoid title/timestamp/chevron overflow on narrow mobile and desktop widths.

### Live updates

Because `ObjectBookmarkController` already notifies listeners:
- adding/changing a bookmark on an expanded child must update the stack aggregate immediately;
- clearing the last child bookmark must remove the aggregate immediately;
- changing one child from one color to another must update the distinct-color summary;
- passive refresh/pagination behavior must remain unchanged.

## Out of scope

Do NOT implement group labels in this task.

The future label design is already recorded in backlog:
- deduplicated union of child labels;
- existing `ObjectLabelStrip`;
- at most two visible plus current `+N`;
- no new AI classification in the first version.

Also out of scope:
- backend changes;
- new stack DB/API entity;
- migrations;
- bookmark API changes;
- Conversation Stack grouping/summarization changes;
- production deploy or client installation/distribution;
- unrelated UI cleanup.

## Focused tests

Add/extend Flutter tests proving at minimum:

1. collapsed stack with no child bookmarks has no aggregate indicator;
2. one red-bookmarked child produces one red filled stack indicator;
3. the same aggregate remains visible when the stack is expanded;
4. two or three distinct child bookmark colors produce the corresponding unique-color glyphs in deterministic child order;
5. more than three distinct colors shows only three glyphs plus `+N`;
6. duplicate colors across several children produce one visual glyph for that color;
7. clearing/changing child bookmark state causes the aggregate to update without a reload;
8. narrow mobile and desktop widths produce no overflow/RenderFlex exception;
9. interacting with the stack aggregate does not call bookmark PUT/DELETE for `stackId` and does not replace expand/collapse behavior.

Run:
- focused Inbox/Conversation Stack/bookmark Flutter tests;
- relevant existing bookmark tests;
- Flutter analyze for touched Dart files;
- `git diff --check`.

## Completion

Record:
- exact implementation SHA;
- files changed;
- focused test/analyze results;
- confirmation that no backend/API/DB code changed;
- confirmation that production remains `fe81a13c8887da73b743f5f5c9a4f8830aafa943`.

Return `CURRENT_TASK.md` to HOLD, push, and STOP.
