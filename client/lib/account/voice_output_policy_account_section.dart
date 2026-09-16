import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../assistant/voice_output_policy.dart';
import '../assistant/voice_output_policy_controller.dart';
import 'account_layout.dart';

bool voiceOutputPolicySettingsVisible({TargetPlatform? platform}) {
  final resolved = platform ?? defaultTargetPlatform;
  return resolved == TargetPlatform.android || resolved == TargetPlatform.linux;
}

class VoiceOutputPolicyAccountSection extends StatelessWidget {
  const VoiceOutputPolicyAccountSection({
    super.key,
    required this.controller,
    this.platform,
  });

  final VoiceOutputPolicyController controller;
  final TargetPlatform? platform;

  @override
  Widget build(BuildContext context) {
    if (!voiceOutputPolicySettingsVisible(platform: platform)) {
      return const SizedBox.shrink();
    }
    return AnimatedBuilder(
      animation: controller,
      builder: (context, _) {
        final enabled = controller.policy == VoiceOutputPolicy.handsFreeEnabled;
        return AccountSectionCard(
          key: const Key('voice_output_policy_section'),
          title: 'Автоозвучивание ответов',
          children: [
            SwitchListTile(
              key: const Key('voice_output_policy_hands_free_enabled'),
              contentPadding: EdgeInsets.zero,
              title: const Text('Озвучивать ответы в hands-free режиме'),
              subtitle: const Text(
                'Экранный микрофон используется только для диктовки и не '
                'включает автоозвучивание.',
              ),
              value: enabled,
              onChanged: (value) {
                controller.setPolicy(
                  value
                      ? VoiceOutputPolicy.handsFreeEnabled
                      : VoiceOutputPolicy.never,
                );
              },
            ),
          ],
        );
      },
    );
  }
}
