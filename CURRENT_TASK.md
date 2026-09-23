# Current task — Quick UX bugfix pack: Google OAuth diagnostics, hands-free failure feedback, desktop delete, exact Assistant references

## Human request

The integration phase is complete. Two unrelated technical-debt items remain deferred and are NOT part of this task:
- cross-provider temporal `already_evidenced` / idempotency nuance;
- historical cleanup/compaction of `PROJECT_STATE.md`.

The human requested a bounded UX bugfix pass before the next major phase.

No production/deploy/provider mutation is authorized by this task.

---

# A. Google OAuth: preserve automatic refresh, diagnose permanent refresh-token expiry correctly

## Current facts

Secretary already implements the normal OAuth lifecycle:
- authorization URL requests `access_type=offline`;
- authorization URL uses `prompt=consent`;
- expired access tokens are automatically refreshed through the stored refresh token;
- Gmail and Google Calendar share the same Google account credential;
- recurring Gmail/Calendar sync failures are classified as authentication/transient/permission.

The current user-visible failure is:
`failed to refresh access token`

Both Gmail and Google Calendar fail together.

Google's Testing publishing mode intentionally expires non-basic OAuth authorizations/refresh tokens after 7 days. This cannot be silently renewed by application code after the refresh token itself expires. The operational fix is to use an OAuth project with Publishing status `In Production` (or appropriate Internal mode for a Workspace organization), not to add a weekly background re-consent flow.

The repository requests Gmail/Calendar/Drive scopes, including restricted Gmail access.

## Required code correction

Code/test-only:

1. Extend `GoogleOAuthError` with a sanitized machine-readable provider OAuth error code, e.g. `invalid_grant`, without storing/logging:
   - access tokens;
   - refresh tokens;
   - authorization codes;
   - raw provider response bodies;
   - client secret.

2. `GoogleOAuthService.refresh_access_token()` must preserve the parsed safe OAuth `error` code on non-success responses.

3. Keep transient classification unchanged for temporary/provider/server errors.

4. Non-retryable OAuth refresh errors, especially `invalid_grant`, remain `authentication` failures and must not be endlessly retried as transient.

5. Improve Google authentication failure presentation so the user gets a clear reconnect instruction. Do not falsely claim that every authentication error is caused by 7-day Testing expiry.

6. Add a short operator/developer note in repo documentation explaining:
   - automatic access-token refresh already exists;
   - Testing OAuth authorizations expire after 7 days for these non-basic scopes;
   - continuous real use requires Google OAuth Publishing status `In Production` (or appropriate Internal deployment);
   - changing Cloud publishing status is an operator action outside Secretary runtime;
   - public distribution with sensitive/restricted scopes may require Google verification/security requirements.

7. Do NOT add any background browser automation, stored Google password, refresh-token rotation hack, service-account impersonation, or automatic consent-screen interaction.

## Required tests

At minimum prove:
- authorization URL still requests offline access + consent;
- expired access token automatically refreshes normally;
- successful refresh keeps existing refresh token when Google does not return a replacement;
- nonretryable `invalid_grant` exposes only the safe error code and classifies as authentication;
- retryable Google OAuth errors remain transient;
- no token/client-secret values enter source-sync user-visible diagnostics.

---

# B. Hands-free Assistant: never fail silently

## Current defect

Backend already exposes typed Assistant failures, including:
- `assistant_round_limit`;
- output limit;
- OpenAI connection/rate/service errors;
- daily budget errors.

The Flutter `AssistantController.sendMessage()` catches auth/network/API failures and sets:
- `sendState=error`;
- `errorMessage`.

But for a voice/hands-free turn, `voiceState` does not treat `sendState=error` as a voice error and `voiceErrorMessage` does not expose the Assistant turn error. The UI can therefore fall back to idle with no audible signal after a long "thinking" period.

## Required behavior

For a voice-originated/hands-free Assistant turn:

1. Any terminal Assistant request failure after transcription must:
   - remain visibly in an error state;
   - preserve the existing sanitized backend/user-facing error message;
   - not silently become ordinary idle until the user explicitly retries/starts the next turn.

2. Play one short LOCAL failure cue when the turn fails.
   - No TTS of the full error is required.
   - The cue must be distinguishable from normal start/stop/ready cues.
   - It must require no network/provider call.
   - It must not loop.

3. Typed backend reasons must remain available in the visible error text, including the existing round-limit message ("не хватило лимита шагов...").

4. Typed/keyboard Assistant behavior must not regress.

5. Do not convert a failed turn into a successful Assistant chat message.

6. Retry must reuse the existing pending retry mechanics and must not duplicate the prior user message.

Prefer a small `VoiceLocalFeedback.playError()` contract with a local asset/system cue and deterministic tests.

## Required tests

Cover:
- voice turn + round-limit/API failure => voice error state + visible reason + exactly one failure cue;
- voice turn + network/auth failure => same fail-visible behavior;
- typed request failure => existing screen error semantics, no hands-free cue;
- next voice trigger/retry clears prior voice turn error correctly;
- successful voice response still follows normal speech path and no error cue.

---

# C. Desktop Inbox: delete action directly on cards

## Current defect

Mobile/touch has Swipe-to-Remove.
Desktop intentionally has no swipe wrapper.

Deletion backend/API and confirmation logic already exist:
- `deleteObjectFromSecretary()`;
- `confirmAndDeleteObject()`;
- `objectSupportsDeliberateSwipeDeleteWithoutDialog()`;
- local card removal through `_removeDeletedInboxObject()`.

## Required behavior

On desktop Inbox source cards, add a Delete/trash quick action immediately after:
- Ask Secretary;
- Open in Graph.

Requirements:
1. Reuse the existing delete semantics. Do not create a second delete API/path.
2. Preserve current confirmation rules:
   - provider-backed known deliberate-delete sources may use the same deliberate direct-delete semantics if appropriate;
   - task/note/unknown/fail-closed cases retain the existing confirmation dialog.
3. After successful delete, remove the object/covered stack entry from the visible Inbox using the existing local update path; no full Inbox reload required.
4. On failure, keep the card and show the existing safe error feedback.
5. Mobile swipe behavior must remain unchanged.
6. Avoid duplicate delete controls on touch/mobile if that would clutter the existing swipe UX; this request is specifically for desktop convenience.

## Required tests

Cover Linux/desktop at minimum:
- trash action rendered after Ask Secretary / Graph when deletion is available;
- success issues exactly one DELETE and removes card locally;
- confirmation-required object keeps dialog semantics;
- failed DELETE keeps card;
- Android/iOS swipe tests remain unchanged.

---

# D. Assistant results: exact cited objects must be openable

## Current defect

Assistant Markdown can display text such as "Открыть письмо", but `AssistantMessageBody` only launches external `http/https` links.

The clickable chips below Assistant answers are built from `candidate_object_ids`: objects merely exposed to the model via bounded tool outputs. They are capped at `MAX_ASSISTANT_REFERENCES=8` in discovery order.

Therefore:
- the chips are not exact citations;
- irrelevant/neighbor objects can consume the cap;
- an object explicitly discussed in the answer can be omitted from the clickable references;
- textual "Открыть письмо" may look link-like but cannot open the Secretary object.

## Required architecture

Implement explicit, provenance-safe Assistant object citations.

Preferred contract:
- Assistant answer may reference a Secretary object only through a deterministic internal citation URI/token such as `secretary://object/<uuid>` or an equivalent structured citation field;
- the client maps that exact validated object id to existing `openObjectDetail()`;
- external http/https Markdown links keep their current external-browser behavior.

Security/provenance requirements:
1. The model must never be allowed to invent an arbitrary object id and make it clickable.
2. Every internal cited object id must be validated server-side against the object ids actually exposed/seen during the current Assistant turn (UI context/tool outputs) and owned by the current user.
3. Invalid/unseen/foreign internal citations must be rendered as non-clickable text or stripped, never opened.
4. Exact cited object references must have priority over generic candidate/reference chips and must not be lost merely because more than 8 objects were seen.
5. Preserve existing generic references if useful, but dedupe them by object id.
6. Do not rely on provider `canonical_uri` for opening a Secretary object; Yandex/Gmail/internal objects may not have a suitable external URI.

The resulting UX should allow an answer like:
- found email A;
- found email B;
with each explicitly cited item opening the exact Secretary object directly from the answer, and/or guaranteeing the exact cited objects appear as clickable chips.

## Required tests

Backend:
- exact cited object exposed this turn => returned as validated citation/reference;
- unseen/invented object id => rejected/non-clickable;
- foreign user's object => rejected;
- >8 generic seen candidates + a later exact citation => exact citation survives the cap;
- duplicate tool exposures/citations dedupe correctly.

Client:
- internal validated Secretary citation opens `openObjectDetail()` for exact id;
- http/https link remains external;
- malformed/unsupported schemes do not launch;
- reference chips for exact cited objects work;
- regression for ordinary Assistant answers with no citations.

Do not make arbitrary Markdown links trusted merely because the model emitted them.

---

# Checks

Run all directly affected backend/client tests plus:
- Assistant provider/error/provenance/reference tests;
- Assistant voice/hands-free tests;
- Inbox desktop/mobile delete tests;
- Google OAuth/source-sync classification/presentation tests;
- `py_compile`;
- Ruff check;
- Ruff format --check;
- relevant Flutter tests;
- `flutter analyze` if required by repo conventions;
- `git diff --check`.

## Production boundary

No production SSH.
No direct Docker/Compose.
No deploy.
No production ref movement.
No production env change.
No Google Cloud Console mutation.
No OAuth publishing-status change.
No real Google reauthorization.
No provider calls.
No production DB write.

When complete:
- update `PROJECT_STATE.md` factually;
- commit + push;
- report exact SHA and test results;
- STOP.

Deployment is a separate explicit human authorization after Architect review.
