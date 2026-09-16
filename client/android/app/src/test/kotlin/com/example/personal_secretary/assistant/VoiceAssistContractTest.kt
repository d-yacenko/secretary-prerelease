package com.example.personal_secretary.assistant

import android.content.Intent
import android.service.voice.VoiceInteractionService
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class VoiceAssistContractTest {
    @Before
    fun resetDebounce() {
        LockedVoiceLaunch.resetForTest()
    }

    @Test
    fun serviceOverridesKeyguardLaunchCallback() {
        val method = SecretaryVoiceInteractionService::class.java.getDeclaredMethod(
            "onLaunchVoiceAssistFromKeyguard",
        )
        assertEquals(SecretaryVoiceInteractionService::class.java, method.declaringClass)
        assertFalse(java.lang.reflect.Modifier.isAbstract(method.modifiers))
    }

    @Test
    fun keyguardCallbackIsNotOnlyOnSession() {
        val sessionMethods = SecretaryVoiceInteractionSession::class.java.declaredMethods.map { it.name }
        assertFalse(sessionMethods.contains("onLaunchVoiceAssistFromKeyguard"))
        val serviceParent = SecretaryVoiceInteractionService::class.java.superclass
        assertEquals(VoiceInteractionService::class.java, serviceParent)
    }

    @Test
    fun lockedLaunchCarriesVoiceTriggerExtraAndSingleTaskFlags() {
        assertEquals("secretary.voice_trigger", SystemAssistantConstants.EXTRA_VOICE_TRIGGER)
        assertEquals(7101, SystemAssistantConstants.REQUEST_ASSISTANT_ROLE)
        val flags = SystemAssistantConstants.LOCKED_LAUNCH_FLAGS
        assertTrue(flags and Intent.FLAG_ACTIVITY_NEW_TASK != 0)
        assertTrue(flags and Intent.FLAG_ACTIVITY_SINGLE_TOP != 0)
        assertTrue(flags and Intent.FLAG_ACTIVITY_CLEAR_TOP != 0)
    }

    @Test
    fun launcherModeIsDistinctFromAssistInvokeTrigger() {
        assertEquals("secretary.voice_session_launch_mode", SystemAssistantConstants.EXTRA_LAUNCH_MODE)
        assertEquals("secretary.driving_voice_session_id", SystemAssistantConstants.EXTRA_DRIVING_SESSION_ID)
        assertEquals("launcher", SystemAssistantConstants.LAUNCH_MODE_LAUNCHER)
        assertEquals("assistInvoke", SystemAssistantConstants.LAUNCH_MODE_ASSIST_INVOKE)
        assertFalse(
            SystemAssistantConstants.EXTRA_LAUNCH_MODE == SystemAssistantConstants.EXTRA_VOICE_TRIGGER,
        )
        assertEquals(
            "com.example.personal_secretary.assistant.VoiceSessionActivity",
            VoiceSessionActivity::class.java.name,
        )
    }

    @Test
    fun showWhenLockedWindowFlagsRemainApi23CompatibleWithoutKeepScreenOn() {
        val flags = SystemAssistantConstants.API23_SHOW_WHEN_LOCKED_FLAGS
        assertTrue(flags and android.view.WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED != 0)
        assertTrue(flags and android.view.WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON != 0)
        assertEquals(0, flags and android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    @Test
    fun parseTreatsVoiceTriggerAsAssistInvokeAndLauncherExtraAsIdleLaunch() {
        assertTrue(parseVoiceSessionLaunch(hasVoiceTrigger = true, launchMode = SystemAssistantConstants.LAUNCH_MODE_LAUNCHER).autoInvoke)
        assertEquals(
            SystemAssistantConstants.LAUNCH_MODE_ASSIST_INVOKE,
            parseVoiceSessionLaunch(hasVoiceTrigger = true, launchMode = null).mode,
        )
        val launcher = parseVoiceSessionLaunch(
            hasVoiceTrigger = false,
            launchMode = SystemAssistantConstants.LAUNCH_MODE_LAUNCHER,
        )
        assertFalse(launcher.autoInvoke)
        assertEquals(SystemAssistantConstants.LAUNCH_MODE_LAUNCHER, launcher.mode)
    }

    @Test
    fun lockedLaunchDebouncesRepeatedKeyguardCallbacks() {
        assertTrue(LockedVoiceLaunch.tryMark(1_000L))
        assertFalse(LockedVoiceLaunch.tryMark(1_400L))
        assertTrue(LockedVoiceLaunch.tryMark(1_000L + SystemAssistantConstants.LOCKED_LAUNCH_DEBOUNCE_MS))
    }
}
