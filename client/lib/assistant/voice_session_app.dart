import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import '../auth/auth_controller.dart';
import 'assistant_controller.dart';
import 'system_assistant_bridge.dart';
import 'voice_session_screen.dart';

/// Minimal lock-screen / overlay isolate. No Inbox or history.
class VoiceSessionApp extends StatefulWidget {
  const VoiceSessionApp({
    super.key,
    required this.authController,
    this.assistant,
    this.systemAssistant,
  });

  final AuthController authController;
  final AssistantController? assistant;
  final SystemAssistantController? systemAssistant;

  @override
  State<VoiceSessionApp> createState() => _VoiceSessionAppState();
}

class _VoiceSessionAppState extends State<VoiceSessionApp> {
  late final AssistantController _assistant;
  late final SystemAssistantController _systemAssistant;
  late final bool _ownsAssistant;
  late final bool _ownsSystemAssistant;
  var _gateReady = false;

  @override
  void initState() {
    super.initState();
    _ownsAssistant = widget.assistant == null;
    _ownsSystemAssistant = widget.systemAssistant == null;
    _assistant =
        widget.assistant ??
        AssistantController(
          apiClient: widget.authController.apiClient,
          authController: widget.authController,
          lockScreenSession: true,
        );
    _systemAssistant = widget.systemAssistant ?? SystemAssistantController();
    widget.authController.addListener(_onAuth);
    _bootstrap();
  }

  Future<void> _bootstrap() async {
    await widget.authController.initialize();
    if (!mounted) {
      return;
    }
    await _systemAssistant.attach(widget.authController.user?.id);
    if (!mounted) {
      return;
    }
    _assistant.keyguardLocked = _systemAssistant.keyguardLocked;
    _assistant.lockScreenVoiceEnabled = _systemAssistant.lockScreenVoiceEnabled;
    _assistant.setDrivingSession(
      authorized: _systemAssistant.drivingSessionAuthorized,
      sessionId: _systemAssistant.drivingSessionId,
    );
    setState(() {
      _gateReady = true;
    });
  }

  void _onAuth() {
    if (!_gateReady) {
      if (mounted) {
        setState(() {});
      }
      return;
    }
    _syncAssistantGate();
    setState(() {});
  }

  Future<void> _syncAssistantGate() async {
    await _systemAssistant.attach(widget.authController.user?.id);
    if (widget.authController.status != AuthStatus.authenticated) {
      await _systemAssistant.clearDrivingSession();
      _assistant.clearDrivingAuthorization();
    }
    _assistant.keyguardLocked = _systemAssistant.keyguardLocked;
    _assistant.lockScreenVoiceEnabled = _systemAssistant.lockScreenVoiceEnabled;
    _assistant.setDrivingSession(
      authorized: _systemAssistant.drivingSessionAuthorized,
      sessionId: _systemAssistant.drivingSessionId,
    );
  }

  @override
  void dispose() {
    widget.authController.removeListener(_onAuth);
    if (_ownsAssistant) {
      _assistant.dispose();
    }
    if (_ownsSystemAssistant) {
      _systemAssistant.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Секретарь',
      locale: const Locale('ru', 'RU'),
      supportedLocales: const [Locale('ru', 'RU')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: Colors.indigo,
          brightness: Brightness.light,
        ),
        useMaterial3: true,
      ),
      darkTheme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: Colors.indigo,
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      themeMode: ThemeMode.system,
      home:
          !_gateReady ||
              widget.authController.status == AuthStatus.initial ||
              widget.authController.status == AuthStatus.loading
          ? const Scaffold(body: Center(child: CircularProgressIndicator()))
          : widget.authController.status == AuthStatus.authenticated
          ? VoiceSessionScreen(
              assistant: _assistant,
              systemAssistant: _systemAssistant,
            )
          : VoiceSessionLockedSignInScreen(systemAssistant: _systemAssistant),
    );
  }
}

class VoiceSessionLockedSignInScreen extends StatelessWidget {
  const VoiceSessionLockedSignInScreen({
    super.key,
    required this.systemAssistant,
  });

  final SystemAssistantController systemAssistant;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Spacer(),
              Text(
                lockScreenSignInMessage,
                key: const Key('voice_session_sign_in_required'),
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.headlineSmall,
              ),
              const Spacer(),
              TextButton(
                key: const Key('voice_session_close'),
                onPressed: systemAssistant.dismissOverlay,
                child: const Text('Закрыть'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
