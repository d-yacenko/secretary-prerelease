import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'auth/auth_controller.dart';
import 'auth/auth_gate.dart';
import 'assistant/assistant_controller.dart';
import 'assistant/hardware_voice_controller.dart';
import 'assistant/system_assistant_bridge.dart';
import 'assistant/voice_output_policy_controller.dart';
import 'capture/capture_controller.dart';
import 'graph/graph_workspace_controller.dart';
import 'navigation/app_route_observer.dart';
import 'ui/object_bookmark_controller.dart';
import 'ui/ui_text_scale.dart';

class PersonalSecretaryApp extends StatefulWidget {
  const PersonalSecretaryApp({
    super.key,
    required this.authController,
    this.textScaleController,
  });

  final AuthController authController;
  final UiTextScaleController? textScaleController;

  @override
  State<PersonalSecretaryApp> createState() => _PersonalSecretaryAppState();
}

class _PersonalSecretaryAppState extends State<PersonalSecretaryApp>
    with WidgetsBindingObserver {
  final _navigatorKey = GlobalKey<NavigatorState>();
  late final AuthSessionNavigator _authSessionNavigator;
  late final CaptureController _captureController;
  late final AssistantController _assistantController;
  late final GraphWorkspaceController _graphController;
  late final ObjectBookmarkController _bookmarkController;
  late final HardwareVoiceController _hardwareVoiceController;
  late final SystemAssistantController _systemAssistantController;
  late final VoiceOutputPolicyController _voiceOutputPolicyController;
  late final UiTextScaleController _textScale;

  @override
  void initState() {
    super.initState();
    _textScale = widget.textScaleController ?? UiTextScaleController();
    _authSessionNavigator = AuthSessionNavigator(_navigatorKey);
    _captureController = CaptureController(
      apiClient: widget.authController.apiClient,
      authController: widget.authController,
    );
    _voiceOutputPolicyController = VoiceOutputPolicyController(
      authController: widget.authController,
    );
    _assistantController = AssistantController(
      apiClient: widget.authController.apiClient,
      authController: widget.authController,
      voiceOutputPolicy: _voiceOutputPolicyController,
    );
    _graphController = GraphWorkspaceController(
      apiClient: widget.authController.apiClient,
      authController: widget.authController,
    );
    _bookmarkController = ObjectBookmarkController(
      apiClient: widget.authController.apiClient,
      authController: widget.authController,
    );
    _hardwareVoiceController = HardwareVoiceController(
      authController: widget.authController,
    );
    _systemAssistantController = SystemAssistantController();
    WidgetsBinding.instance.addObserver(this);
    widget.authController.onSessionTerminated = _onSessionTerminated;
    widget.authController.addListener(_onAuthChanged);
    _textScale.addListener(_onAuthChanged);
    widget.authController.initialize();
    _hardwareVoiceController.attach();
    _voiceOutputPolicyController.attach();
    _systemAssistantController.attach(widget.authController.user?.id);
    if (widget.textScaleController == null) {
      _textScale.load();
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _systemAssistantController.refresh();
    }
  }

  void _onSessionTerminated() {
    _captureController.resetSession();
    _assistantController.resetSession();
    _graphController.resetSession();
    _bookmarkController.resetSession();
    _authSessionNavigator.resetNavigationStack();
  }

  void _onAuthChanged() {
    _systemAssistantController.attach(widget.authController.user?.id);
    setState(() {});
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    widget.authController.onSessionTerminated = null;
    widget.authController.removeListener(_onAuthChanged);
    _textScale.removeListener(_onAuthChanged);
    if (widget.textScaleController == null) {
      _textScale.dispose();
    }
    _captureController.dispose();
    _assistantController.dispose();
    _graphController.dispose();
    _bookmarkController.dispose();
    _hardwareVoiceController.dispose();
    _voiceOutputPolicyController.dispose();
    _systemAssistantController.dispose();
    super.dispose();
  }

  Map<ShortcutActivator, VoidCallback> get _scaleShortcuts {
    return {
      const SingleActivator(LogicalKeyboardKey.equal, control: true): () =>
          _textScale.nudge(0.05),
      const SingleActivator(LogicalKeyboardKey.numpadAdd, control: true): () =>
          _textScale.nudge(0.05),
      const SingleActivator(LogicalKeyboardKey.minus, control: true): () =>
          _textScale.nudge(-0.05),
      const SingleActivator(
        LogicalKeyboardKey.numpadSubtract,
        control: true,
      ): () =>
          _textScale.nudge(-0.05),
      const SingleActivator(LogicalKeyboardKey.digit0, control: true): () =>
          _textScale.reset(),
      const SingleActivator(LogicalKeyboardKey.numpad0, control: true): () =>
          _textScale.reset(),
    };
  }

  @override
  Widget build(BuildContext context) {
    return UiTextScaleScope(
      controller: _textScale,
      child: CallbackShortcuts(
        bindings: _scaleShortcuts,
        child: Focus(
          autofocus: true,
          child: MaterialApp(
            navigatorKey: _navigatorKey,
            navigatorObservers: [appRouteObserver],
            title: 'Личный секретарь',
            locale: const Locale('ru', 'RU'),
            supportedLocales: const [Locale('ru', 'RU')],
            localizationsDelegates: const [
              GlobalMaterialLocalizations.delegate,
              GlobalWidgetsLocalizations.delegate,
              GlobalCupertinoLocalizations.delegate,
            ],
            theme: ThemeData(
              colorScheme: ColorScheme.fromSeed(seedColor: Colors.indigo),
              useMaterial3: true,
            ),
            builder: (context, child) {
              final mq = MediaQuery.of(context);
              return MediaQuery(
                data: mq.copyWith(
                  textScaler: TextScaler.linear(
                    mq.textScaler.scale(1.0) * _textScale.factor,
                  ),
                ),
                child: child ?? const SizedBox.shrink(),
              );
            },
            home: AuthGate(
              authController: widget.authController,
              captureController: _captureController,
              assistantController: _assistantController,
              graphController: _graphController,
              bookmarkController: _bookmarkController,
              hardwareVoiceController: _hardwareVoiceController,
              systemAssistantController: _systemAssistantController,
            ),
          ),
        ),
      ),
    );
  }
}
