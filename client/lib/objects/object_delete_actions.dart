import 'package:flutter/material.dart';

import '../api/api_error.dart';
import '../api/api_models.dart';
import '../api/secretary_api_client.dart';
import '../auth/auth_controller.dart';

const _directSwipeDeleteProviders = {
  'gmail',
  'yandex_mail',
  'google_calendar',
  'yandex_calendar',
  'mattermost',
  'google_drive',
  'yandex_disk',
  'local_device',
};

/// Direct full-swipe confirmation is allowed only when a provider-backed
/// source is guaranteed to survive outside Secretary.
///
/// Unknown provider/kind combinations fail closed (modal remains).
/// `task` and `note` always require the dialog, even if a provider is set.
bool objectSupportsDeliberateSwipeDeleteWithoutDialog(SecretaryObject object) {
  if (object.kind == 'task' || object.kind == 'note') {
    return false;
  }
  final provider = object.provider?.toLowerCase();
  if (provider != null && _directSwipeDeleteProviders.contains(provider)) {
    return true;
  }
  if (object.kind == 'web_page') {
    return true;
  }
  return false;
}

String deleteConfirmationMessage(SecretaryObject object) {
  final provider = object.provider?.toLowerCase();
  if (object.kind == 'task' || object.kind == 'note') {
    return 'Удалить из Секретаря?';
  }
  if (provider == 'gmail' || provider == 'yandex_mail') {
    return 'Удалить из Секретаря?\nПисьмо останется в почтовом ящике.';
  }
  if (provider == 'google_calendar' || provider == 'yandex_calendar') {
    return 'Удалить из Секретаря?\nСобытие останется в календаре.';
  }
  if (provider == 'mattermost') {
    return 'Удалить из Секретаря?\nСообщение останется в Mattermost.';
  }
  if (provider == 'google_drive') {
    if (object.kind == 'folder') {
      return 'Удалить из Секретаря?\nПапка останется в Google Drive.';
    }
    return 'Удалить из Секретаря?\nФайл останется в Google Drive.';
  }
  if (provider == 'yandex_disk') {
    if (object.kind == 'folder') {
      return 'Удалить из Секретаря?\nПапка останется на Яндекс.Диске.';
    }
    return 'Удалить из Секретаря?\nФайл останется на Яндекс.Диске.';
  }
  if (provider == 'local_device') {
    if (object.kind == 'folder') {
      return 'Удалить из Секретаря?\nИсходная папка останется на устройстве.';
    }
    return 'Удалить из Секретаря?\nИсходный файл останется на устройстве.';
  }
  if (object.kind == 'web_page' || object.kind == 'file') {
    return 'Удалить из Секретаря?\nИсходный ресурс останется доступен по ссылке.';
  }
  return 'Удалить из Секретаря?';
}

Future<bool> deleteObjectFromSecretary(
  BuildContext context, {
  required SecretaryObject object,
  required SecretaryApiClient apiClient,
  required AuthController authController,
}) async {
  try {
    await apiClient.deleteObject(object.id);
    return true;
  } on AuthenticationException {
    authController.handleAuthenticationFailure();
    return false;
  } on ApiException catch (error) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(error.message)),
      );
    }
    return false;
  }
}

Future<bool> confirmAndDeleteObject(
  BuildContext context, {
  required SecretaryObject object,
  required SecretaryApiClient apiClient,
  required AuthController authController,
}) async {
  final confirmed = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      title: const Text('Удалить из Секретаря?'),
      content: Text(deleteConfirmationMessage(object)),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context, false),
          child: const Text('Отмена'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(context, true),
          child: const Text('Удалить'),
        ),
      ],
    ),
  );
  if (confirmed != true || !context.mounted) {
    return false;
  }
  return deleteObjectFromSecretary(
    context,
    object: object,
    apiClient: apiClient,
    authController: authController,
  );
}
