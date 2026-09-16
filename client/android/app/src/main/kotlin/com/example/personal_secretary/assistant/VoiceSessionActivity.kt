package com.example.personal_secretary.assistant

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.os.Bundle
import com.example.personal_secretary.hardware.HardwareVoiceLog
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine

class VoiceSessionActivity : FlutterActivity() {
    private var systemAssistant: SystemAssistantPlugin? = null
    private var pendingAssist = 0
    private val unlockReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action == Intent.ACTION_USER_PRESENT) {
                systemAssistant?.emitKeyguard(false)
            }
        }
    }

    override fun getInitialRoute(): String = SystemAssistantConstants.ROUTE_VOICE_SESSION

    override fun onCreate(savedInstanceState: Bundle?) {
        applyLockScreenFlags(this)
        super.onCreate(savedInstanceState)
        HardwareVoiceLog.line("VoiceSessionActivity created")
        if (consumeVoiceTrigger(intent)) {
            pendingAssist += 1
        }
        val filter = IntentFilter(Intent.ACTION_USER_PRESENT)
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(unlockReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            registerReceiver(unlockReceiver, filter)
        }
    }

    override fun onStart() {
        super.onStart()
        applyLockScreenFlags(this)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (consumeVoiceTrigger(intent)) {
            pendingAssist += 1
            deliverPendingAssist()
        }
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        systemAssistant = SystemAssistantPlugin(this, flutterEngine.dartExecutor.binaryMessenger)
        HardwareVoiceLog.line("VoiceSessionActivity plugin attached")
    }

    override fun onResume() {
        super.onResume()
        deliverPendingAssist()
    }

    override fun cleanUpFlutterEngine(flutterEngine: FlutterEngine) {
        systemAssistant?.dispose()
        systemAssistant = null
        super.cleanUpFlutterEngine(flutterEngine)
    }

    override fun onDestroy() {
        try {
            unregisterReceiver(unlockReceiver)
        } catch (_: Throwable) {
        }
        if (isFinishing) {
            DrivingVoiceSessionRegistry.clear()
        }
        super.onDestroy()
    }

    private fun deliverPendingAssist() {
        val plugin = systemAssistant ?: return
        while (pendingAssist > 0) {
            pendingAssist -= 1
            plugin.emitAssistInvoke()
        }
    }
}
