# Current task — Assistant stale voice transcription session fix

Architect review of implementation `5711f47f63b0a3c7222a618833554327756a5b8e` found one remaining auth-session race. Fix only this issue and its focused proof.

Do not start another product feature. Do not deploy to production. Do not apply migration `0047` in production. Do not make live provider/LLM calls.

## Problem

`AssistantController.resetSession()` now invalidates persistent/bootstrap/send/action-plan continuations, but an already-running voice transcription is owned by `VoiceTranscriptionController`.

Current `VoiceTranscriptionController.reset()` invalidates voice startup/recording, but does not invalidate an in-flight `transcribeAudio()` operation. If user A logs out while transcription is in flight, the old request can later:
- set voice state/error after reset;
- invoke the bound transcript consumer;
- call `AssistantController._handleVoiceTranscript()` under the new session and potentially send user A's transcript into user B's current Assistant conversation.

Also ensure an old `_stopVoiceInFlight` future cannot block a fresh voice operation in the next auth session.

## Required behavior

- An in-flight transcription belongs to the auth/session generation in which it started.
- `resetSession()` must invalidate old transcription completion.
- A transcript/error/success from a previous session must not mutate current voice UI state and must not call the Assistant transcript consumer.
- It must therefore be impossible for an old user's transcript to create an Assistant turn in the next user's session.
- A new session must be able to start/use voice normally without waiting for the stale old transcription to finish.
- Prefer a deterministic generation/epoch in `VoiceTranscriptionController` (or an equivalently strong mechanism), rather than trying to cancel an already-running Dart Future.
- Preserve the accepted persistent-conversation session epoch behavior from `5711f47`.

## Focused proof

Add tests proving at minimum:
1. Start transcription for session/user A, reset before `transcribeAudio` completes, then complete the old transcription: transcript consumer is not called and old completion does not restore voice error/state for A.
2. After that reset, session/user B can start a fresh voice operation normally; the stale A future does not block or overwrite B.
3. At Assistant integration level, stale A transcript completion after reset does not cause `POST /assistant/message` and does not append any A transcript/response to B's Assistant state.
4. Existing Assistant conversation/session-isolation and voice tests remain green.

Run the smallest relevant Flutter tests, touched-file analyze, and `git diff --check`. Backend changes are not expected.

When complete:
- record exact checks/results and implementation SHA in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP. Do not choose the next phase and do not deploy.
