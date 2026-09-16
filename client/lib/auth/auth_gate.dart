import 'package:flutter/material.dart';

import '../assistant/assistant_controller.dart';
import '../assistant/hardware_voice_controller.dart';
import '../assistant/system_assistant_bridge.dart';
import '../capture/capture_controller.dart';
import '../graph/graph_workspace_controller.dart';
import '../shell/app_shell.dart';
import '../ui/object_bookmark_controller.dart';
import 'auth_controller.dart';
import 'auth_setup_screen.dart';

/// Root home widget: swaps authenticated shell vs auth setup in-place.
class AuthGate extends StatelessWidget {
  const AuthGate({
    super.key,
    required this.authController,
    required this.captureController,
    required this.assistantController,
    required this.graphController,
    required this.bookmarkController,
    this.hardwareVoiceController,
    this.systemAssistantController,
  });

  final AuthController authController;
  final CaptureController captureController;
  final AssistantController assistantController;
  final GraphWorkspaceController graphController;
  final ObjectBookmarkController bookmarkController;
  final HardwareVoiceController? hardwareVoiceController;
  final SystemAssistantController? systemAssistantController;

  @override
  Widget build(BuildContext context) {
    switch (authController.status) {
      case AuthStatus.initial:
      case AuthStatus.loading:
        return const Scaffold(body: Center(child: CircularProgressIndicator()));
      case AuthStatus.authenticated:
        return AppShell(
          authController: authController,
          captureController: captureController,
          assistantController: assistantController,
          graphController: graphController,
          bookmarkController: bookmarkController,
          hardwareVoiceController: hardwareVoiceController,
          systemAssistantController: systemAssistantController,
        );
      case AuthStatus.needsAuth:
      case AuthStatus.transientError:
        return AuthSetupScreen(controller: authController);
    }
  }
}
