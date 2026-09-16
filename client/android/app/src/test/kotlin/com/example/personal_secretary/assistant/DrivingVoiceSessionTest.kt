package com.example.personal_secretary.assistant

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class DrivingVoiceSessionTest {
    @Before
    fun reset() {
        DrivingVoiceSessionRegistry.resetForTest()
    }

    @Test
    fun defaultRegistryIsUnauthorized() {
        assertNull(DrivingVoiceSessionRegistry.currentSessionId())
        assertFalse(DrivingVoiceSessionRegistry.isAuthorized("anything"))
        assertFalse(
            validateDrivingSession(
                hasVoiceTrigger = false,
                launchMode = SystemAssistantConstants.LAUNCH_MODE_LAUNCHER,
                sessionId = null,
            ).authorized,
        )
    }

    @Test
    fun unlockedLaunchArmsMatchingSession() {
        val decision = decideDrivingLaunch(keyguardLocked = false)
        assertNotNull(decision.sessionId)
        assertEquals(SystemAssistantConstants.LAUNCH_MODE_LAUNCHER, decision.launchMode)
        val snapshot = validateDrivingSession(
            hasVoiceTrigger = false,
            launchMode = decision.launchMode,
            sessionId = decision.sessionId,
        )
        assertTrue(snapshot.authorized)
        assertEquals(DrivingVoiceSessionRegistry.currentSessionId(), snapshot.sessionId)
        assertEquals(decision.sessionId, snapshot.sessionId)
    }

    @Test
    fun lockedLaunchDoesNotArmAuthorization() {
        val decision = decideDrivingLaunch(keyguardLocked = true)
        assertNull(decision.sessionId)
        assertNull(DrivingVoiceSessionRegistry.currentSessionId())
        assertFalse(
            validateDrivingSession(
                hasVoiceTrigger = false,
                launchMode = decision.launchMode,
                sessionId = decision.sessionId,
            ).authorized,
        )
    }

    @Test
    fun assistInvokeExtraDoesNotAuthorizeEvenWithSessionId() {
        val sessionId = DrivingVoiceSessionRegistry.armNewSession()
        assertFalse(
            validateDrivingSession(
                hasVoiceTrigger = true,
                launchMode = SystemAssistantConstants.LAUNCH_MODE_ASSIST_INVOKE,
                sessionId = sessionId,
            ).authorized,
        )
        assertFalse(
            validateDrivingSession(
                hasVoiceTrigger = false,
                launchMode = SystemAssistantConstants.LAUNCH_MODE_ASSIST_INVOKE,
                sessionId = sessionId,
            ).authorized,
        )
        assertNotNull(DrivingVoiceSessionRegistry.currentSessionId())
    }

    @Test
    fun staleIntentAfterClearOrProcessDeathIsUnauthorized() {
        val decision = decideDrivingLaunch(keyguardLocked = false)
        assertTrue(
            validateDrivingSession(
                hasVoiceTrigger = false,
                launchMode = decision.launchMode,
                sessionId = decision.sessionId,
            ).authorized,
        )
        DrivingVoiceSessionRegistry.clear()
        assertFalse(
            validateDrivingSession(
                hasVoiceTrigger = false,
                launchMode = decision.launchMode,
                sessionId = decision.sessionId,
            ).authorized,
        )
        assertNull(DrivingVoiceSessionRegistry.currentSessionId())
    }

    @Test
    fun newSessionInvalidatesPreviousSessionId() {
        val first = decideDrivingLaunch(keyguardLocked = false)
        val second = decideDrivingLaunch(keyguardLocked = false)
        assertNotEquals(first.sessionId, second.sessionId)
        assertFalse(
            validateDrivingSession(
                hasVoiceTrigger = false,
                launchMode = first.launchMode,
                sessionId = first.sessionId,
            ).authorized,
        )
        assertTrue(
            validateDrivingSession(
                hasVoiceTrigger = false,
                launchMode = second.launchMode,
                sessionId = second.sessionId,
            ).authorized,
        )
    }
}
