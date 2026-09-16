package com.example.personal_secretary.assistant

import android.app.KeyguardManager
import android.content.Context
import android.os.Bundle
import android.service.voice.VoiceInteractionSession
import com.example.personal_secretary.hardware.HardwareVoiceCue
import com.example.personal_secretary.hardware.HardwareVoiceLog

class SecretaryVoiceInteractionSession(context: Context) : VoiceInteractionSession(context) {
    override fun onShow(args: Bundle?, showFlags: Int) {
        super.onShow(args, showFlags)
        HardwareVoiceLog.line("VoiceInteractionSession onShow flags=$showFlags")
        val keyguard = context.getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager
        if (keyguard.isKeyguardLocked) {
            // Keyguard entry is VoiceInteractionService.onLaunchVoiceAssistFromKeyguard().
            hide()
            return
        }
        HardwareVoiceCue.playAck(context)
        launchUnlockedVoice(context)
        hide()
    }
}
