package com.example.personal_secretary.assistant

import android.app.Activity
import android.app.KeyguardManager
import android.app.role.RoleManager
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.SystemClock
import android.provider.Settings
import android.service.voice.VoiceInteractionService
import com.example.personal_secretary.hardware.HardwareVoiceLog
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

class SystemAssistantPlugin(
    private val activity: Activity,
    messenger: BinaryMessenger,
) : MethodChannel.MethodCallHandler {
    private val channel = MethodChannel(messenger, SystemAssistantConstants.CHANNEL)

    init {
        channel.setMethodCallHandler(this)
        HardwareVoiceLog.line("SystemAssistantPlugin attached")
    }

    fun dispose() {
        channel.setMethodCallHandler(null)
    }

    fun emitAssistInvoke() {
        HardwareVoiceLog.line("onAssistInvoke")
        channel.invokeMethod("onAssistInvoke", null)
    }

    fun emitKeyguard(locked: Boolean) {
        channel.invokeMethod("onKeyguard", locked)
    }

    fun notifyRolePickerClosed() {
        HardwareVoiceLog.line("onRoleResult")
        channel.invokeMethod("onRoleResult", statusMap())
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "getStatus" -> result.success(statusMap())
            "requestAssistantRole" -> {
                requestRole()
                result.success(null)
            }
            "openLockScreenLauncher" -> {
                val keyguard = activity.getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager
                activity.startActivity(
                    lockScreenLauncherIntent(activity, keyguardLocked = keyguard.isKeyguardLocked),
                )
                result.success(null)
            }
            "clearDrivingSession" -> {
                DrivingVoiceSessionRegistry.clear()
                result.success(null)
            }
            "dismiss" -> {
                DrivingVoiceSessionRegistry.clear()
                if (activity is VoiceSessionActivity) {
                    activity.finish()
                }
                result.success(null)
            }
            else -> result.notImplemented()
        }
    }

    private fun requestRole() {
        activity.startActivityForResult(assistantRoleIntent(activity), SystemAssistantConstants.REQUEST_ASSISTANT_ROLE)
    }

    private fun statusMap(): Map<String, Any?> {
        val keyguard = activity.getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager
        var isDefault = false
        var roleAvailable = false
        if (Build.VERSION.SDK_INT >= 29) {
            val roles = activity.getSystemService(RoleManager::class.java)
            roleAvailable = roles?.isRoleAvailable(RoleManager.ROLE_ASSISTANT) == true
            isDefault = roles?.isRoleHeld(RoleManager.ROLE_ASSISTANT) == true
        }
        if (!isDefault) {
            isDefault = VoiceInteractionService.isActiveService(
                activity,
                android.content.ComponentName(
                    activity,
                    SecretaryVoiceInteractionService::class.java,
                ),
            )
        }
        val driving = if (activity is VoiceSessionActivity) {
            validateDrivingSessionIntent(activity.intent)
        } else {
            DrivingSessionSnapshot.none()
        }
        return mapOf(
            "ok" to true,
            "available" to true,
            "protocol" to SystemAssistantConstants.PROTOCOL,
            "isDefaultAssistant" to isDefault,
            "roleManagerAvailable" to roleAvailable,
            "keyguardLocked" to keyguard.isKeyguardLocked,
            "drivingSessionAuthorized" to driving.authorized,
            "drivingSessionId" to driving.sessionId,
        )
    }
}

fun Intent.hasVoiceTriggerExtra(): Boolean {
    return getBooleanExtra(SystemAssistantConstants.EXTRA_VOICE_TRIGGER, false)
}

fun consumeVoiceTrigger(intent: Intent?): Boolean {
    if (intent == null || !intent.hasVoiceTriggerExtra()) {
        return false
    }
    intent.removeExtra(SystemAssistantConstants.EXTRA_VOICE_TRIGGER)
    return true
}

data class VoiceSessionLaunch(
    val autoInvoke: Boolean,
    val mode: String,
)

fun parseVoiceSessionLaunch(hasVoiceTrigger: Boolean, launchMode: String?): VoiceSessionLaunch {
    if (hasVoiceTrigger) {
        return VoiceSessionLaunch(
            autoInvoke = true,
            mode = SystemAssistantConstants.LAUNCH_MODE_ASSIST_INVOKE,
        )
    }
    return VoiceSessionLaunch(
        autoInvoke = false,
        mode = launchMode ?: SystemAssistantConstants.LAUNCH_MODE_LAUNCHER,
    )
}

fun applyLockScreenFlags(activity: Activity) {
    if (Build.VERSION.SDK_INT >= 27) {
        activity.setShowWhenLocked(true)
        activity.setTurnScreenOn(true)
    } else {
        @Suppress("DEPRECATION")
        activity.window.addFlags(
            SystemAssistantConstants.API23_SHOW_WHEN_LOCKED_FLAGS,
        )
    }
}

fun assistantRoleIntent(context: Context): Intent {
    if (Build.VERSION.SDK_INT >= 29) {
        val roles = context.getSystemService(RoleManager::class.java)
        if (roles != null && roles.isRoleAvailable(RoleManager.ROLE_ASSISTANT)) {
            return roles.createRequestRoleIntent(RoleManager.ROLE_ASSISTANT)
        }
    }
    val voiceInput = Intent(Settings.ACTION_VOICE_INPUT_SETTINGS)
    if (voiceInput.resolveActivity(context.packageManager) != null) {
        return voiceInput
    }
    return Intent(Settings.ACTION_SETTINGS)
}

fun launchUnlockedVoice(context: Context) {
    val intent = Intent().setClassName(
        context,
        "com.example.personal_secretary.MainActivity",
    ).apply {
        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)
        putExtra(SystemAssistantConstants.EXTRA_VOICE_TRIGGER, true)
    }
    context.startActivity(intent)
}

fun lockedVoiceIntent(context: Context): Intent {
    return Intent(context, VoiceSessionActivity::class.java).apply {
        addFlags(SystemAssistantConstants.LOCKED_LAUNCH_FLAGS)
        putExtra(SystemAssistantConstants.EXTRA_LAUNCH_MODE, SystemAssistantConstants.LAUNCH_MODE_ASSIST_INVOKE)
        putExtra(SystemAssistantConstants.EXTRA_VOICE_TRIGGER, true)
    }
}

fun lockScreenLauncherIntent(
    context: Context,
    keyguardLocked: Boolean = false,
): Intent {
    return Intent(context, VoiceSessionActivity::class.java).apply {
        addFlags(SystemAssistantConstants.LOCKED_LAUNCH_FLAGS)
        applyDrivingLaunch(this, keyguardLocked = keyguardLocked)
    }
}

fun Intent.isLockScreenLauncherLaunch(): Boolean {
    return getStringExtra(SystemAssistantConstants.EXTRA_LAUNCH_MODE) ==
        SystemAssistantConstants.LAUNCH_MODE_LAUNCHER &&
        !hasVoiceTriggerExtra()
}

fun launchLockedVoice(context: Context) {
    if (!LockedVoiceLaunch.tryMark()) {
        HardwareVoiceLog.line("launchLockedVoice debounce")
        return
    }
    context.startActivity(lockedVoiceIntent(context))
}

object LockedVoiceLaunch {
    @Volatile
    private var lastElapsedMs = 0L

    fun resetForTest() {
        lastElapsedMs = 0L
    }

    fun tryMark(nowElapsedMs: Long = SystemClock.elapsedRealtime()): Boolean {
        synchronized(this) {
            if (nowElapsedMs - lastElapsedMs < SystemAssistantConstants.LOCKED_LAUNCH_DEBOUNCE_MS) {
                return false
            }
            lastElapsedMs = nowElapsedMs
            return true
        }
    }
}
