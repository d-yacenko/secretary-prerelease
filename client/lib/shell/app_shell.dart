import 'package:flutter/material.dart';

import '../account/account_screen.dart';
import '../api/api_models.dart';
import '../assistant/assistant_controller.dart';
import '../assistant/assistant_screen.dart';
import '../assistant/hardware_voice_controller.dart';
import '../assistant/system_assistant_bridge.dart';
import '../assistant/voice_invocation_source.dart';
import '../auth/auth_controller.dart';
import '../capture/capture_controller.dart';
import '../inbox/inbox_screen.dart';
import '../navigation/secretary_navigation.dart';
import '../graph/graph_workspace_controller.dart';
import '../graph/graph_workspace_screen.dart';
import '../search/search_screen.dart';
import '../today/temporal_area.dart';
import '../ui/object_bookmark_controller.dart';
import '../ui/shell_clock.dart';
import 'driving_mode_shortcut.dart';

const double kShellWideBreakpoint = 600;

enum ShellDestination {
  inbox('Входящие'),
  today('Сегодня'),
  graph('Граф'),
  search('Поиск'),
  assistant('Секретарь');

  const ShellDestination(this.label);
  final String label;
}

class AppShell extends StatefulWidget {
  const AppShell({
    super.key,
    required this.authController,
    required this.captureController,
    required this.assistantController,
    required this.graphController,
    this.bookmarkController,
    this.hardwareVoiceController,
    this.systemAssistantController,
    this.platform,
  });

  final AuthController authController;
  final CaptureController captureController;
  final AssistantController assistantController;
  final GraphWorkspaceController graphController;
  final ObjectBookmarkController? bookmarkController;
  final HardwareVoiceController? hardwareVoiceController;
  final SystemAssistantController? systemAssistantController;
  final TargetPlatform? platform;

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  int _selectedIndex = 0;
  late final ObjectBookmarkController _bookmarks;
  var _ownsBookmarks = false;
  var _hardwareListening = false;

  @override
  void initState() {
    super.initState();
    final provided = widget.bookmarkController;
    if (provided != null) {
      _bookmarks = provided;
    } else {
      _ownsBookmarks = true;
      _bookmarks = ObjectBookmarkController(
        apiClient: widget.authController.apiClient,
        authController: widget.authController,
      );
    }
    widget.hardwareVoiceController?.onShellVoiceTrigger =
        _onHardwareVoiceTrigger;
    widget.systemAssistantController?.onAssistInvoke = _onSystemAssistInvoke;
    widget.systemAssistantController?.addListener(_onSystemAssistantChanged);
    widget.assistantController.addListener(_syncHardwareListening);
    _syncHardwareListening();
  }

  @override
  void dispose() {
    if (widget.hardwareVoiceController != null) {
      widget.hardwareVoiceController!.onShellVoiceTrigger = null;
    }
    widget.assistantController.removeListener(_syncHardwareListening);
    if (widget.systemAssistantController != null) {
      widget.systemAssistantController!.onAssistInvoke = null;
      widget.systemAssistantController!.removeListener(
        _onSystemAssistantChanged,
      );
    }
    if (_ownsBookmarks) {
      _bookmarks.dispose();
    }
    super.dispose();
  }

  void _openCapture() {
    openCapture(
      context,
      captureController: widget.captureController,
      authController: widget.authController,
    );
  }

  void _openAccount() {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (context) => AccountScreen(
          apiClient: widget.authController.apiClient,
          authController: widget.authController,
          hardwareVoiceController: widget.hardwareVoiceController,
          systemAssistantController: widget.systemAssistantController,
          voiceOutputPolicyController:
              widget.assistantController.voiceOutputPolicy,
        ),
      ),
    );
  }

  Future<bool> _onHardwareVoiceTrigger() async {
    if (!mounted) {
      return false;
    }
    // Pushed Account / object detail / capture / OAuth: ignore rather than pop.
    final route = ModalRoute.of(context);
    if (route != null && !route.isCurrent) {
      return false;
    }
    if (Navigator.of(context).canPop()) {
      return false;
    }
    if (_selectedIndex != ShellDestination.assistant.index) {
      setState(() => _selectedIndex = ShellDestination.assistant.index);
    }
    await widget.assistantController.handleVoiceTrigger(
      source: VoiceInvocationSource.hardwareButton,
      startCueAlreadyPlayed: true,
    );
    return true;
  }

  void _onSystemAssistantChanged() {
    widget.assistantController.keyguardLocked =
        widget.systemAssistantController?.keyguardLocked ?? false;
    widget.assistantController.lockScreenVoiceEnabled =
        widget.systemAssistantController?.lockScreenVoiceEnabled ?? false;
  }

  void _syncHardwareListening() {
    final listening =
        widget.assistantController.voiceState == AssistantVoiceState.starting ||
        widget.assistantController.voiceState == AssistantVoiceState.recording;
    if (listening == _hardwareListening) {
      return;
    }
    _hardwareListening = listening;
    widget.hardwareVoiceController?.setListening(listening);
  }

  Future<void> _onSystemAssistInvoke() async {
    if (!mounted) {
      return;
    }
    _onSystemAssistantChanged();
    if (_selectedIndex != ShellDestination.assistant.index) {
      setState(() => _selectedIndex = ShellDestination.assistant.index);
    }
    await widget.assistantController.handleVoiceTrigger(
      source: VoiceInvocationSource.systemAssistant,
      startCueAlreadyPlayed: true,
    );
  }

  void _selectDestination(int index) {
    final previous = ShellDestination.values[_selectedIndex];
    final next = ShellDestination.values[index];
    setState(() => _selectedIndex = index);
    if (next == ShellDestination.graph && previous != ShellDestination.graph) {
      widget.graphController.refreshCurrentWorkspace();
    }
  }

  void _showInGraph(String objectId) {
    widget.graphController.reRoot(objectId);
    if (_selectedIndex != ShellDestination.graph.index) {
      setState(() => _selectedIndex = ShellDestination.graph.index);
    }
  }

  void _askSecretaryAbout(SecretaryObject object) {
    widget.assistantController.setObjectContext(object);
    setState(() => _selectedIndex = ShellDestination.assistant.index);
  }

  void _askSecretaryAboutNotification(NotificationOut notification) {
    widget.assistantController.setNotificationContext(notification);
    setState(() => _selectedIndex = ShellDestination.assistant.index);
  }

  Widget _destinationScreen(ShellDestination destination) {
    switch (destination) {
      case ShellDestination.inbox:
        return InboxScreen(
          apiClient: widget.authController.apiClient,
          authController: widget.authController,
          captureController: widget.captureController,
          assistantController: widget.assistantController,
          bookmarkController: _bookmarks,
          onAskSecretary: _askSecretaryAbout,
          onAskSecretaryAboutNotification: _askSecretaryAboutNotification,
          onShowInGraph: _showInGraph,
        );
      case ShellDestination.today:
        return TemporalArea(
          apiClient: widget.authController.apiClient,
          authController: widget.authController,
          captureController: widget.captureController,
          assistantController: widget.assistantController,
          bookmarkController: _bookmarks,
          onAskSecretary: _askSecretaryAbout,
          onShowInGraph: _showInGraph,
        );
      case ShellDestination.search:
        return SearchScreen(
          apiClient: widget.authController.apiClient,
          authController: widget.authController,
          captureController: widget.captureController,
          assistantController: widget.assistantController,
          bookmarkController: _bookmarks,
          onAskSecretary: _askSecretaryAbout,
          onShowInGraph: _showInGraph,
        );
      case ShellDestination.assistant:
        return AssistantScreen(
          controller: widget.assistantController,
          apiClient: widget.authController.apiClient,
          authController: widget.authController,
          captureController: widget.captureController,
          bookmarkController: _bookmarks,
        );
      case ShellDestination.graph:
        return GraphWorkspaceScreen(
          controller: widget.graphController,
          apiClient: widget.authController.apiClient,
          authController: widget.authController,
          captureController: widget.captureController,
          assistantController: widget.assistantController,
          bookmarkController: _bookmarks,
          onAskSecretary: _askSecretaryAbout,
        );
    }
  }

  @override
  Widget build(BuildContext context) {
    final destination = ShellDestination.values[_selectedIndex];
    final isWide = MediaQuery.sizeOf(context).width >= kShellWideBreakpoint;
    final showRailClock = isWide && MediaQuery.sizeOf(context).height >= 520;

    final captureAction = isWide
        ? Padding(
            padding: const EdgeInsets.fromLTRB(8, 8, 8, 4),
            child: FilledButton.icon(
              key: const Key('shell_add_button'),
              onPressed: _openCapture,
              icon: const Icon(Icons.add),
              label: const Text('Задача'),
            ),
          )
        : null;

    final accountAction = IconButton(
      key: const Key('shell_account_button'),
      icon: const Icon(Icons.account_circle),
      tooltip: 'Аккаунт',
      onPressed: _openAccount,
    );
    final systemAssistant = widget.systemAssistantController;
    final drivingShortcut =
        systemAssistant != null &&
            drivingModeShortcutVisible(
              controller: systemAssistant,
              platform: widget.platform,
            )
        ? DrivingModeShortcutButton(controller: systemAssistant)
        : null;

    if (isWide) {
      return Scaffold(
        body: Row(
          children: [
            NavigationRail(
              selectedIndex: _selectedIndex,
              onDestinationSelected: _selectDestination,
              labelType: NavigationRailLabelType.all,
              groupAlignment: -1.0,
              leadingAtTop: true,
              trailingAtBottom: true,
              leading: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  captureAction!,
                  if (showRailClock) const ShellClock(key: Key('shell_clock')),
                ],
              ),
              trailing: drivingShortcut == null
                  ? accountAction
                  : Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [drivingShortcut, accountAction],
                    ),
              destinations: ShellDestination.values
                  .map(
                    (d) => NavigationRailDestination(
                      icon: Icon(_iconFor(d)),
                      label: Text(d.label),
                    ),
                  )
                  .toList(),
            ),
            const VerticalDivider(width: 1),
            Expanded(child: _destinationScreen(destination)),
          ],
        ),
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: Text(destination.label),
        actions: [
          if (!isWide &&
              (destination == ShellDestination.assistant ||
                  destination == ShellDestination.graph))
            IconButton(
              icon: const Icon(Icons.add),
              tooltip: 'Задача',
              onPressed: _openCapture,
            ),
          if (drivingShortcut != null) drivingShortcut,
          accountAction,
        ],
      ),
      body: _destinationScreen(destination),
      floatingActionButton:
          isWide ||
              destination == ShellDestination.assistant ||
              destination == ShellDestination.graph
          ? null
          : FloatingActionButton.extended(
              onPressed: _openCapture,
              icon: const Icon(Icons.add),
              label: const Text('Задача'),
            ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _selectedIndex,
        onDestinationSelected: _selectDestination,
        destinations: ShellDestination.values
            .map(
              (d) => NavigationDestination(
                icon: Icon(_iconFor(d)),
                label: d.label,
              ),
            )
            .toList(),
      ),
    );
  }

  IconData _iconFor(ShellDestination destination) {
    switch (destination) {
      case ShellDestination.inbox:
        return Icons.inbox_outlined;
      case ShellDestination.today:
        return Icons.today_outlined;
      case ShellDestination.graph:
        return Icons.hub_outlined;
      case ShellDestination.search:
        return Icons.search;
      case ShellDestination.assistant:
        return Icons.smart_toy_outlined;
    }
  }
}
