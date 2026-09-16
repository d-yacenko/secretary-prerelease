package com.example.personal_secretary.assistant

import android.service.voice.VoiceInteractionService
import com.example.personal_secretary.hardware.HardwareVoiceCue
import com.example.personal_secretary.hardware.HardwareVoiceLog

class SecretaryVoiceInteractionService : VoiceInteractionService() {
    override fun onReady() {
        super.onReady()
        HardwareVoiceLog.line("VoiceInteractionService ready")
    }

    override fun onLaunchVoiceAssistFromKeyguard() {
        HardwareVoiceLog.line("onLaunchVoiceAssistFromKeyguard")
        HardwareVoiceCue.playAck(this)
        launchLockedVoice(this)
    }
}
