import 'package:flutter/material.dart';

import '../assistant/system_assistant_bridge.dart';
import 'account_layout.dart';

class SystemAssistantAccountSection extends StatelessWidget {
  const SystemAssistantAccountSection({
    super.key,
    required this.controller,
    this.platform,
  });

  final SystemAssistantController controller;
  final TargetPlatform? platform;

  @override
  Widget build(BuildContext context) {
    if (!systemAssistantSettingsVisible(platform: platform)) {
      return const SizedBox.shrink();
    }
    return AnimatedBuilder(
      animation: controller,
      builder: (context, _) {
        return AccountSectionCard(
          key: const Key('system_assistant_section'),
          title: 'Голос с экрана блокировки',
          children: [
            const Text(
              'Перед поездкой откройте этот режим. После блокировки телефона '
              'большая кнопка Секретаря останется доступна поверх экрана '
              'блокировки.',
            ),
            const SizedBox(height: 8),
            SwitchListTile(
              key: const Key('system_assistant_lock_screen'),
              contentPadding: EdgeInsets.zero,
              title: const Text(
                'Разрешить голосовой режим на экране блокировки',
              ),
              subtitle: const Text(lockScreenDrivingWritePolicyMessage),
              value: controller.lockScreenVoiceEnabled,
              onChanged: controller.setLockScreenVoiceEnabled,
            ),
            if (controller.lockScreenVoiceEnabled) ...[
              const SizedBox(height: 8),
              FilledButton(
                key: const Key('lock_screen_open_driving_mode'),
                onPressed: controller.openLockScreenLauncher,
                child: const Text('Открыть режим вождения'),
              ),
            ],
          ],
        );
      },
    );
  }
}
