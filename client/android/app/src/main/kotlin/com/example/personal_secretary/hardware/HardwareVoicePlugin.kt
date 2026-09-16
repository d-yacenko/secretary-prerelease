package com.example.personal_secretary.hardware

import android.content.Context
import android.media.AudioManager
import android.os.Handler
import android.os.Looper
import android.view.KeyEvent
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

class HardwareVoicePlugin(
    private val context: Context,
    messenger: BinaryMessenger,
    private val channel: MethodChannel = MethodChannel(
        messenger,
        HardwareVoiceConstants.CHANNEL,
    ),
) : MethodChannel.MethodCallHandler, HardwareVoiceCallbacks, HardwareVoiceScheduler {
    private val handler = Handler(Looper.getMainLooper())
    private val posted = mutableMapOf<String, Runnable>()
    private val engine = HardwareVoiceEngine(this, this) {
        android.os.SystemClock.uptimeMillis()
    }
    private var lastCallback = "none"
    private var listening = false

    init {
        channel.setMethodCallHandler(this)
        HardwareVoiceLog.line("plugin created protocol=${HardwareVoiceConstants.PROTOCOL}")
    }

    fun diagnosticMode(): String = engine.diagnosticMode()

    fun dispose() {
        HardwareVoiceLog.line("plugin dispose")
        channel.setMethodCallHandler(null)
        posted.values.forEach { handler.removeCallbacks(it) }
        posted.clear()
    }

    fun onHostPause() {
        HardwareVoiceLog.line("onHostPause mode=${engine.diagnosticMode()}")
        engine.onHostPause()
    }

    fun handleKeyEvent(event: KeyEvent): Boolean {
        lastCallback = "none"
        val name = try {
            KeyEvent.keyCodeToString(event.keyCode)
        } catch (_: Throwable) {
            null
        }
        val stroke = HardwareKeyStroke(
            keyCode = event.keyCode,
            scanCode = event.scanCode,
            repeatCount = event.repeatCount,
            isDown = event.action == KeyEvent.ACTION_DOWN,
            eventTimeMs = event.eventTime,
            androidKeyName = name,
        )
        val mode = engine.diagnosticMode()
        val matched = engine.wouldMatch(stroke)
        val consumed = engine.onKey(stroke)
        HardwareVoiceLog.dispatch(event, mode, matched, consumed, lastCallback)
        val delta = engine.lastDoubleDeltaMs()
        if (delta != null && consumed) {
            HardwareVoiceLog.line("doubleDeltaMs=$delta windowMs=${HardwareVoiceConstants.DOUBLE_PRESS_WINDOW_MS}")
        }
        return consumed
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "getStatus" -> {
                HardwareVoiceLog.line("getStatus mode=${engine.diagnosticMode()}")
                result.success(statusMap())
            }
            "configure" -> {
                val enabled = call.argument<Boolean>("enabled") ?: false
                val keyCode = call.argument<Int>("keyCode") ?: 0
                val scanCode = call.argument<Int>("scanCode") ?: 0
                val gestureRaw = call.argument<String>("gesture") ?: "single"
                val gesture =
                    if (gestureRaw == "double") {
                        HardwareVoiceGesture.DOUBLE
                    } else {
                        HardwareVoiceGesture.SINGLE
                    }
                val binding = HardwareVoiceNativeBinding(
                    enabled = enabled,
                    keyCode = if (keyCode == HardwareVoiceConstants.KEYCODE_VOLUME_UP) {
                        HardwareVoiceConstants.KEYCODE_VOLUME_UP
                    } else {
                        keyCode
                    },
                    scanCode = if (keyCode == HardwareVoiceConstants.KEYCODE_VOLUME_UP) 0 else scanCode,
                    gesture = if (keyCode == HardwareVoiceConstants.KEYCODE_VOLUME_UP) {
                        HardwareVoiceGesture.DOUBLE
                    } else {
                        gesture
                    },
                )
                HardwareVoiceLog.line(
                    "configure enabled=${binding.enabled} keyCode=${binding.keyCode} " +
                        "scanCode=${binding.scanCode} gesture=${binding.gesture}",
                )
                engine.configure(binding)
                if (!binding.enabled) {
                    listening = false
                }
                result.success(statusMap(ok = true))
            }
            "startLearn" -> {
                val timeout = (call.argument<Int>("timeoutMs") ?: HardwareVoiceConstants.LEARN_TIMEOUT_MS.toInt()).toLong()
                HardwareVoiceLog.line("startLearn timeoutMs=$timeout")
                engine.startLearn(timeout)
                result.success(null)
            }
            "cancelLearn" -> {
                HardwareVoiceLog.line("cancelLearn")
                engine.cancelLearn()
                result.success(null)
            }
            "startTest" -> {
                val timeout = (call.argument<Int>("timeoutMs") ?: HardwareVoiceConstants.TEST_TIMEOUT_MS.toInt()).toLong()
                HardwareVoiceLog.line("startTest timeoutMs=$timeout")
                engine.startTest(timeout)
                result.success(null)
            }
            "cancelTest" -> {
                HardwareVoiceLog.line("cancelTest")
                engine.cancelTest()
                result.success(null)
            }
            "setListening" -> {
                listening = call.argument<Boolean>("listening") ?: false
                HardwareVoiceLog.line("setListening listening=$listening")
                result.success(null)
            }
            else -> result.notImplemented()
        }
    }

    private fun statusMap(ok: Boolean = true): Map<String, Any?> {
        val current = engine.diagnosticBinding()
        return mapOf(
            "ok" to ok,
            "available" to true,
            "protocol" to HardwareVoiceConstants.PROTOCOL,
            "mode" to engine.diagnosticMode(),
            "enabled" to (current?.enabled == true),
            "keyCode" to (current?.keyCode ?: 0),
            "scanCode" to (current?.scanCode ?: 0),
            "gesture" to if (current?.gesture == HardwareVoiceGesture.DOUBLE) "double" else "single",
        )
    }

    override fun schedule(token: String, delayMs: Long) {
        posted.remove(token)?.let { handler.removeCallbacks(it) }
        val runnable = Runnable {
            posted.remove(token)
            engine.onScheduled(token)
        }
        posted[token] = runnable
        handler.postDelayed(runnable, delayMs)
    }

    override fun cancel(token: String) {
        posted.remove(token)?.let { handler.removeCallbacks(it) }
    }

    override fun onVoiceTrigger() {
        lastCallback = "voice"
        val acceptedElapsed = HardwareVoiceCue.nowElapsedMs()
        if (listening) {
            listening = false
            HardwareVoiceLog.line(
                "callback=voice cue=none reason=defer_stop_until_recorder_stop " +
                    "acceptedElapsedMs=$acceptedElapsed cueElapsedMs=${HardwareVoiceCue.nowElapsedMs()}",
            )
        } else {
            HardwareVoiceCue.playAck(context)
            listening = true
            HardwareVoiceLog.line(
                "callback=voice cue=ack acceptedElapsedMs=$acceptedElapsed cueElapsedMs=${HardwareVoiceCue.nowElapsedMs()}",
            )
        }
        handler.post { channel.invokeMethod("onVoiceTrigger", null) }
    }

    override fun onLearnCaptured(
        keyCode: Int,
        scanCode: Int,
        androidKeyName: String?,
        gesture: String,
    ) {
        lastCallback = "learn-captured"
        HardwareVoiceLog.line(
            "callback=learn-captured keyCode=$keyCode scanCode=$scanCode gesture=$gesture",
        )
        handler.post {
            channel.invokeMethod(
                "onLearnResult",
                mapOf(
                    "status" to "captured",
                    "keyCode" to keyCode,
                    "scanCode" to scanCode,
                    "androidKeyName" to androidKeyName,
                    "gesture" to gesture,
                    "label" to HardwareVoiceKeyPolicy.displayLabel(keyCode, androidKeyName),
                ),
            )
        }
    }

    override fun onLearnRejected(keyCode: Int, message: String) {
        lastCallback = "learn-rejected"
        HardwareVoiceLog.line("callback=learn-rejected keyCode=$keyCode")
        handler.post {
            channel.invokeMethod(
                "onLearnResult",
                mapOf(
                    "status" to "rejected",
                    "keyCode" to keyCode,
                    "message" to message,
                ),
            )
        }
    }

    override fun onLearnTimeout() {
        lastCallback = "learn-timeout"
        HardwareVoiceLog.line("callback=learn-timeout")
        handler.post {
            channel.invokeMethod("onLearnResult", mapOf("status" to "timeout"))
        }
    }

    override fun onLearnCancelled() {
        lastCallback = "learn-cancelled"
        HardwareVoiceLog.line("callback=learn-cancelled")
        handler.post {
            channel.invokeMethod("onLearnResult", mapOf("status" to "cancelled"))
        }
    }

    override fun onTestRecognized() {
        lastCallback = "test-recognized"
        HardwareVoiceLog.line("callback=test-recognized")
        handler.post {
            channel.invokeMethod("onTestResult", mapOf("status" to "recognized"))
        }
    }

    override fun onTestTimeout() {
        lastCallback = "test-timeout"
        HardwareVoiceLog.line("callback=test-timeout")
        handler.post {
            channel.invokeMethod("onTestResult", mapOf("status" to "timeout"))
        }
    }

    override fun onTestCancelled() {
        lastCallback = "test-cancelled"
        HardwareVoiceLog.line("callback=test-cancelled")
        handler.post {
            channel.invokeMethod("onTestResult", mapOf("status" to "cancelled"))
        }
    }

    override fun raiseVolume() {
        lastCallback = "raise-volume"
        HardwareVoiceLog.line("callback=raise-volume")
        val audio = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        audio.adjustSuggestedStreamVolume(
            AudioManager.ADJUST_RAISE,
            AudioManager.USE_DEFAULT_STREAM_TYPE,
            AudioManager.FLAG_SHOW_UI or AudioManager.FLAG_REMOVE_SOUND_AND_VIBRATE,
        )
    }
}
