import '../api/api_models.dart';
import 'voice_invocation_source.dart';

/// Canonical policy: may this exact pending plan be voice-approved while locked?
///
/// Voice is not biometric identity. The security boundary is an ephemeral
/// Driving Mode session armed only from the authenticated unlocked app.
bool mayVoiceApproveLockedPendingPlan({
  required bool lockScreenSession,
  required bool keyguardLocked,
  required bool drivingSessionAuthorized,
  required String? activeDrivingSessionId,
  required String? boundPlanId,
  required String? boundSessionId,
  required VoiceInvocationSource? boundSource,
  required String? pendingPlanId,
  required int pendingPlanCount,
  required List<PendingAction> actions,
}) {
  if (!lockScreenSession || !keyguardLocked) {
    return false;
  }
  if (!drivingSessionAuthorized) {
    return false;
  }
  final activeId = activeDrivingSessionId;
  if (activeId == null || activeId.isEmpty) {
    return false;
  }
  if (pendingPlanCount != 1) {
    return false;
  }
  if (pendingPlanId == null ||
      boundPlanId == null ||
      pendingPlanId != boundPlanId) {
    return false;
  }
  if (boundSessionId == null || boundSessionId != activeId) {
    return false;
  }
  if (boundSource != VoiceInvocationSource.lockScreenLauncher) {
    return false;
  }
  return PendingAction.planIsVoiceApprovable(actions);
}
