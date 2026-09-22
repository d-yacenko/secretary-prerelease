# Current task — MTProto temporal participation semantic correction

## Context

Commit `10cb4a3179e2a4c1acdfe94c3814a8aaf9ec7694` is architecturally accepted in all reviewed areas except one blocking temporal-participation semantic issue.

Do not reopen the broader Telegram implementation. This is a focused correctness correction, not a new feature phase.

Production remains `TELEGRAM_MTPROTO_AI_ENABLED=false`.

## Blocking issue

Current MTProto participation logic marks any inbound message whose `sender_peer_id` is not the connected Telegram user id as `direct_recipient`.

That is correct for a private 1:1 peer, but incorrect for `peer_kind=group` / `peer_kind=supergroup`.

A group message is not evidence that the current user was directly addressed. Marking every group message `direct_recipient` can cause temporal extraction to promote another participant's event into the user's consolidated calendar as personally expected.

## Required correction

1. In MTProto participation evidence:
   - outbound message authored by the connected Telegram user may keep the sender role;
   - inbound `peer_kind=private` from another sender may be `direct_recipient`;
   - inbound `peer_kind=group` or `supergroup` MUST NOT become `direct_recipient` merely because it is inbound;
   - unknown/missing peer kind must fail conservatively, not assume personal addressing.

2. In temporal extraction request semantics:
   - treat MTProto `group` / `supergroup` as group/channel-style communication for participation resolution, analogous to the existing non-direct channel semantics;
   - do not change private-chat semantics;
   - do not make all Telegram messages personally relevant.

3. Temporal source signature must include every MTProto metadata field that now affects participation/extraction behavior, at minimum:
   - `sender_peer_id`
   - `peer_kind`
   - existing `direction`
   This preserves stale-job fencing correctness.

4. Add focused regressions:
   - private inbound => direct_recipient;
   - private outbound self => sender;
   - group inbound => NOT direct_recipient;
   - supergroup inbound => NOT direct_recipient;
   - group/supergroup request is treated as channel/group semantics;
   - a high-confidence group temporal statement may follow the normal non-direct group policy, but cannot be promoted to personally `expected` solely from inbound direction;
   - changing peer_kind/sender identity changes the temporal extraction signature;
   - false/true Telegram AI gate behavior from the full pipeline remains unchanged.

5. Re-run the new full-pipeline test plus focused participation/temporal/Telegram suites. Do not add a workaround that weakens participation policy.

## Already accepted; do not redesign

- native MTProto conversation projection by account + peer + topic;
- legacy Telegram projection compatibility;
- narrow MTProto-only correlation trigger;
- false→true embedding catch-up;
- labels;
- assistant/context gating;
- stack semantic summaries;
- CRUD paths;
- production flag remains false.

## Authorization

AUTHORIZED:
- local code/tests/docs needed for this semantic correction;
- commit/push canonical `main`.

NOT AUTHORIZED:
- production SSH;
- deploy/ref movement;
- production env changes;
- real Telegram calls;
- real LLM/provider calls;
- DB migration.

## Required report

Return:
- commit SHA;
- exact participation rule after correction;
- temporal group/private behavior;
- source-signature change;
- tests run/results;
- production flag=false;
- production SSH=0;
- provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_MTPROTO_TEMPORAL_PARTICIPATION_FIXED`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
