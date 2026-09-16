package com.example.personal_secretary.hardware

import android.util.Log
import android.view.KeyEvent
import com.example.personal_secretary.BuildConfig

object HardwareVoiceLog {
    const val TAG = "SecretaryHwVoice"

    fun enabled(): Boolean = BuildConfig.DEBUG

    fun line(message: String) {
        if (!enabled()) {
            return
        }
        Log.i(TAG, message)
    }

    fun dispatch(
        event: KeyEvent,
        mode: String,
        matched: Boolean,
        consumed: Boolean,
        callback: String,
    ) {
        if (!enabled()) {
            return
        }
        val action = when (event.action) {
            KeyEvent.ACTION_DOWN -> "DOWN"
            KeyEvent.ACTION_UP -> "UP"
            else -> event.action.toString()
        }
        Log.i(
            TAG,
            "dispatchKeyEvent action=$action keyCode=${event.keyCode} " +
                "scanCode=${event.scanCode} repeatCount=${event.repeatCount} " +
                "eventTime=${event.eventTime} mode=$mode matched=$matched " +
                "consumed=$consumed callback=$callback",
        )
    }
}
