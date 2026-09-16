import 'package:flutter/material.dart';

import '../api/api_error.dart';
import '../api/api_models.dart';
import '../api/secretary_api_client.dart';
import '../assistant/assistant_controller.dart';
import '../auth/auth_controller.dart';
import '../capture/capture_controller.dart';
import '../capture/capture_screen.dart';
import '../inbox/notification_labels.dart';
import '../objects/object_detail_screen.dart';
import '../ui/object_bookmark_controller.dart';

typedef AskSecretaryHandler = void Function(SecretaryObject object);
typedef ShowInGraphHandler = void Function(String objectId);

class ObjectDetailNavigationResult {
  const ObjectDetailNavigationResult({required this.deletedObjectId});

  final String deletedObjectId;
}

Future<ObjectDetailNavigationResult?> openObjectDetail(
  BuildContext context, {
  required String objectId,
  required SecretaryApiClient apiClient,
  required AuthController authController,
  required CaptureController captureController,
  AssistantController? assistantController,
  AskSecretaryHandler? onAskSecretary,
  ShowInGraphHandler? onShowInGraph,
  ValueChanged<SecretaryObject>? onTaskUpdated,
  ObjectBookmarkController? bookmarkController,
}) {
  return Navigator.of(context).push<ObjectDetailNavigationResult>(
    MaterialPageRoute<ObjectDetailNavigationResult>(
      builder: (context) => ObjectDetailScreen(
        objectId: objectId,
        apiClient: apiClient,
        authController: authController,
        captureController: captureController,
        assistantController: assistantController,
        bookmarkController: bookmarkController,
        onAskSecretary: onAskSecretary,
        onShowInGraph: onShowInGraph,
        onTaskUpdated: onTaskUpdated,
      ),
    ),
  );
}

Future<void> openNotificationContext(
  BuildContext context, {
  required NotificationOut notification,
  required SecretaryApiClient apiClient,
  required AuthController authController,
  required CaptureController captureController,
  AssistantController? assistantController,
  AskSecretaryHandler? onAskSecretary,
  void Function(NotificationOut notification)? onAskSecretaryAboutNotification,
  ShowInGraphHandler? onShowInGraph,
  ObjectBookmarkController? bookmarkController,
}) async {
  try {
    if (notification.status == 'new') {
      await apiClient.markNotificationRead(notification.id);
    }
  } on AuthenticationException {
    authController.handleAuthenticationFailure();
    return;
  } catch (_) {
    // best effort read
  }

  final objectId = notification.sourceObjectId ??
      notification.relatedObjectId ??
      notification.resultObjectId;

  if (objectId != null) {
    if (!context.mounted) {
      return;
    }
    await openObjectDetail(
      context,
      objectId: objectId,
      apiClient: apiClient,
      authController: authController,
      captureController: captureController,
      assistantController: assistantController,
      onAskSecretary: onAskSecretary,
      onShowInGraph: onShowInGraph,
      bookmarkController: bookmarkController,
    );
    return;
  }

  if (!context.mounted) {
    return;
  }

  await showDialog<void>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(notification.title),
      content: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Приоритет: ${notificationPriorityLabel(notification.priority)}'),
            if (notification.proposalType != null)
              Text(
                'Предложение: ${notificationProposalTypeLabel(notification.proposalType!)}',
              ),
            if (notification.proposalDescription != null)
              Text(notification.proposalDescription!),
            if (notification.proposedAction != null)
              Text(
                'Действие: ${notificationProposedActionLabel(notification.proposedAction!)}',
              ),
          ],
        ),
      ),
      actions: [
        if (onAskSecretaryAboutNotification != null)
          TextButton(
            onPressed: () {
              Navigator.of(context).pop();
              onAskSecretaryAboutNotification(notification);
            },
            child: const Text('Спросить секретаря'),
          ),
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Закрыть'),
        ),
      ],
    ),
  );
}

Future<void> openCapture(
  BuildContext context, {
  required CaptureController captureController,
  AuthController? authController,
}) async {
  await Navigator.of(context).push<void>(
    MaterialPageRoute<void>(
      builder: (context) => CaptureScreen(
        controller: captureController,
        authController: authController,
      ),
    ),
  );
}
