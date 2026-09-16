import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import 'hardware_voice_binding.dart';

class HardwareVoiceStore {
  HardwareVoiceStore({SharedPreferences? preferences})
    : _preferencesFuture = preferences != null
          ? Future.value(preferences)
          : SharedPreferences.getInstance();

  final Future<SharedPreferences> _preferencesFuture;

  static String prefKeyForUser(String userId) =>
      'hardware_voice_binding.$userId';

  Future<HardwareVoiceBinding?> load(String userId) async {
    if (userId.isEmpty) {
      return null;
    }
    final prefs = await _preferencesFuture;
    final raw = prefs.getString(prefKeyForUser(userId));
    if (raw == null || raw.isEmpty) {
      return null;
    }
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! Map) {
        return null;
      }
      return HardwareVoiceBinding.fromJson(Map<String, dynamic>.from(decoded));
    } on FormatException {
      return null;
    }
  }

  Future<void> save(String userId, HardwareVoiceBinding binding) async {
    if (userId.isEmpty) {
      return;
    }
    final prefs = await _preferencesFuture;
    await prefs.setString(
      prefKeyForUser(userId),
      jsonEncode(binding.normalized().toJson()),
    );
  }

  Future<void> clear(String userId) async {
    if (userId.isEmpty) {
      return;
    }
    final prefs = await _preferencesFuture;
    await prefs.remove(prefKeyForUser(userId));
  }
}
