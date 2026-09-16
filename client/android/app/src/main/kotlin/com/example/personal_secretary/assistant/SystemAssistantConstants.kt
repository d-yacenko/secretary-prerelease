package com.example.personal_secretary.assistant

object SystemAssistantConstants {
    const val CHANNEL = "secretary/system_assistant"
    const val PROTOCOL = "secretary.system_assistant.v1"
    const val EXTRA_VOICE_TRIGGER = "secretary.voice_trigger"
    const val EXTRA_LAUNCH_MODE = "secretary.voice_session_launch_mode"
    const val EXTRA_DRIVING_SESSION_ID = "secretary.driving_voice_session_id"
    const val LAUNCH_MODE_LAUNCHER = "launcher"
    const val LAUNCH_MODE_ASSIST_INVOKE = "assistInvoke"
    const val ROUTE_VOICE_SESSION = "/voice_session"
    const val REQUEST_ASSISTANT_ROLE = 7101
    const val LOCKED_LAUNCH_DEBOUNCE_MS = 800L

    const val LOCKED_LAUNCH_FLAGS =
        android.content.Intent.FLAG_ACTIVITY_NEW_TASK or
            android.content.Intent.FLAG_ACTIVITY_SINGLE_TOP or
            android.content.Intent.FLAG_ACTIVITY_CLEAR_TOP

    // API 23–26 window flags. Do not add FLAG_KEEP_SCREEN_ON: the device
    // must be allowed to sleep; show-when-locked is enough to reappear on wake.
    const val API23_SHOW_WHEN_LOCKED_FLAGS =
        android.view.WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
            android.view.WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
}
