import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

const String systemAssistantChannelName = 'secretary/system_assistant';
const String systemAssistantProtocol = 'secretary.system_assistant.v1';

const String lockScreenVoiceEnabledMessage =
    'Голос с заблокированного экрана выключен.';
const String lockScreenSignInMessage =
    'Откройте Секретарь после разблокировки и войдите в аккаунт.';
const String lockScreenDrivingWritePolicyMessage =
    'В режиме вождения письма и сообщения можно подтвердить голосом после полного '
    'прочтения. Для остальных защищённых действий потребуется разблокировка.';

class SystemAssistantStatus {
  const SystemAssistantStatus({
    required this.available,
    required this.isDefaultAssistant,
    required this.roleManagerAvailable,
    required this.keyguardLocked,
    this.protocol = '',
    this.drivingSessionAuthorized = false,
    this.drivingSessionId,
  });

  final bool available;
  final bool isDefaultAssistant;
  final bool roleManagerAvailable;
  final bool keyguardLocked;
  final String protocol;
  final bool drivingSessionAuthorized;
  final String? drivingSessionId;

  bool get isHealthy => available && protocol == systemAssistantProtocol;
}

abstract class SystemAssistantBridge {
  void setOnAssist(VoidCallback? callback);

  void setOnKeyguard(void Function(bool locked)? callback);

  void setOnRoleResult(void Function(SystemAssistantStatus status)? callback);

  Future<SystemAssistantStatus> getStatus();

  Future<void> requestAssistantRole();

  Future<void> openLockScreenLauncher();

  Future<void> clearDrivingSession();

  Future<void> dismiss();
}

class NoopSystemAssistantBridge implements SystemAssistantBridge {
  @override
  void setOnAssist(VoidCallback? callback) {}

  @override
  void setOnKeyguard(void Function(bool locked)? callback) {}

  @override
  void setOnRoleResult(void Function(SystemAssistantStatus status)? callback) {}

  @override
  Future<SystemAssistantStatus> getStatus() async {
    return const SystemAssistantStatus(
      available: false,
      isDefaultAssistant: false,
      roleManagerAvailable: false,
      keyguardLocked: false,
    );
  }

  @override
  Future<void> requestAssistantRole() async {}

  @override
  Future<void> openLockScreenLauncher() async {}

  @override
  Future<void> clearDrivingSession() async {}

  @override
  Future<void> dismiss() async {}
}

class MethodChannelSystemAssistantBridge implements SystemAssistantBridge {
  MethodChannelSystemAssistantBridge({MethodChannel? channel})
    : _channel = channel ?? const MethodChannel(systemAssistantChannelName) {
    _channel.setMethodCallHandler(_onCall);
  }

  final MethodChannel _channel;
  VoidCallback? _onAssist;
  void Function(bool locked)? _onKeyguard;
  void Function(SystemAssistantStatus status)? _onRoleResult;
  var _pendingAssists = 0;

  @override
  void setOnAssist(VoidCallback? callback) {
    _onAssist = callback;
    _flushPendingAssists();
  }

  @override
  void setOnKeyguard(void Function(bool locked)? callback) {
    _onKeyguard = callback;
  }

  @override
  void setOnRoleResult(void Function(SystemAssistantStatus status)? callback) {
    _onRoleResult = callback;
  }

  @override
  Future<SystemAssistantStatus> getStatus() async {
    try {
      final raw = await _channel.invokeMethod<dynamic>('getStatus');
      return _parse(raw);
    } on MissingPluginException {
      return const SystemAssistantStatus(
        available: false,
        isDefaultAssistant: false,
        roleManagerAvailable: false,
        keyguardLocked: false,
      );
    } on PlatformException {
      return const SystemAssistantStatus(
        available: false,
        isDefaultAssistant: false,
        roleManagerAvailable: false,
        keyguardLocked: false,
      );
    }
  }

  @override
  Future<void> requestAssistantRole() async {
    try {
      await _channel.invokeMethod<void>('requestAssistantRole');
    } on MissingPluginException {
      return;
    } on PlatformException {
      return;
    }
  }

  @override
  Future<void> openLockScreenLauncher() async {
    try {
      await _channel.invokeMethod<void>('openLockScreenLauncher');
    } on MissingPluginException {
      return;
    } on PlatformException {
      return;
    }
  }

  @override
  Future<void> clearDrivingSession() async {
    try {
      await _channel.invokeMethod<void>('clearDrivingSession');
    } on MissingPluginException {
      return;
    } on PlatformException {
      return;
    }
  }

  @override
  Future<void> dismiss() async {
    try {
      await _channel.invokeMethod<void>('dismiss');
    } on MissingPluginException {
      return;
    } on PlatformException {
      return;
    }
  }

  Future<dynamic> _onCall(MethodCall call) async {
    switch (call.method) {
      case 'onAssistInvoke':
        _deliverAssist();
        return null;
      case 'onKeyguard':
        final locked = call.arguments == true;
        _onKeyguard?.call(locked);
        return null;
      case 'onRoleResult':
        _onRoleResult?.call(_parse(call.arguments));
        return null;
      default:
        return null;
    }
  }

  void _deliverAssist() {
    final handler = _onAssist;
    if (handler == null) {
      _pendingAssists += 1;
      return;
    }
    handler();
  }

  void _flushPendingAssists() {
    final handler = _onAssist;
    if (handler == null) {
      return;
    }
    while (_pendingAssists > 0) {
      _pendingAssists -= 1;
      handler();
    }
  }

  SystemAssistantStatus _parse(dynamic arguments) {
    if (arguments is! Map) {
      return const SystemAssistantStatus(
        available: false,
        isDefaultAssistant: false,
        roleManagerAvailable: false,
        keyguardLocked: false,
      );
    }
    final map = Map<Object?, Object?>.from(arguments);
    return SystemAssistantStatus(
      available: map['available'] == true,
      isDefaultAssistant: map['isDefaultAssistant'] == true,
      roleManagerAvailable: map['roleManagerAvailable'] == true,
      keyguardLocked: map['keyguardLocked'] == true,
      protocol: map['protocol'] as String? ?? '',
      drivingSessionAuthorized: map['drivingSessionAuthorized'] == true,
      drivingSessionId: map['drivingSessionId'] as String?,
    );
  }
}

class LockScreenVoiceStore {
  LockScreenVoiceStore({SharedPreferences? preferences})
    : _preferencesFuture = preferences != null
          ? Future.value(preferences)
          : SharedPreferences.getInstance();

  final Future<SharedPreferences> _preferencesFuture;

  static String prefKeyForUser(String userId) =>
      'lock_screen_voice_enabled.$userId';

  Future<bool> load(String userId) async {
    if (userId.isEmpty) {
      return false;
    }
    final prefs = await _preferencesFuture;
    return prefs.getBool(prefKeyForUser(userId)) ?? false;
  }

  Future<void> save(String userId, bool enabled) async {
    if (userId.isEmpty) {
      return;
    }
    final prefs = await _preferencesFuture;
    await prefs.setBool(prefKeyForUser(userId), enabled);
  }
}

class SystemAssistantController extends ChangeNotifier {
  SystemAssistantController({
    SystemAssistantBridge? bridge,
    LockScreenVoiceStore? store,
  }) : _bridge =
           bridge ??
           (!kIsWeb && Platform.isAndroid
               ? MethodChannelSystemAssistantBridge()
               : NoopSystemAssistantBridge()),
       _store = store ?? LockScreenVoiceStore() {
    _bridge.setOnAssist(_deliverAssist);
    _bridge.setOnKeyguard((locked) {
      keyguardLocked = locked;
      notifyListeners();
    });
    _bridge.setOnRoleResult(_applyStatus);
  }

  final SystemAssistantBridge _bridge;
  final LockScreenVoiceStore _store;

  VoidCallback? _onAssistInvoke;
  var _pendingAssists = 0;

  VoidCallback? get onAssistInvoke => _onAssistInvoke;

  set onAssistInvoke(VoidCallback? callback) {
    _onAssistInvoke = callback;
    _flushPendingAssists();
  }

  bool available = false;
  bool isDefaultAssistant = false;
  bool roleManagerAvailable = false;
  bool keyguardLocked = false;
  bool lockScreenVoiceEnabled = false;
  bool drivingSessionAuthorized = false;
  String? drivingSessionId;
  String? _userId;

  Future<void> attach(String? userId) async {
    _userId = userId;
    if (userId != null && userId.isNotEmpty) {
      lockScreenVoiceEnabled = await _store.load(userId);
    } else {
      lockScreenVoiceEnabled = false;
      await clearDrivingSession();
    }
    await refresh();
  }

  Future<void> refresh() async {
    _applyStatus(await _bridge.getStatus());
  }

  Future<void> requestAssistantRole() async {
    await _bridge.requestAssistantRole();
  }

  Future<void> openLockScreenLauncher() async {
    if (!lockScreenVoiceEnabled) {
      return;
    }
    await _bridge.openLockScreenLauncher();
    await refresh();
  }

  Future<void> clearDrivingSession() async {
    drivingSessionAuthorized = false;
    drivingSessionId = null;
    notifyListeners();
    await _bridge.clearDrivingSession();
  }

  Future<void> setLockScreenVoiceEnabled(bool enabled) async {
    lockScreenVoiceEnabled = enabled;
    final userId = _userId;
    if (userId != null) {
      await _store.save(userId, enabled);
    }
    notifyListeners();
  }

  Future<void> dismissOverlay() async {
    await _bridge.dismiss();
    drivingSessionAuthorized = false;
    drivingSessionId = null;
    notifyListeners();
  }

  void _deliverAssist() {
    final handler = _onAssistInvoke;
    if (handler == null) {
      _pendingAssists += 1;
      return;
    }
    handler();
  }

  void _flushPendingAssists() {
    final handler = _onAssistInvoke;
    if (handler == null) {
      return;
    }
    while (_pendingAssists > 0) {
      _pendingAssists -= 1;
      handler();
    }
  }

  void _applyStatus(SystemAssistantStatus status) {
    available = status.isHealthy;
    isDefaultAssistant = status.isDefaultAssistant;
    roleManagerAvailable = status.roleManagerAvailable;
    keyguardLocked = status.keyguardLocked;
    final sessionId = status.drivingSessionId;
    drivingSessionAuthorized =
        status.drivingSessionAuthorized &&
        sessionId != null &&
        sessionId.isNotEmpty;
    drivingSessionId = drivingSessionAuthorized ? sessionId : null;
    notifyListeners();
  }

  @override
  void dispose() {
    _bridge.setOnAssist(null);
    _bridge.setOnKeyguard(null);
    _bridge.setOnRoleResult(null);
    super.dispose();
  }
}

bool systemAssistantSettingsVisible({TargetPlatform? platform}) {
  final resolved = platform ?? defaultTargetPlatform;
  return !kIsWeb && resolved == TargetPlatform.android;
}
