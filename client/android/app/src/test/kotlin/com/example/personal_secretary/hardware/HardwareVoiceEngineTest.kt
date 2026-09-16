package com.example.personal_secretary.hardware

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class RecordingScheduler : HardwareVoiceScheduler {
    val scheduled = mutableMapOf<String, Long>()

    override fun schedule(token: String, delayMs: Long) {
        scheduled[token] = delayMs
    }

    override fun cancel(token: String) {
        scheduled.remove(token)
    }

    fun fire(engine: HardwareVoiceEngine, token: String): Boolean {
        if (scheduled.remove(token) == null) {
            return false
        }
        engine.onScheduled(token)
        return true
    }
}

class RecordingCallbacks : HardwareVoiceCallbacks {
    var voiceTriggers = 0
    var volumeRaises = 0
    var learnTimeouts = 0
    var learnCancels = 0
    var testRecognized = 0
    var testTimeouts = 0
    var testCancels = 0
    val rejected = mutableListOf<Int>()
    val captured = mutableListOf<Triple<Int, Int, String>>()

    override fun onVoiceTrigger() {
        voiceTriggers += 1
    }

    override fun onLearnCaptured(keyCode: Int, scanCode: Int, androidKeyName: String?, gesture: String) {
        captured.add(Triple(keyCode, scanCode, gesture))
    }

    override fun onLearnRejected(keyCode: Int, message: String) {
        rejected.add(keyCode)
    }

    override fun onLearnTimeout() {
        learnTimeouts += 1
    }

    override fun onLearnCancelled() {
        learnCancels += 1
    }

    override fun onTestRecognized() {
        testRecognized += 1
    }

    override fun onTestTimeout() {
        testTimeouts += 1
    }

    override fun onTestCancelled() {
        testCancels += 1
    }

    override fun raiseVolume() {
        volumeRaises += 1
    }
}

class HardwareVoiceEngineTest {
    private lateinit var scheduler: RecordingScheduler
    private lateinit var callbacks: RecordingCallbacks
    private lateinit var engine: HardwareVoiceEngine

    @Before
    fun setUp() {
        scheduler = RecordingScheduler()
        callbacks = RecordingCallbacks()
        engine = HardwareVoiceEngine(callbacks, scheduler) { 0L }
    }

    private fun down(
        keyCode: Int,
        repeat: Int = 0,
        scan: Int = 0,
        eventTime: Long = 0L,
    ): HardwareKeyStroke {
        return HardwareKeyStroke(keyCode, scan, repeat, true, eventTime)
    }

    private fun up(keyCode: Int, scan: Int = 0): HardwareKeyStroke {
        return HardwareKeyStroke(keyCode, scan, 0, false, 0L)
    }

    private fun arm(keyCode: Int, gesture: HardwareVoiceGesture, scan: Int = 0) {
        engine.configure(
            HardwareVoiceNativeBinding(
                enabled = true,
                keyCode = keyCode,
                scanCode = scan,
                gesture = gesture,
            ),
        )
    }

    @Test
    fun genericSingleKeyEmitsOneTriggerPerPhysicalDown() {
        arm(1082, HardwareVoiceGesture.SINGLE)
        assertTrue(engine.onKey(down(1082)))
        engine.onKey(up(1082))
        assertEquals(1, callbacks.voiceTriggers)
        engine.onKey(down(1082))
        engine.onKey(up(1082))
        assertEquals(2, callbacks.voiceTriggers)
    }

    @Test
    fun keyDownRepeatIsNotMultipleTaps() {
        arm(1082, HardwareVoiceGesture.SINGLE)
        engine.onKey(down(1082, repeat = 0))
        engine.onKey(down(1082, repeat = 1))
        engine.onKey(down(1082, repeat = 2))
        engine.onKey(up(1082))
        assertEquals(1, callbacks.voiceTriggers)
    }

    @Test
    fun genericDoubleRequiresSecondPressInsideWindow() {
        arm(1082, HardwareVoiceGesture.DOUBLE)
        engine.onKey(down(1082))
        engine.onKey(up(1082))
        assertEquals(0, callbacks.voiceTriggers)
        assertTrue(scheduler.fire(engine, HardwareVoiceConstants.TOKEN_PENDING))
        assertEquals(0, callbacks.voiceTriggers)

        engine.onKey(down(1082))
        engine.onKey(up(1082))
        engine.onKey(down(1082))
        engine.onKey(up(1082))
        assertEquals(1, callbacks.voiceTriggers)
    }

    @Test
    fun volumeUpSingleRaisesVolumeOnceAndDoesNotTrigger() {
        arm(HardwareVoiceConstants.KEYCODE_VOLUME_UP, HardwareVoiceGesture.DOUBLE)
        engine.onKey(down(HardwareVoiceConstants.KEYCODE_VOLUME_UP))
        engine.onKey(up(HardwareVoiceConstants.KEYCODE_VOLUME_UP))
        assertEquals(0, callbacks.voiceTriggers)
        scheduler.fire(engine, HardwareVoiceConstants.TOKEN_PENDING)
        assertEquals(0, callbacks.voiceTriggers)
        assertEquals(1, callbacks.volumeRaises)
    }

    @Test
    fun volumeUpDoubleEmitsOneTriggerAndNoVolume() {
        arm(HardwareVoiceConstants.KEYCODE_VOLUME_UP, HardwareVoiceGesture.DOUBLE)
        engine.onKey(down(HardwareVoiceConstants.KEYCODE_VOLUME_UP))
        engine.onKey(up(HardwareVoiceConstants.KEYCODE_VOLUME_UP))
        engine.onKey(down(HardwareVoiceConstants.KEYCODE_VOLUME_UP))
        engine.onKey(up(HardwareVoiceConstants.KEYCODE_VOLUME_UP))
        assertEquals(1, callbacks.voiceTriggers)
        assertEquals(0, callbacks.volumeRaises)
    }

    @Test
    fun volumeUpDoubleRecordsKeyDownDelta() {
        arm(HardwareVoiceConstants.KEYCODE_VOLUME_UP, HardwareVoiceGesture.DOUBLE)
        engine.onKey(down(HardwareVoiceConstants.KEYCODE_VOLUME_UP, eventTime = 10))
        engine.onKey(up(HardwareVoiceConstants.KEYCODE_VOLUME_UP))
        engine.onKey(down(HardwareVoiceConstants.KEYCODE_VOLUME_UP, eventTime = 490))
        engine.onKey(up(HardwareVoiceConstants.KEYCODE_VOLUME_UP))
        assertEquals(1, callbacks.voiceTriggers)
        assertEquals(480L, engine.lastDoubleDeltaMs())
        assertEquals(500L, HardwareVoiceConstants.DOUBLE_PRESS_WINDOW_MS)
    }

    @Test
    fun learnCapturesVolumeUpImmediatelyAsDouble() {
        engine.startLearn()
        engine.onKey(down(HardwareVoiceConstants.KEYCODE_VOLUME_UP, scan = 19))
        assertEquals(1, callbacks.captured.size)
        assertEquals(24, callbacks.captured[0].first)
        assertEquals("double", callbacks.captured[0].third)
        assertEquals(0, callbacks.voiceTriggers)
    }

    @Test
    fun diagnosticModeReportsLearnAndArmed() {
        assertEquals("disabled", engine.diagnosticMode())
        arm(1082, HardwareVoiceGesture.SINGLE)
        assertEquals("armed", engine.diagnosticMode())
        engine.startLearn()
        assertEquals("learn", engine.diagnosticMode())
    }

    @Test
    fun learnRejectsSystemKeysAndKeepsListening() {
        engine.startLearn()
        engine.onKey(down(4))
        assertEquals(listOf(4), callbacks.rejected)
        assertTrue(callbacks.captured.isEmpty())
        engine.onKey(down(1082, scan = 77))
        assertEquals(1, callbacks.captured.size)
        assertEquals(1082, callbacks.captured[0].first)
        assertEquals(77, callbacks.captured[0].second)
        assertEquals("single", callbacks.captured[0].third)
    }

    @Test
    fun unknownOemKeyCanBeStoredAndMatched() {
        engine.startLearn()
        engine.onKey(down(1082, scan = 9))
        arm(1082, HardwareVoiceGesture.SINGLE, scan = 9)
        engine.onKey(down(1082, scan = 9))
        assertEquals(1, callbacks.voiceTriggers)
        engine.onKey(down(1082, scan = 8))
        assertEquals(1, callbacks.voiceTriggers)
    }

    @Test
    fun learnTimeoutLeavesPreviousBindingArmed() {
        arm(1082, HardwareVoiceGesture.SINGLE)
        engine.startLearn()
        scheduler.fire(engine, HardwareVoiceConstants.TOKEN_LEARN)
        assertEquals(1, callbacks.learnTimeouts)
        engine.onKey(down(1082))
        assertEquals(1, callbacks.voiceTriggers)
    }

    @Test
    fun learnCancelLeavesPreviousBindingArmed() {
        arm(1082, HardwareVoiceGesture.SINGLE)
        engine.startLearn()
        engine.cancelLearn()
        assertEquals(1, callbacks.learnCancels)
        engine.onKey(down(1082))
        assertEquals(1, callbacks.voiceTriggers)
    }

    @Test
    fun disabledBindingDoesNotTrigger() {
        engine.configure(
            HardwareVoiceNativeBinding(
                enabled = false,
                keyCode = 1082,
                scanCode = 0,
                gesture = HardwareVoiceGesture.SINGLE,
            ),
        )
        assertFalse(engine.onKey(down(1082)))
        assertEquals(0, callbacks.voiceTriggers)
    }

    @Test
    fun testModeRecognizesWithoutVoiceTrigger() {
        arm(1082, HardwareVoiceGesture.SINGLE)
        engine.startTest()
        engine.onKey(down(1082))
        assertEquals(1, callbacks.testRecognized)
        assertEquals(0, callbacks.voiceTriggers)
    }

    @Test
    fun volumeLongPressRaisesVolumeAndDoesNotTriggerVoice() {
        arm(HardwareVoiceConstants.KEYCODE_VOLUME_UP, HardwareVoiceGesture.DOUBLE)
        engine.onKey(down(HardwareVoiceConstants.KEYCODE_VOLUME_UP, repeat = 0))
        engine.onKey(down(HardwareVoiceConstants.KEYCODE_VOLUME_UP, repeat = 1))
        engine.onKey(down(HardwareVoiceConstants.KEYCODE_VOLUME_UP, repeat = 2))
        engine.onKey(up(HardwareVoiceConstants.KEYCODE_VOLUME_UP))
        assertEquals(0, callbacks.voiceTriggers)
        assertEquals(3, callbacks.volumeRaises)
    }
}
