import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../assistant/hardware_voice_binding.dart';
import '../assistant/hardware_voice_bridge.dart';
import '../assistant/hardware_voice_controller.dart';
import 'account_layout.dart';

bool hardwareVoiceSettingsVisible({TargetPlatform? platform}) {
  final resolved = platform ?? defaultTargetPlatform;
  return !kIsWeb && resolved == TargetPlatform.android;
}

class HardwareVoiceAccountSection extends StatelessWidget {
  const HardwareVoiceAccountSection({
    super.key,
    required this.controller,
    this.platform,
  });

  final HardwareVoiceController controller;
  final TargetPlatform? platform;

  @override
  Widget build(BuildContext context) {
    if (!hardwareVoiceSettingsVisible(platform: platform)) {
      return const SizedBox.shrink();
    }
    return AnimatedBuilder(
      animation: controller,
      builder: (context, _) {
        return AccountSectionCard(
          key: const Key('hardware_voice_section'),
          title: 'Голосовой помощник',
          children: [
            const Text(
              'Аппаратная кнопка — это устройство. Настройка хранится только '
              'на этом Android-устройстве и не синхронизируется с сервером.',
            ),
            if (controller.handlerBanner != null) ...[
              const SizedBox(height: 12),
              Text(
                controller.handlerBanner!,
                key: const Key('hardware_voice_bridge_error'),
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ],
            const SizedBox(height: 12),
            Text(
              'Аппаратная кнопка — это устройство',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 4),
            Text(
              controller.statusPrimary,
              key: const Key('hardware_voice_status'),
              style: Theme.of(context).textTheme.titleSmall,
            ),
            if (controller.statusSecondary != null)
              Text(
                controller.statusSecondary!,
                key: const Key('hardware_voice_status_secondary'),
              ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                OutlinedButton(
                  key: const Key('hardware_voice_learn'),
                  onPressed:
                      !controller.isBridgeAvailable ||
                          controller.isLearning ||
                          controller.isTesting
                      ? null
                      : () => _learn(context),
                  child: const Text('Выбрать кнопку…'),
                ),
                OutlinedButton(
                  key: const Key('hardware_voice_volume_up'),
                  onPressed:
                      !controller.isBridgeAvailable ||
                          controller.isLearning ||
                          controller.isTesting
                      ? null
                      : () => controller.useVolumeUpDouble(),
                  child: const Text(
                    'Использовать «Громкость +» (двойное нажатие)',
                  ),
                ),
                OutlinedButton(
                  key: const Key('hardware_voice_test'),
                  onPressed:
                      !controller.isNativeActive ||
                          controller.isLearning ||
                          controller.isTesting
                      ? null
                      : () => _test(context),
                  child: const Text('Проверить'),
                ),
                OutlinedButton(
                  key: const Key('hardware_voice_disable'),
                  onPressed:
                      !controller.hasEnabledBinding ||
                          controller.isLearning ||
                          controller.isTesting
                      ? null
                      : () => controller.disable(),
                  child: const Text('Отключить'),
                ),
              ],
            ),
            if (controller.isNativeActive &&
                !controller.binding!.isVolumeUp) ...[
              const SizedBox(height: 12),
              SegmentedButton<HardwareVoiceGesture>(
                key: const Key('hardware_voice_gesture'),
                segments: const [
                  ButtonSegment(
                    value: HardwareVoiceGesture.single,
                    label: Text('Одно нажатие'),
                  ),
                  ButtonSegment(
                    value: HardwareVoiceGesture.doublePress,
                    label: Text('Двойное нажатие'),
                  ),
                ],
                selected: {controller.binding!.gesture},
                onSelectionChanged:
                    controller.isLearning || controller.isTesting
                    ? null
                    : (selected) {
                        controller.setGesture(selected.first);
                      },
              ),
            ],
          ],
        );
      },
    );
  }

  Future<void> _learn(BuildContext context) async {
    final pending = controller.startLearn();
    if (!context.mounted) {
      return;
    }
    showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) {
        return AnimatedBuilder(
          animation: controller,
          builder: (context, _) {
            return AlertDialog(
              key: const Key('hardware_voice_learn_dialog'),
              title: const Text('Выбор кнопки'),
              content: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Нажмите аппаратную кнопку, которую хотите использовать',
                  ),
                  if (controller.learnHint != null) ...[
                    const SizedBox(height: 12),
                    Text(controller.learnHint!),
                  ],
                ],
              ),
              actions: [
                TextButton(
                  key: const Key('hardware_voice_learn_cancel'),
                  onPressed: () {
                    controller.cancelLearn();
                  },
                  child: const Text('Отмена'),
                ),
              ],
            );
          },
        );
      },
    );
    HardwareVoiceLearnResult result;
    try {
      result = await pending;
    } finally {
      if (context.mounted && Navigator.of(context).canPop()) {
        Navigator.of(context).pop();
      }
    }
    if (!context.mounted) {
      return;
    }
    if (result.status == HardwareVoiceLearnStatus.bridgeError) {
      await showDialog<void>(
        context: context,
        builder: (dialogContext) {
          return AlertDialog(
            content: Text(result.message ?? hardwareVoiceReinstallMessage),
            actions: [
              TextButton(
                onPressed: () => Navigator.of(dialogContext).pop(),
                child: const Text('Понятно'),
              ),
            ],
          );
        },
      );
      return;
    }
    if (result.status == HardwareVoiceLearnStatus.timeout) {
      await showDialog<void>(
        context: context,
        builder: (dialogContext) {
          return AlertDialog(
            content: const Text(
              'Обработчик работает, но Android не передал событие от этой кнопки.\n'
              'Возможно, прошивка устройства перехватывает её.\n'
              'Можно выбрать другую кнопку или использовать двойное нажатие «Громкость +».',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.of(dialogContext).pop(),
                child: const Text('Понятно'),
              ),
            ],
          );
        },
      );
      return;
    }
    if (result.isCaptured && result.keyCode != null) {
      await controller.saveLearned(
        keyCode: result.keyCode!,
        scanCode: result.scanCode,
        androidKeyName: result.androidKeyName,
      );
    }
  }

  Future<void> _test(BuildContext context) async {
    final pending = controller.startTest();
    if (!context.mounted) {
      return;
    }
    showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) {
        return AlertDialog(
          key: const Key('hardware_voice_test_dialog'),
          title: const Text('Проверка кнопки'),
          content: const Text(
            'Нажмите настроенную аппаратную кнопку. Микрофон не включится.',
          ),
          actions: [
            TextButton(
              onPressed: () {
                controller.cancelTest();
              },
              child: const Text('Отмена'),
            ),
          ],
        );
      },
    );
    HardwareVoiceTestResult result;
    try {
      result = await pending;
    } finally {
      if (context.mounted && Navigator.of(context).canPop()) {
        Navigator.of(context).pop();
      }
    }
    if (!context.mounted) {
      return;
    }
    final message = switch (result.status) {
      HardwareVoiceTestStatus.recognized => 'Кнопка распознана',
      HardwareVoiceTestStatus.cancelled => null,
      HardwareVoiceTestStatus.bridgeError =>
        result.message ?? hardwareVoiceReinstallMessage,
      HardwareVoiceTestStatus.timeout =>
        'Кнопка не распознана. Повторите жест или выберите другую кнопку.',
    };
    if (message == null) {
      return;
    }
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }
}
