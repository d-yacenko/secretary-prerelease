import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/assistant/driving_locked_voice_approval.dart';
import 'package:personal_secretary/assistant/voice_invocation_source.dart';

PendingAction emailAction() {
  return PendingAction(
    toolName: 'send_email',
    arguments: {
      'to': ['ivan@example.com'],
      'subject': 'Статус',
      'body': 'Пришлю завтра.',
    },
  );
}

PendingAction messageAction() {
  return PendingAction(
    toolName: 'send_message',
    arguments: {
      'provider': 'telegram',
      'mode': 'reply',
      'body': 'Точное исходящее тело',
      'route': {'chat_display_name': 'Ivan'},
    },
  );
}

PendingAction taskAction() {
  return PendingAction(
    toolName: 'create_task',
    arguments: {'title': 'Разобрать письмо'},
  );
}

PendingAction deleteAction() {
  return PendingAction(
    toolName: 'delete_task',
    arguments: {'title': 'Старая задача'},
  );
}

void main() {
  const session = 'drive-1';

  bool allow({
    bool lockScreenSession = true,
    bool keyguardLocked = true,
    bool drivingSessionAuthorized = true,
    String? activeDrivingSessionId = session,
    String? boundPlanId = 'plan-email',
    String? boundSessionId = session,
    VoiceInvocationSource? boundSource =
        VoiceInvocationSource.lockScreenLauncher,
    String? pendingPlanId = 'plan-email',
    int pendingPlanCount = 1,
    List<PendingAction>? actions,
  }) {
    return mayVoiceApproveLockedPendingPlan(
      lockScreenSession: lockScreenSession,
      keyguardLocked: keyguardLocked,
      drivingSessionAuthorized: drivingSessionAuthorized,
      activeDrivingSessionId: activeDrivingSessionId,
      boundPlanId: boundPlanId,
      boundSessionId: boundSessionId,
      boundSource: boundSource,
      pendingPlanId: pendingPlanId,
      pendingPlanCount: pendingPlanCount,
      actions: actions ?? [emailAction()],
    );
  }

  test('eligible locked driving send_email may be voice-approved', () {
    expect(allow(), isTrue);
    expect(allow(actions: [messageAction()]), isTrue);
  });

  test('missing driving authorization is blocked', () {
    expect(allow(drivingSessionAuthorized: false), isFalse);
    expect(allow(activeDrivingSessionId: null), isFalse);
  });

  test('wrong source or session cannot leak into driving approval', () {
    expect(allow(boundSource: VoiceInvocationSource.screenMic), isFalse);
    expect(allow(boundSource: VoiceInvocationSource.typed), isFalse);
    expect(allow(boundSessionId: 'old-session'), isFalse);
    expect(allow(boundPlanId: 'other-plan'), isFalse);
    expect(allow(pendingPlanCount: 2), isFalse);
  });

  test('unsupported mixed and destructive plans stay locked', () {
    expect(allow(actions: [taskAction()]), isFalse);
    expect(allow(actions: [emailAction(), taskAction()]), isFalse);
    expect(allow(actions: [deleteAction()]), isFalse);
  });

  test('unlocked path is outside this helper', () {
    expect(allow(keyguardLocked: false), isFalse);
    expect(allow(lockScreenSession: false), isFalse);
  });
}
