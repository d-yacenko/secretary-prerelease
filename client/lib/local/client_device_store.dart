import 'dart:convert';
import 'dart:io' show Platform;
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:shared_preferences/shared_preferences.dart';

const _deviceKeyPref = 'secretary_device_key';
const _displayNamePref = 'secretary_device_display_name';

/// Persistent local device identity for client-assisted file intake.
class ClientDeviceStore {
  ClientDeviceStore({SharedPreferences? preferences})
      : _preferencesFuture = preferences != null
          ? Future.value(preferences)
          : SharedPreferences.getInstance();

  final Future<SharedPreferences> _preferencesFuture;

  Future<ClientDeviceIdentity> loadOrCreate() async {
    final prefs = await _preferencesFuture;
    final existingKey = prefs.getString(_deviceKeyPref);
    final existingName = prefs.getString(_displayNamePref);
    if (existingKey != null && existingName != null) {
      return ClientDeviceIdentity(deviceKey: existingKey, displayName: existingName);
    }
    final key = _generateDeviceKey();
    final name = _defaultDisplayName();
    await prefs.setString(_deviceKeyPref, key);
    await prefs.setString(_displayNamePref, name);
    return ClientDeviceIdentity(deviceKey: key, displayName: name);
  }

  String _defaultDisplayName() {
    if (kIsWeb) {
      return 'Этот компьютер';
    }
    if (Platform.isAndroid) {
      return 'Этот телефон';
    }
    return 'Этот компьютер';
  }

  String _generateDeviceKey() {
    final random = Random.secure();
    final bytes = List<int>.generate(16, (_) => random.nextInt(256));
    return base64Url.encode(bytes).replaceAll('=', '');
  }
}

class ClientDeviceIdentity {
  const ClientDeviceIdentity({
    required this.deviceKey,
    required this.displayName,
  });

  final String deviceKey;
  final String displayName;
}
