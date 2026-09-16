package com.example.personal_secretary.assistant

import android.content.Intent
import java.util.UUID

data class DrivingSessionSnapshot(
    val authorized: Boolean,
    val sessionId: String?,
) {
    companion object {
        fun none(): DrivingSessionSnapshot = DrivingSessionSnapshot(false, null)
    }
}

data class DrivingLaunchDecision(
    val sessionId: String?,
    val launchMode: String = SystemAssistantConstants.LAUNCH_MODE_LAUNCHER,
)

/**
 * Process-memory driving authorization. Not SharedPreferences, not server.
 * Process death / reboot leaves the next VoiceSessionActivity intent stale.
 */
object DrivingVoiceSessionRegistry {
    @Volatile
    private var sessionId: String? = null

    fun resetForTest() {
        sessionId = null
    }

    fun currentSessionId(): String? = sessionId

    fun armNewSession(): String {
        val id = UUID.randomUUID().toString()
        sessionId = id
        return id
    }

    fun isAuthorized(candidate: String?): Boolean {
        val current = sessionId
        return current != null && candidate != null && current == candidate
    }

    fun clear() {
        sessionId = null
    }
}

fun decideDrivingLaunch(keyguardLocked: Boolean): DrivingLaunchDecision {
    if (keyguardLocked) {
        return DrivingLaunchDecision(sessionId = null)
    }
    return DrivingLaunchDecision(sessionId = DrivingVoiceSessionRegistry.armNewSession())
}

fun validateDrivingSession(
    hasVoiceTrigger: Boolean,
    launchMode: String?,
    sessionId: String?,
): DrivingSessionSnapshot {
    if (hasVoiceTrigger) {
        return DrivingSessionSnapshot.none()
    }
    if (launchMode == SystemAssistantConstants.LAUNCH_MODE_ASSIST_INVOKE) {
        return DrivingSessionSnapshot.none()
    }
    if (!DrivingVoiceSessionRegistry.isAuthorized(sessionId)) {
        return DrivingSessionSnapshot.none()
    }
    return DrivingSessionSnapshot(authorized = true, sessionId = sessionId)
}

fun applyDrivingLaunch(intent: Intent, keyguardLocked: Boolean): Intent {
    val decision = decideDrivingLaunch(keyguardLocked)
    intent.putExtra(SystemAssistantConstants.EXTRA_LAUNCH_MODE, decision.launchMode)
    intent.removeExtra(SystemAssistantConstants.EXTRA_VOICE_TRIGGER)
    if (decision.sessionId == null) {
        intent.removeExtra(SystemAssistantConstants.EXTRA_DRIVING_SESSION_ID)
    } else {
        intent.putExtra(SystemAssistantConstants.EXTRA_DRIVING_SESSION_ID, decision.sessionId)
    }
    return intent
}

fun validateDrivingSessionIntent(intent: Intent?): DrivingSessionSnapshot {
    if (intent == null) {
        return DrivingSessionSnapshot.none()
    }
    return validateDrivingSession(
        hasVoiceTrigger = intent.hasVoiceTriggerExtra(),
        launchMode = intent.getStringExtra(SystemAssistantConstants.EXTRA_LAUNCH_MODE),
        sessionId = intent.getStringExtra(SystemAssistantConstants.EXTRA_DRIVING_SESSION_ID),
    )
}
