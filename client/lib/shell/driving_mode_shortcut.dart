import 'package:flutter/material.dart';

import '../assistant/system_assistant_bridge.dart';

const String drivingModeShortcutTooltip = 'Режим вождения';
const String drivingModeEnableConfirmMessage =
    'Разрешить голосовой режим на экране блокировки?';
const String drivingModeEnableCancelLabel = 'Отмена';
const String drivingModeEnableConfirmLabel = 'Включить и открыть';

const Key drivingModeShortcutButtonKey = Key('shell_driving_mode_button');
const Key drivingModeEnableDialogKey = Key('driving_mode_enable_dialog');
const Key drivingModeEnableCancelKey = Key('driving_mode_enable_cancel');
const Key drivingModeEnableConfirmKey = Key('driving_mode_enable_confirm');

bool drivingModeShortcutVisible({
  required SystemAssistantController? controller,
  TargetPlatform? platform,
}) {
  return controller != null &&
      systemAssistantSettingsVisible(platform: platform);
}

class DrivingModeShortcutButton extends StatelessWidget {
  const DrivingModeShortcutButton({super.key, required this.controller});

  final SystemAssistantController controller;

  Future<void> _onPressed(BuildContext context) async {
    if (controller.lockScreenVoiceEnabled) {
      await controller.openLockScreenLauncher();
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) {
        return AlertDialog(
          key: drivingModeEnableDialogKey,
          content: const Text(drivingModeEnableConfirmMessage),
          actions: [
            TextButton(
              key: drivingModeEnableCancelKey,
              onPressed: () => Navigator.of(dialogContext).pop(false),
              child: const Text(drivingModeEnableCancelLabel),
            ),
            FilledButton(
              key: drivingModeEnableConfirmKey,
              onPressed: () => Navigator.of(dialogContext).pop(true),
              child: const Text(drivingModeEnableConfirmLabel),
            ),
          ],
        );
      },
    );
    if (confirmed != true) {
      return;
    }
    await controller.setLockScreenVoiceEnabled(true);
    await controller.openLockScreenLauncher();
  }

  @override
  Widget build(BuildContext context) {
    return IconButton(
      key: drivingModeShortcutButtonKey,
      icon: const Icon(Icons.directions_car),
      tooltip: drivingModeShortcutTooltip,
      onPressed: () => _onPressed(context),
    );
  }
}
