import 'dart:io' show Platform;

import 'package:desktop_drop/desktop_drop.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/api_models.dart';
import '../api/secretary_api_client.dart';
import '../assistant/assistant_controller.dart';
import '../assistant/voice_invocation_source.dart';
import '../auth/auth_controller.dart';
import '../capture/capture_controller.dart';
import '../local/local_intake_actions.dart';
import '../navigation/secretary_navigation.dart';
import '../ui/domain_labels.dart';
import '../ui/object_bookmark_controller.dart';
import 'assistant_message_body.dart';
import 'assistant_reference_chip.dart';

class AssistantScreen extends StatefulWidget {
  const AssistantScreen({
    super.key,
    required this.controller,
    required this.apiClient,
    required this.authController,
    required this.captureController,
    this.bookmarkController,
  });

  final AssistantController controller;
  final SecretaryApiClient apiClient;
  final AuthController authController;
  final CaptureController captureController;
  final ObjectBookmarkController? bookmarkController;

  @override
  State<AssistantScreen> createState() => _AssistantScreenState();
}

class _AssistantScreenState extends State<AssistantScreen> {
  final _inputController = TextEditingController();
  final _scrollController = ScrollController();
  AssistantSendState? _lastSendState;
  late final LocalIntakeActions _intakeActions;

  @override
  void initState() {
    super.initState();
    _intakeActions = LocalIntakeActions(
      apiClient: widget.apiClient,
      authController: widget.authController,
      captureController: widget.captureController,
      assistantController: widget.controller,
    );
    _lastSendState = widget.controller.sendState;
    widget.controller.addListener(_onControllerChanged);
    if (widget.controller.pendingRetryMessage != null &&
        widget.controller.sendState == AssistantSendState.error) {
      _inputController.text = widget.controller.pendingRetryMessage!;
    }
    if (widget.controller.messages.isNotEmpty) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _scrollToEnd());
    }
    widget.controller.restorePersistentConversation();
  }

  @override
  void dispose() {
    widget.controller.removeListener(_onControllerChanged);
    _inputController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _onControllerChanged() {
    if (mounted) {
      final controller = widget.controller;
      final pending = controller.pendingRetryMessage;
      if (pending != null &&
          controller.sendState == AssistantSendState.error &&
          _inputController.text != pending) {
        _inputController.text = pending;
        _inputController.selection = TextSelection.collapsed(
          offset: pending.length,
        );
      }
      if (_lastSendState == AssistantSendState.sending &&
          controller.sendState == AssistantSendState.idle &&
          pending == null) {
        _inputController.clear();
      }
      final replyCompleted =
          _lastSendState == AssistantSendState.sending &&
          controller.sendState == AssistantSendState.idle;
      _lastSendState = controller.sendState;
      setState(() {});
      if (replyCompleted) {
        _scrollToEnd();
      }
    }
  }

  void _scrollToEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scrollController.hasClients) {
        return;
      }
      final target = _scrollController.position.maxScrollExtent;
      if (!target.isFinite) {
        return;
      }
      if ((_scrollController.offset - target).abs() < 2) {
        return;
      }
      _scrollController.jumpTo(target);
    });
  }

  Future<void> _send() async {
    final text = _inputController.text;
    await widget.controller.sendMessage(text);
    if (widget.controller.sendState != AssistantSendState.error) {
      _inputController.clear();
    }
  }

  bool get _isDesktopPlatform {
    if (kIsWeb) {
      return false;
    }
    return Platform.isLinux || Platform.isMacOS || Platform.isWindows;
  }

  String get _sendTooltip =>
      _isDesktopPlatform ? 'Отправить (Ctrl+Enter)' : 'Отправить';

  KeyEventResult _handleInputKeyEvent(FocusNode node, KeyEvent event) {
    if (event is! KeyDownEvent) {
      return KeyEventResult.ignored;
    }
    if (event.logicalKey != LogicalKeyboardKey.enter) {
      return KeyEventResult.ignored;
    }
    final ctrl = HardwareKeyboard.instance.isControlPressed;
    final meta = HardwareKeyboard.instance.isMetaPressed;
    if (!ctrl && !meta) {
      return KeyEventResult.ignored;
    }
    if (widget.controller.isInputBlocked) {
      return KeyEventResult.handled;
    }
    _send();
    return KeyEventResult.handled;
  }

  Future<void> _onVoicePressed() async {
    await widget.controller.handleVoiceTrigger(
      source: VoiceInvocationSource.screenMic,
    );
  }

  void _openReference(AssistantReference reference) {
    openObjectDetail(
      context,
      objectId: reference.objectId,
      apiClient: widget.apiClient,
      authController: widget.authController,
      captureController: widget.captureController,
      assistantController: widget.controller,
      onAskSecretary: (object) {
        widget.controller.setObjectContext(object);
      },
      bookmarkController: widget.bookmarkController,
    );
  }

  void _openAffectedObject(AssistantAffectedObject affected) {
    openObjectDetail(
      context,
      objectId: affected.objectId,
      apiClient: widget.apiClient,
      authController: widget.authController,
      captureController: widget.captureController,
      assistantController: widget.controller,
      onAskSecretary: (object) {
        widget.controller.setObjectContext(object);
      },
      bookmarkController: widget.bookmarkController,
    );
  }

  String _objectContextLabel(AssistantContextRef contextRef) {
    return 'Контекст: ${objectKindLabel(contextRef.kind)} — ${contextRef.title}';
  }

  String _notificationContextLabel(AssistantContextRef contextRef) {
    return 'Контекст: Уведомление — ${contextRef.title}';
  }

  @override
  Widget build(BuildContext context) {
    final controller = widget.controller;
    final inputDisabled = controller.isInputBlocked;
    final body = Column(
      children: [
        Row(
          children: [
            IconButton(
              key: const Key('assistant_history_button'),
              tooltip: 'Диалоги',
              onPressed: () {
                final wide = MediaQuery.sizeOf(context).width >= 600;
                if (wide) {
                  controller.toggleHistoryPanel();
                } else {
                  Scaffold.of(context).openEndDrawer();
                }
              },
              icon: const Icon(Icons.forum_outlined),
            ),
            TextButton(
              key: const Key('assistant_new_conversation'),
              onPressed: controller.canSwitchConversation
                  ? () => controller.startNewConversation()
                  : null,
              child: const Text('Новый диалог'),
            ),
            if (controller.conversationSwitchNotice != null)
              Expanded(
                child: Text(
                  controller.conversationSwitchNotice!,
                  key: const Key('assistant_conversation_switch_notice'),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
          ],
        ),
        if (controller.objectContext != null)
          _ContextBanner(
            label: _objectContextLabel(controller.objectContext!),
            onClear: controller.clearObjectContext,
          ),
        if (controller.notificationContext != null)
          _ContextBanner(
            label: _notificationContextLabel(controller.notificationContext!),
            onClear: controller.clearNotificationContext,
          ),
        if (controller.voiceState == AssistantVoiceState.recording)
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
                    key: const Key('assistant_voice_stop'),
                    onPressed: controller.stopVoiceRecordingAndTranscribe,
                    child: const Text('Стоп'),
                  ),
                ],
              ),
            ),
          )
        else if (controller.voiceState == AssistantVoiceState.transcribing ||
            controller.voiceState == AssistantVoiceState.starting)
          Material(
            color: Theme.of(context).colorScheme.secondaryContainer,
            child: const Padding(
              padding: EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Row(
                children: [
                  SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                  SizedBox(width: 8),
                  Expanded(child: Text('Распознаю речь…')),
                ],
              ),
            ),
          )
        else if (controller.voiceState == AssistantVoiceState.thinking)
          Material(
            color: Theme.of(context).colorScheme.secondaryContainer,
            child: const Padding(
              padding: EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Row(
                children: [
                  SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                  SizedBox(width: 8),
                  Expanded(child: Text('Секретарь думает…')),
                ],
              ),
            ),
          )
        else if (controller.voiceState == AssistantVoiceState.speaking)
          Material(
            color: Theme.of(context).colorScheme.tertiaryContainer,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Row(
                children: [
                  const Icon(Icons.volume_up_outlined, size: 18),
                  const SizedBox(width: 8),
                  const Expanded(child: Text('Секретарь говорит…')),
                  TextButton(
                    key: const Key('assistant_stop_speaking'),
                    onPressed: controller.stopSpeaking,
                    child: const Text('Стоп'),
                  ),
                ],
              ),
            ),
          ),
        if (controller.hasOlderMessages)
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton(
              key: const Key('assistant_load_older_messages'),
              onPressed: controller.loadingOlderMessages
                  ? null
                  : controller.loadOlderMessages,
              child: Text(
                controller.loadingOlderMessages ? 'Загрузка…' : 'Ранее',
              ),
            ),
          ),
        Expanded(
          child: SelectionArea(
            child: ListView.builder(
              key: const Key('assistant_message_list'),
              controller: _scrollController,
              padding: const EdgeInsets.all(16),
              itemCount: controller.messages.length,
              itemBuilder: (context, index) {
                final message = controller.messages[index];
                final isUser = message.role == 'user';
                final actionPlan = message.actionPlan;
                return Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: isUser
                        ? CrossAxisAlignment.end
                        : CrossAxisAlignment.start,
                    children: [
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: isUser
                              ? Theme.of(context).colorScheme.primaryContainer
                              : Theme.of(
                                  context,
                                ).colorScheme.surfaceContainerHighest,
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: isUser
                            ? Text(message.content)
                            : AssistantMessageBody(
                                content: message.content,
                                openableObjectIds: {
                                  for (final ref in message.references)
                                    ref.objectId,
                                },
                                onOpenObject: (objectId) => openObjectDetail(
                                  context,
                                  objectId: objectId,
                                  apiClient: widget.apiClient,
                                  authController: widget.authController,
                                  captureController: widget.captureController,
                                  assistantController: widget.controller,
                                  onAskSecretary: (object) {
                                    widget.controller.setObjectContext(object);
                                  },
                                  bookmarkController: widget.bookmarkController,
                                ),
                              ),
                      ),
                      if (!isUser)
                        Align(
                          alignment: Alignment.centerLeft,
                          child: IconButton(
                            key: Key('assistant_copy_$index'),
                            tooltip: 'Скопировать ответ',
                            visualDensity: VisualDensity.compact,
                            icon: const Icon(Icons.copy_outlined, size: 18),
                            onPressed: () async {
                              await Clipboard.setData(
                                ClipboardData(text: message.content),
                              );
                              if (!context.mounted) {
                                return;
                              }
                              ScaffoldMessenger.of(context).showSnackBar(
                                const SnackBar(
                                  content: Text('Ответ скопирован'),
                                ),
                              );
                            },
                          ),
                        ),
                      if (!isUser && actionPlan != null)
                        _ActionPlanCard(
                          actionPlan: actionPlan,
                          messageIndex: index,
                          controller: controller,
                          operationState: controller.actionPlanOperationState,
                        ),
                      if (!isUser && message.references.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(top: 8),
                          child: Wrap(
                            spacing: 8,
                            runSpacing: 8,
                            children: message.references
                                .map(
                                  (ref) => AssistantReferenceChip(
                                    reference: ref,
                                    onPressed: () => _openReference(ref),
                                  ),
                                )
                                .toList(),
                          ),
                        ),
                      if (!isUser && message.affectedObjects.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(top: 8),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'Затронутые объекты:',
                                style: Theme.of(context).textTheme.labelLarge,
                              ),
                              ...message.affectedObjects.map(
                                (affected) => ActionChip(
                                  label: Text(
                                    affectedObjectDisplayLabel(affected),
                                  ),
                                  onPressed: () =>
                                      _openAffectedObject(affected),
                                ),
                              ),
                            ],
                          ),
                        ),
                    ],
                  ),
                );
              },
            ),
          ),
        ),
        if (controller.sendState == AssistantSendState.error &&
            controller.errorMessage != null)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Row(
              children: [
                Expanded(child: Text(controller.errorMessage!)),
                TextButton(onPressed: _send, child: const Text('Повторить')),
              ],
            ),
          ),
        if (controller.voiceState == AssistantVoiceState.error &&
            controller.voiceErrorMessage != null)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Row(
              children: [
                Expanded(child: Text(controller.voiceErrorMessage!)),
                TextButton(
                  onPressed: controller.canStartVoiceRecording
                      ? _onVoicePressed
                      : null,
                  child: const Text('Повторить'),
                ),
              ],
            ),
          ),
        Padding(
          padding: EdgeInsets.fromLTRB(
            16,
            8,
            16,
            16 + MediaQuery.paddingOf(context).bottom,
          ),
          child: LayoutBuilder(
            builder: (context, constraints) {
              final compact = MediaQuery.sizeOf(context).width < 600;
              return Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Expanded(
                    child: Focus(
                      onKeyEvent: _handleInputKeyEvent,
                      child: TextField(
                        key: const Key('assistant_input'),
                        controller: _inputController,
                        minLines: 1,
                        maxLines: compact ? 3 : 4,
                        decoration: const InputDecoration(
                          hintText: 'Спросить секретаря…',
                          border: OutlineInputBorder(),
                          isDense: true,
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 4),
                  IconButton(
                    key: const Key('assistant_attach_file_button'),
                    visualDensity: VisualDensity.compact,
                    tooltip: 'Добавить файл',
                    onPressed: inputDisabled
                        ? null
                        : () => _intakeActions.pickAndRegisterFile(context),
                    icon: const Icon(Icons.attach_file),
                  ),
                  IconButton(
                    key: const Key('assistant_voice_button'),
                    visualDensity: VisualDensity.compact,
                    tooltip:
                        controller.voiceState == AssistantVoiceState.recording
                        ? 'Остановить запись'
                        : controller.voiceState == AssistantVoiceState.speaking
                        ? 'Прервать и записать'
                        : 'Записать голосовую команду',
                    onPressed:
                        controller.voiceState ==
                                AssistantVoiceState.recording ||
                            controller.canStartVoiceRecording
                        ? _onVoicePressed
                        : null,
                    icon:
                        controller.voiceState ==
                                AssistantVoiceState.transcribing ||
                            controller.voiceState ==
                                AssistantVoiceState.starting ||
                            controller.voiceState ==
                                AssistantVoiceState.thinking
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : Icon(
                            controller.voiceState ==
                                    AssistantVoiceState.recording
                                ? Icons.stop_circle_outlined
                                : Icons.mic_none_outlined,
                          ),
                  ),
                  if (compact)
                    IconButton(
                      key: const Key('assistant_send_button'),
                      visualDensity: VisualDensity.compact,
                      tooltip: _sendTooltip,
                      onPressed: inputDisabled ? null : _send,
                      icon: controller.isSending
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.send),
                    )
                  else
                    Tooltip(
                      message: _sendTooltip,
                      child: FilledButton(
                        key: const Key('assistant_send_button'),
                        onPressed: inputDisabled ? null : _send,
                        child: controller.isSending
                            ? const SizedBox(
                                width: 18,
                                height: 18,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              )
                            : const Text('Отправить'),
                      ),
                    ),
                ],
              );
            },
          ),
        ),
      ],
    );
    final wide = MediaQuery.sizeOf(context).width >= 600;
    final history = _ConversationHistory(controller: controller);
    return Scaffold(
      endDrawer: wide ? null : Drawer(child: history),
      body: wide
          ? Row(
              children: [
                if (!controller.historyCollapsed)
                  SizedBox(
                    key: const Key('assistant_history_panel'),
                    width: 240,
                    child: history,
                  ),
                Expanded(child: _wrapDropTarget(body)),
              ],
            )
          : _wrapDropTarget(body),
    );
  }

  Widget _wrapDropTarget(Widget child) {
    if (kIsWeb || !Platform.isLinux) {
      return child;
    }
    return DropTarget(
      onDragDone: (detail) {
        final paths = detail.files
            .map((file) => file.path)
            .where((path) => path != null)
            .cast<String>()
            .toList();
        _intakeActions.registerDroppedFiles(context, paths);
      },
      child: child,
    );
  }
}

class _ConversationHistory extends StatelessWidget {
  const _ConversationHistory({required this.controller});

  final AssistantController controller;

  @override
  Widget build(BuildContext context) {
    final conversations = controller.conversations;
    return Material(
      color: Theme.of(context).colorScheme.surfaceContainerLow,
      child: ListView(
        children: [
          for (final conversation in conversations)
            ListTile(
              key: Key('assistant_history_item_${conversation.id}'),
              selected: conversation.id == controller.conversationId,
              title: Text(
                conversation.displayTitle,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
              subtitle: Text(
                conversation.lastMessageAt ?? conversation.createdAt,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
              onTap: controller.canSwitchConversation
                  ? () => controller.selectConversation(conversation.id)
                  : null,
            ),
        ],
      ),
    );
  }
}

class _ContextBanner extends StatelessWidget {
  const _ContextBanner({required this.label, required this.onClear});

  final String label;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Theme.of(context).colorScheme.secondaryContainer,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        child: Row(
          children: [
            Expanded(child: Text(label)),
            IconButton(
              tooltip: 'Убрать контекст',
              onPressed: onClear,
              icon: const Icon(Icons.close),
            ),
          ],
        ),
      ),
    );
  }
}

class _ActionPlanCard extends StatelessWidget {
  const _ActionPlanCard({
    required this.actionPlan,
    required this.messageIndex,
    required this.controller,
    required this.operationState,
  });

  final MessageActionPlan actionPlan;
  final int messageIndex;
  final AssistantController controller;
  final AssistantActionPlanOperationState operationState;

  @override
  Widget build(BuildContext context) {
    final cardState = actionPlan.cardState;
    final buttonsDisabled = controller.isActionPlanOperationBusy;
    final compact = MediaQuery.sizeOf(context).width < 600;

    String statusLabel;
    switch (cardState) {
      case ActionPlanCardState.pending:
        statusLabel = 'Требует подтверждения';
      case ActionPlanCardState.completed:
        statusLabel = 'Выполнено';
      case ActionPlanCardState.rejected:
        statusLabel = 'Отклонено';
      case ActionPlanCardState.failed:
        statusLabel = 'Ошибка';
      case ActionPlanCardState.expired:
        statusLabel = 'Истекло';
    }

    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(statusLabel, style: Theme.of(context).textTheme.titleSmall),
              const SizedBox(height: 8),
              ...actionPlan.plan.actions.map(
                (action) => Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: action.toolName == 'send_email'
                      ? _SendEmailPreview(action: action)
                      : action.toolName == 'send_message'
                      ? _SendMessagePreview(action: action)
                      : Text(action.displayLabel, softWrap: true),
                ),
              ),
              if (cardState == ActionPlanCardState.pending &&
                  controller.actionPlanErrorMessage != null)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(
                    controller.actionPlanErrorMessage!,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                ),
              if (cardState == ActionPlanCardState.pending)
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    FilledButton(
                      key: Key('assistant_action_plan_approve_$messageIndex'),
                      onPressed: buttonsDisabled
                          ? null
                          : () => controller.approveActionPlanAt(messageIndex),
                      child: Text(compact ? 'Подтвердить' : 'Подтвердить'),
                    ),
                    OutlinedButton(
                      key: Key('assistant_action_plan_reject_$messageIndex'),
                      onPressed: buttonsDisabled
                          ? null
                          : () => controller.rejectActionPlanAt(messageIndex),
                      child: Text(compact ? 'Отклонить' : 'Отклонить'),
                    ),
                  ],
                ),
              if (cardState == ActionPlanCardState.completed &&
                  actionPlan.resumeFailed)
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const SizedBox(height: 8),
                    const Text('Действие выполнено.'),
                    const Text('Не удалось загрузить ответ секретаря.'),
                    TextButton(
                      key: Key('assistant_action_plan_retry_$messageIndex'),
                      onPressed: buttonsDisabled
                          ? null
                          : () => controller.retryResumeSummary(
                              actionPlan.plan.id,
                            ),
                      child: const Text('Повторить загрузку ответа'),
                    ),
                  ],
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _SendEmailPreview extends StatelessWidget {
  const _SendEmailPreview({required this.action});

  final PendingAction action;

  @override
  Widget build(BuildContext context) {
    final arguments = action.arguments;
    final from = arguments['account_email']?.toString() ?? '';
    final toRaw = arguments['to'];
    final to = toRaw is List
        ? toRaw.map((e) => e.toString()).join(', ')
        : (toRaw?.toString() ?? '');
    final subject = arguments['subject']?.toString() ?? '';
    final body = arguments['body']?.toString() ?? '';
    final textTheme = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Отправить письмо', style: textTheme.titleSmall),
        const SizedBox(height: 4),
        Text('From: $from', softWrap: true),
        Text('To: $to', softWrap: true),
        Text('Subject: $subject', softWrap: true),
        const SizedBox(height: 4),
        Text('Body:', style: textTheme.labelMedium),
        ConstrainedBox(
          constraints: const BoxConstraints(maxHeight: 240),
          child: SingleChildScrollView(child: SelectableText(body)),
        ),
      ],
    );
  }
}

class _SendMessagePreview extends StatelessWidget {
  const _SendMessagePreview({required this.action});

  final PendingAction action;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(action.displayLabel, style: textTheme.titleSmall, softWrap: true),
      ],
    );
  }
}
