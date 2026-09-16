import 'dart:io' show Platform;

import 'package:desktop_drop/desktop_drop.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';

import '../auth/auth_controller.dart';
import '../local/local_intake_actions.dart';
import '../voice/voice_transcription_controller.dart';
import 'capture_controller.dart';
import 'capture_draft.dart';

class CaptureScreen extends StatefulWidget {
  const CaptureScreen({
    super.key,
    required this.controller,
    this.authController,
  });

  final CaptureController controller;
  final AuthController? authController;

  @override
  State<CaptureScreen> createState() => _CaptureScreenState();
}

class _CaptureScreenState extends State<CaptureScreen> {
  late final TextEditingController _textController;
  late final TextEditingController _titleController;
  LocalIntakeActions? _intakeActions;

  @override
  void initState() {
    super.initState();
    _textController = TextEditingController(text: widget.controller.draft.text);
    _titleController = TextEditingController(text: widget.controller.draft.title ?? '');
    final auth = widget.authController;
    if (auth != null) {
      _intakeActions = LocalIntakeActions(
        apiClient: auth.apiClient,
        authController: auth,
        captureController: widget.controller,
        attachToCapture: true,
      );
    }
    widget.controller.addListener(_onControllerChanged);
  }

  void _onControllerChanged() {
    final controller = widget.controller;
    if (controller.draft.text != _textController.text) {
      _textController.text = controller.draft.text;
      _textController.selection = TextSelection.collapsed(
        offset: controller.draft.text.length,
      );
    }
    if (controller.submitState == CaptureSubmitState.success &&
        controller.draft.text.isEmpty) {
      _textController.clear();
      _titleController.clear();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Задача создана')),
        );
        controller.clearSuccess();
      }
    }
    setState(() {});
  }

  @override
  void dispose() {
    widget.controller.removeListener(_onControllerChanged);
    _textController.dispose();
    _titleController.dispose();
    super.dispose();
  }

  Future<void> _onVoicePressed() async {
    final controller = widget.controller;
    if (controller.voiceState == VoiceState.recording) {
      await controller.stopVoiceRecordingAndTranscribe();
      return;
    }
    if (controller.submitState == CaptureSubmitState.submitting ||
        (controller.isVoiceBusy &&
            controller.voiceState != VoiceState.recording)) {
      return;
    }
    if (controller.voiceState == VoiceState.error) {
      controller.clearVoiceError();
    }
    await controller.startVoiceRecording();
  }

  @override
  Widget build(BuildContext context) {
    final controller = widget.controller;
    final draft = controller.draft;
    final isSubmitting = controller.submitState == CaptureSubmitState.submitting;
    final inputDisabled = isSubmitting || controller.isVoiceBusy;
    final intakeActions = _intakeActions;

    final body = Scaffold(
      appBar: AppBar(
        title: const Text('Создание задачи'),
        actions: [
          if (intakeActions != null)
            buildAddFileButton(actions: intakeActions, context: context),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (controller.voiceState == VoiceState.recording)
              Material(
                color: Theme.of(context).colorScheme.errorContainer,
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  child: Row(
                    children: [
                      const Icon(Icons.mic, size: 18),
                      const SizedBox(width: 8),
                      const Expanded(
                        child: Text('Запись… нажмите микрофон, чтобы остановить'),
                      ),
                      TextButton(
                        key: const Key('capture_voice_stop'),
                        onPressed: controller.stopVoiceRecordingAndTranscribe,
                        child: const Text('Стоп'),
                      ),
                    ],
                  ),
                ),
              ),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: TextField(
                    controller: _textController,
                    decoration: InputDecoration(
                      labelText: 'Текст задачи',
                      hintText: 'Что нужно сделать?',
                      errorText: draft.isTextTooLong
                          ? 'Текст не должен превышать ${CaptureDraft.maxTextLength} символов'
                          : controller.submitState == CaptureSubmitState.validationError &&
                                  draft.isBlank
                              ? 'Текст не может быть пустым'
                              : null,
                    ),
                    maxLines: 8,
                    maxLength: CaptureDraft.maxTextLength,
                    onChanged: controller.setText,
                    enabled: !inputDisabled,
                  ),
                ),
                const SizedBox(width: 4),
                IconButton(
                  key: const Key('capture_voice_button'),
                  visualDensity: VisualDensity.compact,
                  tooltip: controller.voiceState == VoiceState.recording
                      ? 'Остановить запись'
                      : 'Записать голосовую команду',
                  onPressed: isSubmitting &&
                          controller.voiceState != VoiceState.recording
                      ? null
                      : _onVoicePressed,
                  icon: controller.voiceState == VoiceState.transcribing ||
                          controller.voiceState == VoiceState.starting
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : Icon(
                          controller.voiceState == VoiceState.recording
                              ? Icons.stop_circle_outlined
                              : Icons.mic_none_outlined,
                        ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _titleController,
              decoration: InputDecoration(
                labelText: 'Название (необязательно)',
                errorText: draft.isTitleTooLong
                    ? 'Название не должно превышать ${CaptureDraft.maxTitleLength} символов'
                    : null,
              ),
              maxLength: CaptureDraft.maxTitleLength,
              onChanged: controller.setTitle,
              enabled: !inputDisabled,
            ),
            if (controller.errorMessage != null &&
                controller.submitState != CaptureSubmitState.success)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(
                  controller.errorMessage!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
            if (controller.voiceState == VoiceState.error &&
                controller.voiceErrorMessage != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        controller.voiceErrorMessage!,
                        style: TextStyle(color: Theme.of(context).colorScheme.error),
                      ),
                    ),
                    TextButton(
                      onPressed: isSubmitting ? null : _onVoicePressed,
                      child: const Text('Повторить'),
                    ),
                  ],
                ),
              ),
            if (draft.contextRefs.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text('Прикреплённый контекст', style: Theme.of(context).textTheme.labelLarge),
              const SizedBox(height: 4),
              ...draft.contextRefs.map(
                (ref) => Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Text('Контекст: ${ref.title}'),
                ),
              ),
            ],
            const Spacer(),
            FilledButton(
              key: const Key('capture_submit_button'),
              onPressed: draft.canSubmit && !inputDisabled ? controller.submit : null,
              child: isSubmitting
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Text('Создать задачу'),
            ),
          ],
        ),
      ),
    );

    if (intakeActions == null || kIsWeb || !Platform.isLinux) {
      return body;
    }

    return DropTarget(
      onDragDone: (detail) {
        final paths = detail.files
            .map((file) => file.path)
            .where((path) => path != null)
            .cast<String>()
            .toList();
        intakeActions.registerDroppedFiles(context, paths);
      },
      child: body,
    );
  }
}
