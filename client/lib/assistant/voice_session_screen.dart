import 'package:flutter/material.dart';

import 'assistant_controller.dart';
import 'system_assistant_bridge.dart';
import 'voice_invocation_source.dart';

class VoiceSessionScreen extends StatefulWidget {
  const VoiceSessionScreen({
    super.key,
    required this.assistant,
    required this.systemAssistant,
  });

  final AssistantController assistant;
  final SystemAssistantController systemAssistant;

  @override
  State<VoiceSessionScreen> createState() => _VoiceSessionScreenState();
}

class _VoiceSessionScreenState extends State<VoiceSessionScreen> {
  @override
  void initState() {
    super.initState();
    widget.assistant.addListener(_onChange);
    widget.systemAssistant.addListener(_onChange);
    widget.systemAssistant.onAssistInvoke = _onAssistInvoke;
    WidgetsBinding.instance.addPostFrameCallback((_) => _syncGate());
  }

  @override
  void dispose() {
    widget.assistant.removeListener(_onChange);
    widget.systemAssistant.removeListener(_onChange);
    widget.systemAssistant.onAssistInvoke = null;
    super.dispose();
  }

  void _onChange() {
    widget.assistant.keyguardLocked = widget.systemAssistant.keyguardLocked;
    widget.assistant.lockScreenVoiceEnabled =
        widget.systemAssistant.lockScreenVoiceEnabled;
    widget.assistant.setDrivingSession(
      authorized: widget.systemAssistant.drivingSessionAuthorized,
      sessionId: widget.systemAssistant.drivingSessionId,
    );
    if (mounted) {
      setState(() {});
    }
  }

  Future<void> _syncGate() async {
    await widget.systemAssistant.refresh();
    _onChange();
  }

  void _onAssistInvoke() {
    widget.assistant.keyguardLocked = widget.systemAssistant.keyguardLocked;
    widget.assistant.lockScreenVoiceEnabled =
        widget.systemAssistant.lockScreenVoiceEnabled;
    widget.assistant.setDrivingSession(
      authorized: widget.systemAssistant.drivingSessionAuthorized,
      sessionId: widget.systemAssistant.drivingSessionId,
    );
    widget.assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.systemAssistant,
      startCueAlreadyPlayed: true,
    );
  }

  bool get _launcherEnabled => widget.systemAssistant.lockScreenVoiceEnabled;

  bool get _preparing {
    switch (widget.assistant.voiceState) {
      case AssistantVoiceState.starting:
      case AssistantVoiceState.transcribing:
      case AssistantVoiceState.thinking:
        return true;
      case AssistantVoiceState.idle:
      case AssistantVoiceState.recording:
      case AssistantVoiceState.speaking:
      case AssistantVoiceState.error:
        return false;
    }
  }

  String _statusText() {
    if (!_launcherEnabled) {
      return lockScreenVoiceEnabledMessage;
    }
    switch (widget.assistant.voiceState) {
      case AssistantVoiceState.starting:
        return 'Готовлюсь…';
      case AssistantVoiceState.recording:
        return 'Слушаю… остановлюсь после паузы';
      case AssistantVoiceState.transcribing:
        return 'Распознаю…';
      case AssistantVoiceState.thinking:
        return 'Секретарь думает…';
      case AssistantVoiceState.speaking:
        return 'Секретарь говорит…';
      case AssistantVoiceState.error:
        return widget.assistant.voiceErrorMessage ?? 'Ошибка голоса';
      case AssistantVoiceState.idle:
        return 'Нажмите, чтобы говорить';
    }
  }

  String _buttonLabel() {
    switch (widget.assistant.voiceState) {
      case AssistantVoiceState.recording:
        return 'Стоп';
      case AssistantVoiceState.error:
        return 'Повторить';
      case AssistantVoiceState.speaking:
        return 'Прервать и говорить';
      case AssistantVoiceState.starting:
        return 'Готовлюсь…';
      case AssistantVoiceState.transcribing:
      case AssistantVoiceState.thinking:
        return 'Подождите…';
      case AssistantVoiceState.idle:
        return 'Нажмите, чтобы говорить';
    }
  }

  Future<void> _onLauncherTap() async {
    if (!_launcherEnabled || _preparing) {
      return;
    }
    await widget.assistant.handleVoiceTrigger(
      source: VoiceInvocationSource.lockScreenLauncher,
    );
  }

  @override
  Widget build(BuildContext context) {
    final assistant = widget.assistant;
    final theme = Theme.of(context);
    return Scaffold(
      backgroundColor: theme.colorScheme.surface,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('Секретарь', style: theme.textTheme.titleLarge),
              const SizedBox(height: 16),
              Text(
                _statusText(),
                key: const Key('voice_session_status'),
                style: theme.textTheme.headlineSmall,
                textAlign: TextAlign.center,
              ),
              if (assistant.blocksExternalWrite &&
                  !assistant.drivingSessionAuthorized) ...[
                const SizedBox(height: 16),
                Text(
                  voiceUnlockRequiredSpeech,
                  key: const Key('voice_session_unlock_required'),
                  textAlign: TextAlign.center,
                ),
              ],
              Expanded(
                child: LayoutBuilder(
                  builder: (context, constraints) {
                    final side = constraints.biggest.shortestSide * 0.86;
                    return Center(child: _launcherButton(theme, side));
                  },
                ),
              ),
              TextButton(
                key: const Key('voice_session_close'),
                onPressed: widget.systemAssistant.dismissOverlay,
                child: const Text('Завершить режим вождения'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Color _launcherAccent(ThemeData theme) {
    switch (widget.assistant.voiceState) {
      case AssistantVoiceState.recording:
        return const Color(0xFFE53935);
      case AssistantVoiceState.speaking:
        return theme.colorScheme.tertiary;
      case AssistantVoiceState.error:
        return theme.colorScheme.error;
      case AssistantVoiceState.starting:
      case AssistantVoiceState.transcribing:
      case AssistantVoiceState.thinking:
        return theme.colorScheme.surfaceContainerHighest;
      case AssistantVoiceState.idle:
        return theme.colorScheme.primary;
    }
  }

  Color _launcherOnAccent(ThemeData theme) {
    switch (widget.assistant.voiceState) {
      case AssistantVoiceState.recording:
        return Colors.white;
      case AssistantVoiceState.starting:
      case AssistantVoiceState.transcribing:
      case AssistantVoiceState.thinking:
        return theme.colorScheme.onSurfaceVariant;
      case AssistantVoiceState.error:
        return theme.colorScheme.onError;
      case AssistantVoiceState.speaking:
        return theme.colorScheme.onTertiary;
      case AssistantVoiceState.idle:
        return theme.colorScheme.onPrimary;
    }
  }

  Widget _launcherButton(ThemeData theme, double side) {
    final recording =
        widget.assistant.voiceState == AssistantVoiceState.recording;
    final accent = _launcherAccent(theme);
    final onAccent = _launcherOnAccent(theme);
    final halo = _preparing ? 0.10 : 0.32;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 220),
      curve: Curves.easeOut,
      width: side,
      height: side,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        boxShadow: [
          BoxShadow(
            color: accent.withValues(alpha: halo),
            blurRadius: _preparing ? 16 : 34,
            spreadRadius: _preparing ? 2 : 8,
          ),
          BoxShadow(
            color: accent.withValues(alpha: halo * 0.45),
            blurRadius: _preparing ? 8 : 18,
            spreadRadius: _preparing ? 10 : 20,
          ),
        ],
      ),
      child: Material(
        color: accent,
        shape: const CircleBorder(),
        child: InkWell(
          key: const Key('voice_session_launcher_button'),
          customBorder: const CircleBorder(),
          onTap: (_launcherEnabled && !_preparing) ? _onLauncherTap : null,
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(
                recording ? Icons.stop_rounded : Icons.support_agent,
                size: side * 0.28,
                color: onAccent,
              ),
              const SizedBox(height: 16),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 24),
                child: Text(
                  _buttonLabel(),
                  textAlign: TextAlign.center,
                  style: theme.textTheme.titleLarge?.copyWith(color: onAccent),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
