package com.example.personal_secretary.hardware

object HardwareVoiceConstants {
    const val CHANNEL = "secretary/hardware_voice"
    const val PROTOCOL = "secretary.hardware_voice.v1"
    const val DOUBLE_PRESS_WINDOW_MS = 500L
    const val LEARN_TIMEOUT_MS = 9000L
    const val TEST_TIMEOUT_MS = 9000L

    const val KEYCODE_VOLUME_UP = 24
    const val TOKEN_PENDING = "pending"
    const val TOKEN_LEARN = "learn"
    const val TOKEN_TEST = "test"
}

enum class HardwareVoiceGesture {
    SINGLE,
    DOUBLE,
}

data class HardwareVoiceNativeBinding(
    val enabled: Boolean,
    val keyCode: Int,
    val scanCode: Int,
    val gesture: HardwareVoiceGesture,
)

data class HardwareKeyStroke(
    val keyCode: Int,
    val scanCode: Int,
    val repeatCount: Int,
    val isDown: Boolean,
    val eventTimeMs: Long,
    val androidKeyName: String? = null,
)

interface HardwareVoiceScheduler {
    fun schedule(token: String, delayMs: Long)

    fun cancel(token: String)
}

interface HardwareVoiceCallbacks {
    fun onVoiceTrigger()

    fun onLearnCaptured(keyCode: Int, scanCode: Int, androidKeyName: String?, gesture: String)

    fun onLearnRejected(keyCode: Int, message: String)

    fun onLearnTimeout()

    fun onLearnCancelled()

    fun onTestRecognized()

    fun onTestTimeout()

    fun onTestCancelled()

    fun raiseVolume()
}

object HardwareVoiceKeyPolicy {
    private val rejected = setOf(
        3, // HOME
        4, // BACK
        5, // CALL
        6, // ENDCALL
        25, // VOLUME_DOWN
        26, // POWER
        82, // MENU
        164, // VOLUME_MUTE
        187, // APP_SWITCH
        223, // SLEEP
        224, // WAKEUP
        276, // SOFT_SLEEP
        280, // SYSTEM_NAVIGATION_UP
        281, // SYSTEM_NAVIGATION_DOWN
        282, // SYSTEM_NAVIGATION_LEFT
        283, // SYSTEM_NAVIGATION_RIGHT
    )

    fun isRejected(keyCode: Int): Boolean = keyCode in rejected

    fun displayLabel(keyCode: Int, androidKeyName: String?): String {
        if (keyCode == HardwareVoiceConstants.KEYCODE_VOLUME_UP) {
            return "Громкость +"
        }
        val name = androidKeyName?.trim().orEmpty()
        if (name.isNotEmpty()) {
            val lower = name.lowercase()
            if (lower.contains("bixby") ||
                (lower.contains("assist") && !lower.startsWith("keycode_"))
            ) {
                return name
            }
        }
        return "Дополнительная кнопка (код $keyCode)"
    }

    fun matches(binding: HardwareVoiceNativeBinding, stroke: HardwareKeyStroke): Boolean {
        if (stroke.keyCode != binding.keyCode) {
            return false
        }
        if (binding.scanCode != 0 && stroke.scanCode != binding.scanCode) {
            return false
        }
        return true
    }
}

private enum class EngineMode {
    DISABLED,
    ARMED,
    LEARN,
    TEST,
}

class HardwareVoiceEngine(
    private val callbacks: HardwareVoiceCallbacks,
    private val scheduler: HardwareVoiceScheduler,
    private val clock: () -> Long = { 0L },
) {
    private var mode = EngineMode.DISABLED
    private var binding: HardwareVoiceNativeBinding? = null
    private var pendingDown = false
    private var firstDownEventTimeMs = 0L
    private var doubleDeltaMs: Long? = null
    private var longPressActive = false
    private var volumeLongPressStarted = false

    fun configure(next: HardwareVoiceNativeBinding) {
        cancelPending(fireVolumeIfNeeded = true)
        binding = next
        mode = if (next.enabled) EngineMode.ARMED else EngineMode.DISABLED
        longPressActive = false
        volumeLongPressStarted = false
    }

    fun diagnosticMode(): String = when (mode) {
        EngineMode.DISABLED -> "disabled"
        EngineMode.ARMED -> "armed"
        EngineMode.LEARN -> "learn"
        EngineMode.TEST -> "test"
    }

    fun lastDoubleDeltaMs(): Long? = doubleDeltaMs

    fun diagnosticBinding(): HardwareVoiceNativeBinding? = binding

    fun wouldMatch(stroke: HardwareKeyStroke): Boolean {
        val current = binding ?: return false
        if (mode == EngineMode.DISABLED) {
            return false
        }
        return HardwareVoiceKeyPolicy.matches(current, stroke)
    }

    fun startLearn(timeoutMs: Long = HardwareVoiceConstants.LEARN_TIMEOUT_MS) {
        cancelPending(fireVolumeIfNeeded = true)
        mode = EngineMode.LEARN
        scheduler.cancel(HardwareVoiceConstants.TOKEN_TEST)
        scheduler.schedule(HardwareVoiceConstants.TOKEN_LEARN, timeoutMs)
    }

    fun cancelLearn() {
        if (mode != EngineMode.LEARN) {
            return
        }
        scheduler.cancel(HardwareVoiceConstants.TOKEN_LEARN)
        restoreArmedOrDisabled()
        callbacks.onLearnCancelled()
    }

    fun startTest(timeoutMs: Long = HardwareVoiceConstants.TEST_TIMEOUT_MS) {
        val current = binding
        if (current == null || !current.enabled) {
            callbacks.onTestCancelled()
            return
        }
        cancelPending(fireVolumeIfNeeded = true)
        mode = EngineMode.TEST
        scheduler.cancel(HardwareVoiceConstants.TOKEN_LEARN)
        scheduler.schedule(HardwareVoiceConstants.TOKEN_TEST, timeoutMs)
    }

    fun cancelTest() {
        if (mode != EngineMode.TEST) {
            return
        }
        scheduler.cancel(HardwareVoiceConstants.TOKEN_TEST)
        cancelPending(fireVolumeIfNeeded = true)
        restoreArmedOrDisabled()
        callbacks.onTestCancelled()
    }

    fun onHostPause() {
        cancelPending(fireVolumeIfNeeded = true)
        if (mode == EngineMode.LEARN) {
            scheduler.cancel(HardwareVoiceConstants.TOKEN_LEARN)
            restoreArmedOrDisabled()
            callbacks.onLearnCancelled()
        } else if (mode == EngineMode.TEST) {
            scheduler.cancel(HardwareVoiceConstants.TOKEN_TEST)
            restoreArmedOrDisabled()
            callbacks.onTestCancelled()
        }
        longPressActive = false
        volumeLongPressStarted = false
    }

    fun onScheduled(token: String) {
        when (token) {
            HardwareVoiceConstants.TOKEN_PENDING -> {
                val current = binding
                pendingDown = false
                if (firstDownEventTimeMs != 0L) {
                    doubleDeltaMs = clock() - firstDownEventTimeMs
                }
                firstDownEventTimeMs = 0L
                if (current != null && current.keyCode == HardwareVoiceConstants.KEYCODE_VOLUME_UP) {
                    callbacks.raiseVolume()
                }
            }
            HardwareVoiceConstants.TOKEN_LEARN -> {
                if (mode == EngineMode.LEARN) {
                    restoreArmedOrDisabled()
                    callbacks.onLearnTimeout()
                }
            }
            HardwareVoiceConstants.TOKEN_TEST -> {
                if (mode == EngineMode.TEST) {
                    cancelPending(fireVolumeIfNeeded = true)
                    restoreArmedOrDisabled()
                    callbacks.onTestTimeout()
                }
            }
        }
    }

    /**
     * @return true if the event is consumed and must not be dispatched further.
     */
    fun onKey(stroke: HardwareKeyStroke): Boolean {
        return when (mode) {
            EngineMode.DISABLED -> false
            EngineMode.LEARN -> handleLearn(stroke)
            EngineMode.ARMED, EngineMode.TEST -> handleArmed(stroke, test = mode == EngineMode.TEST)
        }
    }

    private fun handleLearn(stroke: HardwareKeyStroke): Boolean {
        if (!stroke.isDown || stroke.repeatCount != 0) {
            return stroke.isDown
        }
        if (HardwareVoiceKeyPolicy.isRejected(stroke.keyCode)) {
            callbacks.onLearnRejected(
                stroke.keyCode,
                "Эту кнопку нельзя назначить голосовому помощнику.",
            )
            return true
        }
        scheduler.cancel(HardwareVoiceConstants.TOKEN_LEARN)
        val gesture =
            if (stroke.keyCode == HardwareVoiceConstants.KEYCODE_VOLUME_UP) {
                "double"
            } else {
                "single"
            }
        restoreArmedOrDisabled()
        callbacks.onLearnCaptured(
            stroke.keyCode,
            stroke.scanCode,
            stroke.androidKeyName,
            gesture,
        )
        return true
    }

    private fun handleArmed(stroke: HardwareKeyStroke, test: Boolean): Boolean {
        val current = binding ?: return false
        if (!HardwareVoiceKeyPolicy.matches(current, stroke)) {
            return false
        }
        if (!stroke.isDown) {
            longPressActive = false
            volumeLongPressStarted = false
            return true
        }
        if (current.gesture == HardwareVoiceGesture.SINGLE) {
            if (stroke.repeatCount == 0) {
                emitTrigger(test)
            }
            return true
        }
        return handleDouble(current, stroke, test)
    }

    private fun handleDouble(
        current: HardwareVoiceNativeBinding,
        stroke: HardwareKeyStroke,
        test: Boolean,
    ): Boolean {
        val volume = current.keyCode == HardwareVoiceConstants.KEYCODE_VOLUME_UP
        if (stroke.repeatCount > 0) {
            if (pendingDown) {
                scheduler.cancel(HardwareVoiceConstants.TOKEN_PENDING)
                pendingDown = false
                longPressActive = true
                if (volume) {
                    callbacks.raiseVolume()
                    callbacks.raiseVolume()
                    volumeLongPressStarted = true
                }
            } else if (longPressActive && volume) {
                callbacks.raiseVolume()
            }
            return true
        }
        if (pendingDown) {
            scheduler.cancel(HardwareVoiceConstants.TOKEN_PENDING)
            pendingDown = false
            doubleDeltaMs = stroke.eventTimeMs - firstDownEventTimeMs
            firstDownEventTimeMs = 0L
            emitTrigger(test)
            return true
        }
        pendingDown = true
        firstDownEventTimeMs = stroke.eventTimeMs
        doubleDeltaMs = null
        scheduler.schedule(
            HardwareVoiceConstants.TOKEN_PENDING,
            HardwareVoiceConstants.DOUBLE_PRESS_WINDOW_MS,
        )
        return true
    }

    private fun emitTrigger(test: Boolean) {
        if (test) {
            scheduler.cancel(HardwareVoiceConstants.TOKEN_TEST)
            restoreArmedOrDisabled()
            callbacks.onTestRecognized()
        } else {
            callbacks.onVoiceTrigger()
        }
    }

    private fun cancelPending(fireVolumeIfNeeded: Boolean) {
        val current = binding
        val wasPending = pendingDown
        scheduler.cancel(HardwareVoiceConstants.TOKEN_PENDING)
        pendingDown = false
        firstDownEventTimeMs = 0L
        if (fireVolumeIfNeeded &&
            wasPending &&
            current != null &&
            current.keyCode == HardwareVoiceConstants.KEYCODE_VOLUME_UP
        ) {
            callbacks.raiseVolume()
        }
    }

    private fun restoreArmedOrDisabled() {
        val current = binding
        mode = if (current != null && current.enabled) EngineMode.ARMED else EngineMode.DISABLED
        pendingDown = false
        firstDownEventTimeMs = 0L
        longPressActive = false
        volumeLongPressStarted = false
    }
}
