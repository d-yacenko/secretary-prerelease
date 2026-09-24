import 'dart:async';
import 'dart:io';
import 'dart:math';

import 'package:flutter/foundation.dart';

import '../api/api_error.dart';
import '../api/api_models.dart';
import '../api/secretary_api_client.dart';
import '../assistant/voice_recorder.dart';
import '../assistant/voice_temp_files.dart';
import '../auth/auth_controller.dart';
import '../voice/voice_transcription_controller.dart';
import 'audioplayers_speech_player.dart';
import 'fake_speech_player.dart';
import 'speech_playback_controller.dart';
import 'speech_player.dart';
import 'voice_capture_diagnostics.dart';
import 'driving_locked_voice_approval.dart';
import 'driving_silence_monitor.dart';
import 'voice_confirmation.dart';
import 'voice_invocation_source.dart';
import 'voice_local_feedback.dart';
import 'voice_output_policy.dart';
import 'voice_output_policy_controller.dart';
import 'voice_turn_timing.dart';

const int maxAssistantHistoryMessages = 12;
const unresolvedPendingPlanDetail = 'unresolved_pending_action_plan';
const conversationSwitchWaitMessage = 'Дождитесь завершения подтверждения.';
const unresolvedPendingPlanMessage =
    'Сначала подтвердите или отклоните ожидающее действие.';

String newAssistantTurnId() {
  final random = Random.secure();
  final bytes = List<int>.generate(16, (_) => random.nextInt(256));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  final hex = bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
  return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-'
      '${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
}

const voiceUnsupportedPlanSpeech = 'Это действие нужно подтвердить на экране.';
const voiceRejectedSpeech = 'Не отправляю.';
const voiceExecutionFailedSpeech = 'Не удалось выполнить отправку.';
const voiceExpiredSpeech = 'Срок подтверждения истёк.';
const voiceResumeFailedSpeech =
    'Действие выполнено. Не удалось загрузить итоговый ответ секретаря.';
const voicePlanAmbiguousSpeech =
    'Нельзя подтвердить голосом: найдено несколько ожидающих действий.';
const voiceUnlockRequiredSpeech =
    'Нужно разблокировать устройство, чтобы подтвердить отправку.';

enum AssistantSendState { idle, sending, error }

enum AssistantVoiceState {
  idle,
  starting,
  recording,
  transcribing,
  thinking,
  speaking,
  error,
}

enum AssistantActionPlanOperationState {
  idle,
  approving,
  rejecting,
  resuming,
  error,
}

enum ActionPlanCardState { pending, completed, rejected, failed, expired }

class MessageActionPlan {
  MessageActionPlan({
    required this.plan,
    this.cardState = ActionPlanCardState.pending,
    this.resumeFailed = false,
  });

  final PendingActionPlan plan;
  ActionPlanCardState cardState;
  bool resumeFailed;
}

class AssistantChatMessage {
  AssistantChatMessage({
    required this.role,
    required this.content,
    this.storedId,
    this.references = const [],
    this.affectedObjects = const [],
    this.actionPlan,
  });

  final String role;
  final String content;
  final String? storedId;
  final List<AssistantReference> references;
  final List<AssistantAffectedObject> affectedObjects;
  final MessageActionPlan? actionPlan;
}

class AssistantController extends ChangeNotifier {
  AssistantController({
    required SecretaryApiClient apiClient,
    required AuthController authController,
    VoiceRecorder? voiceRecorder,
    VoiceTempFiles? voiceTempFiles,
    VoiceTranscriptionController? voiceController,
    SpeechPlayer? speechPlayer,
    SpeechPlaybackController? speechPlayback,
    VoiceLocalFeedback? voiceFeedback,
    VoiceOutputPolicyController? voiceOutputPolicy,
    this.lockScreenSession = false,
    String Function()? newTurnId,
  }) : _apiClient = apiClient,
       _newTurnId = newTurnId ?? newAssistantTurnId,
       _authController = authController,
       _voiceTempFiles =
           voiceTempFiles ??
           (Platform.environment['FLUTTER_TEST'] == 'true'
               ? VoiceTempFiles(
                   directory: Directory.systemTemp.createTempSync(
                     'secretary_voice_test',
                   ),
                 )
               : VoiceTempFiles()) {
    _voice =
        voiceController ??
        VoiceTranscriptionController(
          apiClient: apiClient,
          authController: authController,
          voiceRecorder: voiceRecorder,
          voiceTempFiles: _voiceTempFiles,
        );
    _speech =
        speechPlayback ??
        SpeechPlaybackController(
          apiClient: apiClient,
          authController: authController,
          player:
              speechPlayer ??
              (Platform.environment['FLUTTER_TEST'] == 'true'
                  ? FakeSpeechPlayer()
                  : AudioplayersSpeechPlayer()),
          tempFiles: _voiceTempFiles,
        );
    _feedback =
        voiceFeedback ??
        (Platform.environment['FLUTTER_TEST'] == 'true'
            ? const NoopVoiceLocalFeedback()
            : AssetVoiceLocalFeedback());
    _voiceOutputPolicy =
        voiceOutputPolicy ??
        VoiceOutputPolicyController(authController: authController);
    _ownsVoiceOutputPolicy = voiceOutputPolicy == null;
    _voice.bindTranscriptConsumer(_handleVoiceTranscript);
    _voice.addListener(_onVoiceChanged);
    _voiceOutputPolicy.addListener(_onVoiceChanged);
    if (_ownsVoiceOutputPolicy) {
      _voiceOutputPolicy.attach();
    }
  }

  final SecretaryApiClient _apiClient;
  final AuthController _authController;
  final String Function() _newTurnId;
  late final VoiceTranscriptionController _voice;
  final VoiceTempFiles _voiceTempFiles;
  late final SpeechPlaybackController _speech;
  late final VoiceLocalFeedback _feedback;
  late final VoiceOutputPolicyController _voiceOutputPolicy;
  late final bool _ownsVoiceOutputPolicy;
  final bool lockScreenSession;

  bool keyguardLocked = false;
  bool lockScreenVoiceEnabled = false;
  bool drivingSessionAuthorized = false;
  String? drivingSessionId;

  VoiceOutputPolicyController get voiceOutputPolicy => _voiceOutputPolicy;

  bool get autoSpeechAllowed => _autoSpeechAllowed;

  VoiceInvocationSource get turnSource => _turnSource;

  bool get voiceInputActive => _voiceInputActive;

  bool get blocksExternalWrite => lockScreenSession && keyguardLocked;

  void setDrivingSession({required bool authorized, String? sessionId}) {
    final nextId = authorized && sessionId != null && sessionId.isNotEmpty
        ? sessionId
        : null;
    final nextAuthorized = nextId != null;
    if (drivingSessionAuthorized == nextAuthorized &&
        drivingSessionId == nextId) {
      return;
    }
    drivingSessionAuthorized = nextAuthorized;
    drivingSessionId = nextId;
    _clearVoiceApprovalBinding();
    _voiceApprovalArmed = false;
    notifyListeners();
  }

  void clearDrivingAuthorization() {
    setDrivingSession(authorized: false, sessionId: null);
  }

  void _clearVoiceApprovalBinding() {
    _boundVoiceApprovalPlanId = null;
    _boundVoiceApprovalSessionId = null;
    _boundVoiceApprovalSource = null;
  }

  void _bindVoiceApprovalForPlan(PendingActionPlan? plan) {
    if (plan == null) {
      _clearVoiceApprovalBinding();
      return;
    }
    _boundVoiceApprovalPlanId = plan.id;
    _boundVoiceApprovalSessionId = drivingSessionAuthorized
        ? drivingSessionId
        : null;
    _boundVoiceApprovalSource = _turnSource;
  }

  int _pendingPlanCount() {
    var count = 0;
    for (final message in _messages) {
      final plan = message.actionPlan;
      if (plan != null && plan.cardState == ActionPlanCardState.pending) {
        count += 1;
      }
    }
    return count;
  }

  bool _mayVoiceApproveLockedPendingPlanAt(int messageIndex) {
    if (messageIndex < 0 || messageIndex >= _messages.length) {
      return false;
    }
    final actionPlan = _messages[messageIndex].actionPlan;
    if (actionPlan == null ||
        actionPlan.cardState != ActionPlanCardState.pending) {
      return false;
    }
    return mayVoiceApproveLockedPendingPlan(
      lockScreenSession: lockScreenSession,
      keyguardLocked: keyguardLocked,
      drivingSessionAuthorized: drivingSessionAuthorized,
      activeDrivingSessionId: drivingSessionId,
      boundPlanId: _boundVoiceApprovalPlanId,
      boundSessionId: _boundVoiceApprovalSessionId,
      boundSource: _boundVoiceApprovalSource,
      pendingPlanId: actionPlan.plan.id,
      pendingPlanCount: _pendingPlanCount(),
      actions: actionPlan.plan.actions,
    );
  }

  final List<AssistantChatMessage> _messages = [];
  AssistantContextRef? _objectContext;
  AssistantContextRef? _notificationContext;
  AssistantSendState sendState = AssistantSendState.idle;
  AssistantActionPlanOperationState actionPlanOperationState =
      AssistantActionPlanOperationState.idle;
  String? errorMessage;
  String? actionPlanErrorMessage;
  String? _pendingRetryMessage;
  String? _retryTurnId;
  String? _retryTurnText;
  int _sessionEpoch = 0;
  bool _legacyConversationServer = false;
  bool _persistentBootstrapReady = false;
  Future<void>? _restoreInFlight;
  bool persistentMode = false;
  bool hasOlderMessages = false;
  bool loadingOlderMessages = false;
  String? conversationId;
  List<AssistantConversation> conversations = const [];
  bool historyCollapsed = false;
  String? switchBlockedMessage;
  bool _approveInFlight = false;
  bool _voiceInputActive = false;
  bool _autoSpeechAllowed = false;
  VoiceInvocationSource _turnSource = VoiceInvocationSource.typed;
  bool _voiceApprovalArmed = false;
  bool _planNarrationInProgress = false;
  bool _speakingOverlay = false;
  String? _speechErrorMessage;
  bool _assistantTurnVoiceError = false;
  bool _confirmationInFlight = false;
  InboxReviewReceipt? _pendingInboxReviewReceipt;
  String? _boundVoiceApprovalPlanId;
  String? _boundVoiceApprovalSessionId;
  VoiceInvocationSource? _boundVoiceApprovalSource;
  DrivingSilenceMonitor? _drivingSilence;
  Future<void>? _stopVoiceInFlight;

  bool get voiceApprovalArmed => _voiceApprovalArmed;

  AssistantVoiceState get voiceState {
    if (_speechErrorMessage != null || _assistantTurnVoiceError) {
      return AssistantVoiceState.error;
    }
    if (_speakingOverlay || _speech.isSpeaking) {
      return AssistantVoiceState.speaking;
    }
    if (_voiceInputActive &&
        (sendState == AssistantSendState.sending ||
            isActionPlanOperationBusy)) {
      return AssistantVoiceState.thinking;
    }
    switch (_voice.voiceState) {
      case VoiceState.idle:
        return AssistantVoiceState.idle;
      case VoiceState.starting:
        return AssistantVoiceState.starting;
      case VoiceState.recording:
        return AssistantVoiceState.recording;
      case VoiceState.transcribing:
        return AssistantVoiceState.transcribing;
      case VoiceState.error:
        return AssistantVoiceState.error;
    }
  }

  String? get voiceErrorMessage =>
      _speechErrorMessage ??
      _voice.voiceErrorMessage ??
      (_assistantTurnVoiceError ? errorMessage : null);

  List<AssistantChatMessage> get messages => List.unmodifiable(_messages);

  bool get canSwitchConversation =>
      actionPlanOperationState == AssistantActionPlanOperationState.idle &&
      sendState != AssistantSendState.sending;

  String? get conversationSwitchNotice {
    if (!canSwitchConversation) {
      return conversationSwitchWaitMessage;
    }
    return switchBlockedMessage;
  }
  AssistantContextRef? get objectContext => _objectContext;
  AssistantContextRef? get notificationContext => _notificationContext;
  String? get pendingRetryMessage => _pendingRetryMessage;
  bool get isSending => sendState == AssistantSendState.sending;
  bool get isVoiceBusy => _voice.isVoiceBusy;
  bool get isSpeaking => _speakingOverlay || _speech.isSpeaking;
  bool get hasPendingActionPlan => _messages.any(
    (message) =>
        message.actionPlan != null &&
        message.actionPlan!.cardState == ActionPlanCardState.pending,
  );
  bool get isActionPlanOperationBusy =>
      actionPlanOperationState == AssistantActionPlanOperationState.approving ||
      actionPlanOperationState == AssistantActionPlanOperationState.rejecting ||
      actionPlanOperationState == AssistantActionPlanOperationState.resuming;
  bool get canSubmitOrdinaryAssistantMessage =>
      !isSending &&
      !isVoiceBusy &&
      !hasPendingActionPlan &&
      !isActionPlanOperationBusy &&
      !isSpeaking;
  bool get isInputBlocked => !canSubmitOrdinaryAssistantMessage;
  bool get canStartVoiceRecording {
    if (isActionPlanOperationBusy || _confirmationInFlight) {
      return false;
    }
    if (isSpeaking) {
      return true;
    }
    if (_voice.isVoiceBusy) {
      return false;
    }
    if (isSending) {
      return false;
    }
    if (hasPendingActionPlan) {
      return true;
    }
    return true;
  }

  void _onVoiceChanged() {
    if (_voice.voiceState != VoiceState.recording) {
      _cancelDrivingSilenceMonitor();
    }
    notifyListeners();
  }

  void setObjectContext(SecretaryObject object) {
    _objectContext = AssistantContextRef(
      id: object.id,
      title: object.title,
      kind: object.kind,
    );
    _notificationContext = null;
    notifyListeners();
  }

  void setNotificationContext(NotificationOut notification) {
    _notificationContext = AssistantContextRef(
      id: notification.id,
      title: notification.title,
      kind: 'notification',
    );
    _objectContext = null;
    notifyListeners();
  }

  void clearObjectContext() {
    _objectContext = null;
    notifyListeners();
  }

  void clearNotificationContext() {
    _notificationContext = null;
    notifyListeners();
  }

  Future<void> restorePersistentConversation() {
    if (_persistentBootstrapReady || _legacyConversationServer) {
      return Future<void>.value();
    }
    final inFlight = _restoreInFlight;
    if (inFlight != null) {
      return inFlight;
    }
    final run = _restorePersistentConversationBody();
    _restoreInFlight = run;
    return run.whenComplete(() {
      if (identical(_restoreInFlight, run)) {
        _restoreInFlight = null;
      }
    });
  }

  bool _isCurrentSession(int epoch) => epoch == _sessionEpoch;

  Future<void> _restorePersistentConversationBody() async {
    final epoch = _sessionEpoch;
    try {
      final current = await _apiClient.getCurrentAssistantConversation();
      if (!_isCurrentSession(epoch)) {
        return;
      }
      final conversation =
          current ?? await _apiClient.createAssistantConversation();
      if (!_isCurrentSession(epoch)) {
        return;
      }
      if (conversation == null) {
        _legacyConversationServer = true;
        persistentMode = false;
        notifyListeners();
        return;
      }
      persistentMode = true;
      conversationId = conversation.id;
      await _refreshConversationList(epoch);
      if (!_isCurrentSession(epoch)) {
        return;
      }
      await _replaceMessagesFromServer(conversation.id, epoch);
      if (!_isCurrentSession(epoch)) {
        return;
      }
      _persistentBootstrapReady = true;
      errorMessage = null;
    } on ApiException catch (error) {
      if (!_isCurrentSession(epoch)) {
        return;
      }
      persistentMode = false;
      _persistentBootstrapReady = false;
      errorMessage = error.message;
    }
    if (!_isCurrentSession(epoch)) {
      return;
    }
    notifyListeners();
  }

  Future<void> loadOlderMessages() async {
    final id = conversationId;
    final oldest = _messages.isEmpty ? null : _messages.first.storedId;
    if (!hasOlderMessages ||
        loadingOlderMessages ||
        id == null ||
        oldest == null) {
      return;
    }
    loadingOlderMessages = true;
    notifyListeners();
    final epoch = _sessionEpoch;
    try {
      final page = await _apiClient.listAssistantMessages(id, beforeId: oldest);
      if (!_isCurrentSession(epoch)) {
        return;
      }
      final known = <String>{
        for (final message in _messages)
          if (message.storedId != null) message.storedId!,
      };
      final older = <AssistantChatMessage>[];
      for (final message in page.messages) {
        final chat = _chatFromStored(message);
        if (chat.storedId != null && known.contains(chat.storedId)) {
          continue;
        }
        older.add(chat);
      }
      _messages.insertAll(0, older);
      hasOlderMessages = page.hasMore;
    } on ApiException catch (error) {
      if (!_isCurrentSession(epoch)) {
        return;
      }
      errorMessage = error.message;
    }
    if (!_isCurrentSession(epoch)) {
      return;
    }
    loadingOlderMessages = false;
    notifyListeners();
  }

  Future<void> startNewConversation() async {
    if (!canSwitchConversation) {
      notifyListeners();
      return;
    }
    final epoch = _sessionEpoch;
    try {
      final created = await _apiClient.createAssistantConversation();
      if (!_isCurrentSession(epoch) || created == null) {
        return;
      }
      _clearTransientTurnState();
      persistentMode = true;
      conversationId = created.id;
      _messages.clear();
      hasOlderMessages = false;
      switchBlockedMessage = null;
      await _refreshConversationList(epoch);
    } on ApiException catch (error) {
      if (!_isCurrentSession(epoch)) {
        return;
      }
      switchBlockedMessage = _switchFailureMessage(error);
    }
    if (!_isCurrentSession(epoch)) {
      return;
    }
    notifyListeners();
  }

  Future<void> selectConversation(String id) async {
    if (!canSwitchConversation) {
      notifyListeners();
      return;
    }
    final epoch = _sessionEpoch;
    try {
      final selected = await _apiClient.selectAssistantConversation(id);
      if (!_isCurrentSession(epoch)) {
        return;
      }
      _clearTransientTurnState();
      persistentMode = true;
      conversationId = selected.id;
      switchBlockedMessage = null;
      await _replaceMessagesFromServer(selected.id, epoch);
      if (!_isCurrentSession(epoch)) {
        return;
      }
      await _refreshConversationList(epoch);
    } on ApiException catch (error) {
      if (!_isCurrentSession(epoch)) {
        return;
      }
      switchBlockedMessage = _switchFailureMessage(error);
    }
    if (!_isCurrentSession(epoch)) {
      return;
    }
    notifyListeners();
  }

  void toggleHistoryPanel() {
    historyCollapsed = !historyCollapsed;
    notifyListeners();
  }

  Future<void> sendMessage(
    String text, {
    VoiceInvocationSource source = VoiceInvocationSource.typed,
    bool preserveTurn = false,
  }) async {
    final trimmed = text.trim();
    if (trimmed.isEmpty || !canSubmitOrdinaryAssistantMessage) {
      return;
    }

    if (!preserveTurn) {
      _beginTurn(source);
    }
    _voiceApprovalArmed = false;
    _planNarrationInProgress = false;
    sendState = AssistantSendState.sending;
    errorMessage = null;
    notifyListeners();

    final epoch = _sessionEpoch;
    await restorePersistentConversation();
    if (!_isCurrentSession(epoch)) {
      return;
    }
    if (!_persistentBootstrapReady && !_legacyConversationServer) {
      sendState = AssistantSendState.error;
      errorMessage ??= 'Не удалось открыть диалог.';
      notifyListeners();
      return;
    }
    final turnId = persistentMode ? _turnIdFor(trimmed) : null;
    final history = persistentMode
        ? const <AssistantHistoryMessage>[]
        : _boundedHistory();
    try {
      final started = Stopwatch()..start();
      final response = await _apiClient.sendAssistantMessage(
        AssistantMessageRequest(
          message: trimmed,
          history: history,
          contextObjectId: _objectContext?.id,
          contextNotificationId: _notificationContext?.id,
          conversationId: persistentMode ? conversationId : null,
          clientTurnId: turnId,
        ),
      );
      VoiceTurnTiming.interval('assistant_rtt_ms', started.elapsedMilliseconds);
      if (!_isCurrentSession(epoch)) {
        return;
      }
      _messages.add(
        AssistantChatMessage(
          role: 'user',
          content: trimmed,
          storedId: response.userMessageId,
        ),
      );
      _messages.add(
        AssistantChatMessage(
          role: 'assistant',
          content: response.answer,
          storedId: response.assistantMessageId,
          references: response.references,
          affectedObjects: response.affectedObjects,
          actionPlan: response.pendingActionPlan == null
              ? null
              : MessageActionPlan(plan: response.pendingActionPlan!),
        ),
      );
      _bindVoiceApprovalForPlan(response.pendingActionPlan);
      _pendingRetryMessage = null;
      _retryTurnId = null;
      _retryTurnText = null;
      _assistantTurnVoiceError = false;
      sendState = AssistantSendState.idle;
      if (persistentMode) {
        try {
          await _refreshConversationList(epoch);
        } on ApiException {
          // The turn is already stored. History refresh can retry later.
        }
      }
      if (!_isCurrentSession(epoch)) {
        return;
      }
      notifyListeners();
      _pendingInboxReviewReceipt =
          _autoSpeechAllowed &&
              response.pendingActionPlan == null &&
              response.inboxReviewReceipt != null
          ? response.inboxReviewReceipt
          : null;
      VoiceCaptureDiagnostics.event(
        response.inboxReviewReceipt == null
            ? 'assistant_response_review_receipt_missing'
            : 'assistant_response_review_receipt_received',
        {
          'auto_speech_allowed': _autoSpeechAllowed,
          'pending_action_plan': response.pendingActionPlan != null,
        },
      );
      if (_pendingInboxReviewReceipt != null) {
        VoiceCaptureDiagnostics.event('inbox_review_receipt_stored', {
          'total_count': _pendingInboxReviewReceipt!.totalCount,
        });
      }
      if (_autoSpeechAllowed) {
        await _speakLatestAssistantResult();
      }
    } on AuthenticationException catch (e) {
      if (!_isCurrentSession(epoch)) {
        return;
      }
      _pendingRetryMessage = trimmed;
      sendState = AssistantSendState.error;
      errorMessage = e.message;
      _authController.handleAuthenticationFailure();
      await _noteAssistantTurnFailure();
    } on NetworkException catch (e) {
      if (!_isCurrentSession(epoch)) {
        return;
      }
      _pendingRetryMessage = trimmed;
      sendState = AssistantSendState.error;
      errorMessage = e.message;
      await _noteAssistantTurnFailure();
    } on ApiException catch (e) {
      if (!_isCurrentSession(epoch)) {
        return;
      }
      _pendingRetryMessage = trimmed;
      sendState = AssistantSendState.error;
      errorMessage = localOpenAiDailyBudgetMessage(e) ?? e.message;
      await _noteAssistantTurnFailure();
    }
  }

  Future<void> _noteAssistantTurnFailure() async {
    if (_turnSource.isVoiceInput) {
      _assistantTurnVoiceError = true;
      notifyListeners();
      await _feedback.playError();
      return;
    }
    notifyListeners();
  }

  Future<void> approveActionPlanAt(
    int messageIndex, {
    bool fromVoiceApproval = false,
  }) async {
    if (_approveInFlight ||
        actionPlanOperationState != AssistantActionPlanOperationState.idle) {
      return;
    }
    if (messageIndex < 0 || messageIndex >= _messages.length) {
      return;
    }
    final message = _messages[messageIndex];
    final actionPlan = message.actionPlan;
    if (actionPlan == null ||
        actionPlan.cardState != ActionPlanCardState.pending) {
      return;
    }
    if (blocksExternalWrite) {
      if (!fromVoiceApproval ||
          !_mayVoiceApproveLockedPendingPlanAt(messageIndex)) {
        if (fromVoiceApproval && _autoSpeechAllowed) {
          await _speakDeterministic(voiceUnlockRequiredSpeech);
        }
        return;
      }
    }

    _approveInFlight = true;
    final epoch = _sessionEpoch;
    actionPlanOperationState = AssistantActionPlanOperationState.approving;
    actionPlanErrorMessage = null;
    notifyListeners();

    try {
      final response = await _apiClient.approveActionPlan(actionPlan.plan.id);
      if (!_isCurrentSession(epoch)) {
        return;
      }
      if (response.status == 'failed') {
        actionPlan.cardState = ActionPlanCardState.failed;
        actionPlanOperationState = AssistantActionPlanOperationState.idle;
        _clearVoiceApprovalBinding();
        _voiceApprovalArmed = false;
        notifyListeners();
        if (_autoSpeechAllowed) {
          await _speakDeterministic(voiceExecutionFailedSpeech);
        }
        return;
      }
      if (response.status == 'expired') {
        actionPlan.cardState = ActionPlanCardState.expired;
        actionPlanOperationState = AssistantActionPlanOperationState.idle;
        _clearVoiceApprovalBinding();
        _voiceApprovalArmed = false;
        notifyListeners();
        if (_autoSpeechAllowed) {
          await _speakDeterministic(voiceExpiredSpeech);
        }
        return;
      }
      if (response.status == 'executed') {
        actionPlan.cardState = ActionPlanCardState.completed;
        actionPlan.resumeFailed = false;
        _clearVoiceApprovalBinding();
        _voiceApprovalArmed = false;
        notifyListeners();
        await _resumeExecutedPlan(actionPlan);
        return;
      }
      actionPlanOperationState = AssistantActionPlanOperationState.idle;
      notifyListeners();
    } on AuthenticationException catch (e) {
      if (!_isCurrentSession(epoch)) {
        return;
      }
      actionPlanOperationState = AssistantActionPlanOperationState.idle;
      actionPlanErrorMessage = e.message;
      _authController.handleAuthenticationFailure();
      notifyListeners();
    } on NetworkException catch (e) {
      if (!_isCurrentSession(epoch)) {
        return;
      }
      actionPlanOperationState = AssistantActionPlanOperationState.idle;
      actionPlanErrorMessage = e.message;
      notifyListeners();
    } on ApiException catch (e) {
      if (!_isCurrentSession(epoch)) {
        return;
      }
      actionPlanOperationState = AssistantActionPlanOperationState.idle;
      actionPlanErrorMessage = localOpenAiDailyBudgetMessage(e) ?? e.message;
      notifyListeners();
    } finally {
      if (_isCurrentSession(epoch)) {
        _approveInFlight = false;
      }
    }
  }

  Future<void> rejectActionPlanAt(int messageIndex) async {
    if (actionPlanOperationState != AssistantActionPlanOperationState.idle) {
      return;
    }
    if (messageIndex < 0 || messageIndex >= _messages.length) {
      return;
    }
    final message = _messages[messageIndex];
    final actionPlan = message.actionPlan;
    if (actionPlan == null ||
        actionPlan.cardState != ActionPlanCardState.pending) {
      return;
    }

    actionPlanOperationState = AssistantActionPlanOperationState.rejecting;
    actionPlanErrorMessage = null;
    notifyListeners();
    final epoch = _sessionEpoch;

    try {
      final response = await _apiClient.rejectActionPlan(actionPlan.plan.id);
      if (!_isCurrentSession(epoch)) {
        return;
      }
      if (response.status == 'expired') {
        actionPlan.cardState = ActionPlanCardState.expired;
      } else {
        actionPlan.cardState = ActionPlanCardState.rejected;
      }
      _clearVoiceApprovalBinding();
      _voiceApprovalArmed = false;
      actionPlanOperationState = AssistantActionPlanOperationState.idle;
      notifyListeners();
      if (_autoSpeechAllowed) {
        await _speakDeterministic(
          response.status == 'expired'
              ? voiceExpiredSpeech
              : voiceRejectedSpeech,
        );
      }
    } on AuthenticationException catch (e) {
      if (!_isCurrentSession(epoch)) {
        return;
      }
      actionPlanOperationState = AssistantActionPlanOperationState.idle;
      actionPlanErrorMessage = e.message;
      _authController.handleAuthenticationFailure();
      notifyListeners();
    } on NetworkException catch (e) {
      if (!_isCurrentSession(epoch)) {
        return;
      }
      actionPlanOperationState = AssistantActionPlanOperationState.idle;
      actionPlanErrorMessage = e.message;
      notifyListeners();
    } on ApiException catch (e) {
      if (!_isCurrentSession(epoch)) {
        return;
      }
      actionPlanOperationState = AssistantActionPlanOperationState.idle;
      actionPlanErrorMessage = localOpenAiDailyBudgetMessage(e) ?? e.message;
      notifyListeners();
    }
  }

  Future<void> retryResumeSummary(String planId) async {
    if (actionPlanOperationState != AssistantActionPlanOperationState.idle) {
      return;
    }
    MessageActionPlan? actionPlan;
    for (final message in _messages) {
      final candidate = message.actionPlan;
      if (candidate != null &&
          candidate.plan.id == planId &&
          candidate.cardState == ActionPlanCardState.completed) {
        actionPlan = candidate;
        break;
      }
    }
    if (actionPlan == null) {
      return;
    }
    await _resumeExecutedPlan(actionPlan);
  }

  Future<void> _resumeExecutedPlan(MessageActionPlan actionPlan) async {
    actionPlanOperationState = AssistantActionPlanOperationState.resuming;
    actionPlanErrorMessage = null;
    notifyListeners();
    final epoch = _sessionEpoch;

    try {
      final response = await _apiClient.resumeActionPlan(actionPlan.plan.id);
      if (!_isCurrentSession(epoch)) {
        return;
      }
      _messages.add(
        AssistantChatMessage(
          role: 'assistant',
          content: response.answer,
          affectedObjects: response.affectedObjects,
        ),
      );
      actionPlan.resumeFailed = false;
      actionPlanOperationState = AssistantActionPlanOperationState.idle;
      notifyListeners();
      if (_autoSpeechAllowed) {
        await _speakDeterministic(response.answer);
      }
    } on AuthenticationException catch (e) {
      if (!_isCurrentSession(epoch)) {
        return;
      }
      actionPlan.resumeFailed = true;
      actionPlanOperationState = AssistantActionPlanOperationState.idle;
      actionPlanErrorMessage = e.message;
      _authController.handleAuthenticationFailure();
      notifyListeners();
      if (_autoSpeechAllowed) {
        await _speakDeterministic(voiceResumeFailedSpeech);
      }
    } on NetworkException catch (e) {
      if (!_isCurrentSession(epoch)) {
        return;
      }
      actionPlan.resumeFailed = true;
      actionPlanOperationState = AssistantActionPlanOperationState.idle;
      actionPlanErrorMessage = e.message;
      notifyListeners();
      if (_autoSpeechAllowed) {
        await _speakDeterministic(voiceResumeFailedSpeech);
      }
    } on ApiException catch (e) {
      if (!_isCurrentSession(epoch)) {
        return;
      }
      actionPlan.resumeFailed = true;
      actionPlanOperationState = AssistantActionPlanOperationState.idle;
      actionPlanErrorMessage = localOpenAiDailyBudgetMessage(e) ?? e.message;
      notifyListeners();
      if (_autoSpeechAllowed) {
        await _speakDeterministic(voiceResumeFailedSpeech);
      }
    }
  }

  /// Canonical Voice Assistant A trigger for on-screen mic and Android hardware.
  ///
  /// Idle/error: start recording. Recording: stop and transcribe. Speaking:
  /// stop TTS and start a new recording. Starting/transcribing/thinking: ignore.
  /// Pending Action Plan uses the existing confirmation utterance path.
  ///
  /// Audible cues never overlap an active microphone recording. Hands-free
  /// ready tone completes before the recorder starts. Stop cue plays after
  /// the recorder has stopped.
  Future<void> handleVoiceTrigger({
    VoiceInvocationSource source = VoiceInvocationSource.screenMic,
    bool startCueAlreadyPlayed = false,
    bool stopCueAlreadyPlayed = false,
  }) async {
    VoiceCaptureDiagnostics.trigger(source: source, state: voiceState.name);
    switch (voiceState) {
      case AssistantVoiceState.recording:
        await stopVoiceRecordingAndTranscribe(
          stopCueAlreadyPlayed: stopCueAlreadyPlayed,
        );
        return;
      case AssistantVoiceState.starting:
      case AssistantVoiceState.transcribing:
      case AssistantVoiceState.thinking:
        return;
      case AssistantVoiceState.speaking:
      case AssistantVoiceState.idle:
      case AssistantVoiceState.error:
        if (lockScreenSession && keyguardLocked && !lockScreenVoiceEnabled) {
          return;
        }
        if (source == VoiceInvocationSource.lockScreenLauncher &&
            !lockScreenVoiceEnabled) {
          return;
        }
        VoiceTurnTiming.startTurn(
          startCueAlreadyPlayed ? 'native_or_assist' : 'ui',
        );
        VoiceCaptureDiagnostics.startTurn(
          turnId: '${DateTime.now().microsecondsSinceEpoch}-${source.name}',
          source: source,
        );
        final interruptedPlanNarration =
            voiceState == AssistantVoiceState.speaking &&
            _planNarrationInProgress;
        await stopSpeaking();
        if (interruptedPlanNarration) {
          _voiceApprovalArmed = false;
        }
        if (!startCueAlreadyPlayed) {
          await _feedback.playAck();
        }
        VoiceTurnTiming.mark('ack');
        VoiceCaptureDiagnostics.event('ack_completed');
        await startVoiceRecording(source: source);
        if (voiceState != AssistantVoiceState.recording) {
          return;
        }
        VoiceTurnTiming.mark('recording_ready');
        VoiceCaptureDiagnostics.event('recording_ready');
        return;
    }
  }

  Future<void> startVoiceRecording({
    VoiceInvocationSource source = VoiceInvocationSource.screenMic,
  }) async {
    if (voiceState == AssistantVoiceState.recording) {
      return;
    }
    if (!canStartVoiceRecording) {
      return;
    }
    if (isSpeaking) {
      final interruptedPlanNarration = _planNarrationInProgress;
      await stopSpeaking();
      if (interruptedPlanNarration) {
        _voiceApprovalArmed = false;
      }
    }
    if (voiceState == AssistantVoiceState.error) {
      clearVoiceError();
    }
    if (!hasPendingActionPlan) {
      _beginTurn(source);
    }
    await _voice.startRecording(
      beforeMicrophoneStart: () async {
        await _feedback.releasePlayback();
        if (!source.isHandsFree) {
          return;
        }
        VoiceTurnTiming.mark('ready_cue_requested');
        VoiceCaptureDiagnostics.event('ready_cue_requested');
        await _feedback.playReady();
        await _feedback.releasePlayback();
        VoiceTurnTiming.mark('ready_cue_completed');
        VoiceCaptureDiagnostics.event('ready_cue_completed');
      },
    );
    if (_voice.voiceState == VoiceState.recording &&
        source == VoiceInvocationSource.lockScreenLauncher) {
      _startDrivingSilenceMonitor();
    }
  }

  void _startDrivingSilenceMonitor() {
    _cancelDrivingSilenceMonitor();
    final monitor = DrivingSilenceMonitor(
      amplitudeSamples: _voice.amplitudeSamples,
      onAutoStop: () => stopVoiceRecordingAndTranscribe(),
    );
    _drivingSilence = monitor;
    monitor.start();
  }

  void _cancelDrivingSilenceMonitor() {
    final monitor = _drivingSilence;
    if (monitor == null) {
      return;
    }
    _drivingSilence = null;
    monitor.cancel();
  }

  Future<void> stopVoiceRecordingAndTranscribe({
    bool stopCueAlreadyPlayed = false,
  }) async {
    _cancelDrivingSilenceMonitor();
    final inFlight = _stopVoiceInFlight;
    if (inFlight != null) {
      return inFlight;
    }
    final stop = _stopVoiceRecordingAndTranscribeBody(
      stopCueAlreadyPlayed: stopCueAlreadyPlayed,
    );
    _stopVoiceInFlight = stop;
    try {
      await stop;
    } finally {
      if (identical(_stopVoiceInFlight, stop)) {
        _stopVoiceInFlight = null;
      }
    }
  }

  Future<void> _stopVoiceRecordingAndTranscribeBody({
    required bool stopCueAlreadyPlayed,
  }) async {
    VoiceTurnTiming.mark('stop');
    VoiceCaptureDiagnostics.event('stop_trigger');
    await _voice.stopAndTranscribe(
      afterRecorderStopped: () async {
        VoiceTurnTiming.mark('stop_feedback');
        if (!stopCueAlreadyPlayed) {
          unawaited(_feedback.playStop());
        }
      },
    );
  }

  Future<void> stopSpeaking() async {
    if (_speakingOverlay || _speech.isSpeaking) {
      VoiceCaptureDiagnostics.event('playback_interrupted');
    }
    _discardPendingInboxReviewCompletion();
    _planNarrationInProgress = false;
    _speakingOverlay = false;
    await _speech.stop();
    notifyListeners();
  }

  Future<void> _handleVoiceTranscript(String transcript) async {
    if (hasPendingActionPlan) {
      await _handleVoiceConfirmation(transcript);
      return;
    }
    if (!canSubmitOrdinaryAssistantMessage) {
      _pendingRetryMessage = transcript;
      notifyListeners();
      return;
    }
    await sendMessage(transcript, preserveTurn: true);
  }

  Future<void> _handleVoiceConfirmation(String transcript) async {
    if (_confirmationInFlight ||
        isActionPlanOperationBusy ||
        _approveInFlight) {
      return;
    }
    _confirmationInFlight = true;
    try {
      final pendingIndex = _uniquePendingPlanIndex();
      if (pendingIndex == null) {
        if (_autoSpeechAllowed) {
          await _speakDeterministic(voicePlanAmbiguousSpeech);
        }
        return;
      }
      final decision = parseVoiceConfirmation(transcript);
      if (decision == VoiceConfirmation.reject) {
        await rejectActionPlanAt(pendingIndex);
        return;
      }
      if (decision == VoiceConfirmation.approve) {
        if (blocksExternalWrite) {
          if (!_mayVoiceApproveLockedPendingPlanAt(pendingIndex)) {
            if (_autoSpeechAllowed) {
              await _speakDeterministic(voiceUnlockRequiredSpeech);
            }
            return;
          }
          if (!_voiceApprovalArmed) {
            if (_autoSpeechAllowed) {
              await _speakDeterministic(voiceApprovalUnarmedSpeech);
            }
            return;
          }
          await approveActionPlanAt(pendingIndex, fromVoiceApproval: true);
          return;
        }
        final message = _messages[pendingIndex];
        final actions =
            message.actionPlan?.plan.actions ?? const <PendingAction>[];
        final voiceApprovable = PendingAction.planIsVoiceApprovable(actions);
        if (!_voiceApprovalArmed || !voiceApprovable) {
          if (_autoSpeechAllowed) {
            await _speakDeterministic(
              voiceApprovable
                  ? voiceApprovalUnarmedSpeech
                  : voiceUnsupportedPlanSpeech,
            );
          }
          return;
        }
        await approveActionPlanAt(pendingIndex, fromVoiceApproval: true);
        return;
      }
      if (_autoSpeechAllowed) {
        await _speakDeterministic(voiceConfirmationRetrySpeech);
      }
    } finally {
      _confirmationInFlight = false;
    }
  }

  int? _uniquePendingPlanIndex() {
    final indexes = <int>[];
    for (var i = 0; i < _messages.length; i++) {
      final plan = _messages[i].actionPlan;
      if (plan != null && plan.cardState == ActionPlanCardState.pending) {
        indexes.add(i);
      }
    }
    if (indexes.length == 1) {
      return indexes.first;
    }
    return null;
  }

  Future<void> _speakLatestAssistantResult() async {
    final pendingIndex = _uniquePendingPlanIndex();
    if (pendingIndex != null) {
      _discardPendingInboxReviewCompletion();
      if (blocksExternalWrite) {
        if (_mayVoiceApproveLockedPendingPlanAt(pendingIndex)) {
          final preview = PendingAction.planVoicePreview(
            _messages[pendingIndex].actionPlan!.plan.actions,
          );
          if (preview != null) {
            _voiceApprovalArmed = false;
            _planNarrationInProgress = true;
            await _speakDeterministic(preview, isPlanNarration: true);
            return;
          }
        }
        _voiceApprovalArmed = false;
        await _speakDeterministic(voiceUnlockRequiredSpeech);
        return;
      }
      final plan = _messages[pendingIndex].actionPlan!.plan;
      final preview = PendingAction.planVoicePreview(plan.actions);
      if (preview != null) {
        _voiceApprovalArmed = false;
        _planNarrationInProgress = true;
        await _speakDeterministic(preview, isPlanNarration: true);
        return;
      }
      _voiceApprovalArmed = false;
      final answer = _messages.last.content;
      final spoken = answer.trim().isEmpty
          ? voiceUnsupportedPlanSpeech
          : '$answer\n$voiceUnsupportedPlanSpeech';
      await _speakDeterministic(spoken);
      return;
    }
    await _speakDeterministic(_messages.last.content);
  }

  Future<void> _speakDeterministic(
    String text, {
    bool isPlanNarration = false,
  }) async {
    _speechErrorMessage = null;
    _speakingOverlay = true;
    notifyListeners();
    var playbackFinished = false;
    await _speech.speak(
      text,
      onPlaybackStarted: () {
        VoiceCaptureDiagnostics.event('playback_started');
      },
      onFinished: () {
        playbackFinished = true;
        VoiceCaptureDiagnostics.event('playback_completed');
        _speakingOverlay = false;
        if (isPlanNarration && _planNarrationInProgress) {
          _voiceApprovalArmed = true;
        }
        _planNarrationInProgress = false;
        notifyListeners();
      },
      onError: (message) {
        VoiceCaptureDiagnostics.event('playback_error');
        _discardPendingInboxReviewCompletion();
        _speakingOverlay = false;
        if (isPlanNarration) {
          _voiceApprovalArmed = false;
        }
        _planNarrationInProgress = false;
        _speechErrorMessage = message;
        notifyListeners();
      },
    );
    if (playbackFinished && !isPlanNarration) {
      await _completePendingInboxReviewAfterPlayback();
    }
  }

  void _discardPendingInboxReviewCompletion() {
    _pendingInboxReviewReceipt = null;
  }

  Future<void> _completePendingInboxReviewAfterPlayback() async {
    final receipt = _pendingInboxReviewReceipt;
    _pendingInboxReviewReceipt = null;
    if (receipt == null) {
      return;
    }
    VoiceCaptureDiagnostics.event('inbox_review_completion_started', {
      'total_count': receipt.totalCount,
    });
    try {
      final result = await _apiClient.completeInboxReviewMarker(receipt);
      VoiceCaptureDiagnostics.event('inbox_review_completion_result', {
        'status': result.status,
      });
    } on AuthenticationException {
      VoiceCaptureDiagnostics.event('inbox_review_completion_failed', {
        'failure': 'authentication',
      });
    } on NetworkException {
      VoiceCaptureDiagnostics.event('inbox_review_completion_failed', {
        'failure': 'network',
      });
    } on ApiException {
      VoiceCaptureDiagnostics.event('inbox_review_completion_failed', {
        'failure': 'api',
      });
    } catch (_) {
      VoiceCaptureDiagnostics.event('inbox_review_completion_failed', {
        'failure': 'unexpected',
      });
      // Fail closed: interrupted/errored/conflict completion must not move the marker.
    }
  }

  Future<void> cancelVoiceRecording() async {
    _cancelDrivingSilenceMonitor();
    await _voice.cancel();
  }

  void clearVoiceError() {
    _speechErrorMessage = null;
    _assistantTurnVoiceError = false;
    _voice.clearError();
    notifyListeners();
  }

  String _turnIdFor(String text) {
    if (_retryTurnText == text && _retryTurnId != null) {
      return _retryTurnId!;
    }
    final id = _newTurnId();
    _retryTurnId = id;
    _retryTurnText = text;
    return id;
  }

  String _switchFailureMessage(ApiException error) {
    if (error.message == unresolvedPendingPlanDetail) {
      return unresolvedPendingPlanMessage;
    }
    return error.message;
  }

  Future<void> _refreshConversationList(int epoch) async {
    final rows = await _apiClient.listAssistantConversations();
    if (!_isCurrentSession(epoch)) {
      return;
    }
    conversations = rows;
  }

  Future<void> _replaceMessagesFromServer(String id, int epoch) async {
    final page = await _apiClient.listAssistantMessages(id);
    if (!_isCurrentSession(epoch)) {
      return;
    }
    _messages
      ..clear()
      ..addAll(page.messages.map(_chatFromStored));
    hasOlderMessages = page.hasMore;
  }

  AssistantChatMessage _chatFromStored(AssistantStoredMessage message) {
    final plan = message.pendingActionPlan;
    return AssistantChatMessage(
      role: message.role,
      content: message.content,
      storedId: message.id,
      references: message.references,
      affectedObjects: message.affectedObjects,
      actionPlan: plan == null
          ? null
          : MessageActionPlan(plan: plan, cardState: _cardStateFor(plan)),
    );
  }

  ActionPlanCardState _cardStateFor(PendingActionPlan plan) {
    final expires = DateTime.tryParse(plan.expiresAt);
    if (plan.status == 'pending' &&
        expires != null &&
        expires.isBefore(DateTime.now().toUtc())) {
      return ActionPlanCardState.expired;
    }
    switch (plan.status) {
      case 'executed':
        return ActionPlanCardState.completed;
      case 'rejected':
        return ActionPlanCardState.rejected;
      case 'failed':
        return ActionPlanCardState.failed;
      case 'expired':
        return ActionPlanCardState.expired;
      default:
        return ActionPlanCardState.pending;
    }
  }

  void _clearTransientTurnState() {
    _cancelDrivingSilenceMonitor();
    _voice.reset();
    _speech.stop();
    _objectContext = null;
    _notificationContext = null;
    sendState = AssistantSendState.idle;
    errorMessage = null;
    actionPlanErrorMessage = null;
    _pendingRetryMessage = null;
    _retryTurnId = null;
    _retryTurnText = null;
    _voiceInputActive = false;
    _autoSpeechAllowed = false;
    _voiceApprovalArmed = false;
    _planNarrationInProgress = false;
    _boundVoiceApprovalPlanId = null;
    _boundVoiceApprovalSessionId = null;
    _boundVoiceApprovalSource = null;
  }

  List<AssistantHistoryMessage> _boundedHistory() {
    final pairs = <AssistantHistoryMessage>[];
    for (final message in _messages) {
      pairs.add(
        AssistantHistoryMessage(role: message.role, content: message.content),
      );
    }
    if (pairs.length > maxAssistantHistoryMessages) {
      return pairs.sublist(pairs.length - maxAssistantHistoryMessages);
    }
    return pairs;
  }

  void _beginTurn(VoiceInvocationSource source) {
    _discardPendingInboxReviewCompletion();
    _assistantTurnVoiceError = false;
    _turnSource = source;
    _voiceInputActive = source.isVoiceInput;
    _autoSpeechAllowed =
        source.isHandsFree &&
        _voiceOutputPolicy.policy.allowsAutoSpeech(source);
    _voiceApprovalArmed = false;
    _planNarrationInProgress = false;
  }

  void resetSession() {
    _sessionEpoch += 1;
    _restoreInFlight = null;
    persistentMode = false;
    conversationId = null;
    conversations = const [];
    hasOlderMessages = false;
    loadingOlderMessages = false;
    _legacyConversationServer = false;
    _persistentBootstrapReady = false;
    switchBlockedMessage = null;
    _cancelDrivingSilenceMonitor();
    _stopVoiceInFlight = null;
    _voice.reset();
    _speech.stop();
    _messages.clear();
    _objectContext = null;
    _notificationContext = null;
    sendState = AssistantSendState.idle;
    actionPlanOperationState = AssistantActionPlanOperationState.idle;
    errorMessage = null;
    actionPlanErrorMessage = null;
    _pendingRetryMessage = null;
    _retryTurnId = null;
    _retryTurnText = null;
    _approveInFlight = false;
    _voiceInputActive = false;
    _autoSpeechAllowed = false;
    _turnSource = VoiceInvocationSource.typed;
    _voiceApprovalArmed = false;
    _planNarrationInProgress = false;
    _speakingOverlay = false;
    _speechErrorMessage = null;
    _assistantTurnVoiceError = false;
    _confirmationInFlight = false;
    _clearVoiceApprovalBinding();
    _discardPendingInboxReviewCompletion();
    notifyListeners();
  }

  @override
  void dispose() {
    _cancelDrivingSilenceMonitor();
    _voiceOutputPolicy.removeListener(_onVoiceChanged);
    if (_ownsVoiceOutputPolicy) {
      _voiceOutputPolicy.dispose();
    }
    _voice.removeListener(_onVoiceChanged);
    _voice.dispose();
    _speech.dispose();
    _feedback.dispose();
    super.dispose();
  }
}
