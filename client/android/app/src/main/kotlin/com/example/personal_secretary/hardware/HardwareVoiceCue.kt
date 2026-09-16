package com.example.personal_secretary.hardware

import android.content.Context
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Build
import android.os.SystemClock
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager

object HardwareVoiceCue {
    fun playAck(context: Context) {
        haptic(context, 25)
        tone(ToneGenerator.TONE_PROP_NACK, durationMs = 40, volume = 45)
    }

    fun playStart(context: Context) {
        playAck(context)
    }

    fun playStop(context: Context) {
        tone(ToneGenerator.TONE_PROP_ACK)
    }

    fun nowElapsedMs(): Long = SystemClock.elapsedRealtime()

    private fun tone(type: Int, durationMs: Int = 90, volume: Int = 70) {
        var generator: ToneGenerator? = null
        try {
            generator = ToneGenerator(AudioManager.STREAM_MUSIC, volume)
            generator.startTone(type, durationMs)
        } catch (_: Throwable) {
            try {
                generator?.release()
            } catch (_: Throwable) {
            }
            return
        }
        android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({
            try {
                generator?.release()
            } catch (_: Throwable) {
            }
        }, 120)
    }

    private fun haptic(context: Context, durationMs: Long) {
        try {
            val vibrator = if (Build.VERSION.SDK_INT >= 31) {
                val manager = context.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager
                manager.defaultVibrator
            } else {
                @Suppress("DEPRECATION")
                context.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
            }
            if (Build.VERSION.SDK_INT >= 26) {
                vibrator.vibrate(
                    VibrationEffect.createOneShot(durationMs, VibrationEffect.DEFAULT_AMPLITUDE),
                )
            } else {
                @Suppress("DEPRECATION")
                vibrator.vibrate(durationMs)
            }
        } catch (_: Throwable) {
        }
    }
}
