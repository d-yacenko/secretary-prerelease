import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'voice_output_policy.dart';

class VoiceOutputPolicyStore {
  VoiceOutputPolicyStore({SharedPreferences? preferences})
    : _memory =
          preferences == null && Platform.environment['FLUTTER_TEST'] == 'true'
          ? <String, String>{}
          : null,
      _preferencesFuture = preferences != null
          ? Future.value(preferences)
          : (Platform.environment['FLUTTER_TEST'] == 'true'
                ? null
                : SharedPreferences.getInstance());

  VoiceOutputPolicyStore.memory({Map<String, String>? initial})
    : _memory = {...?initial},
      _preferencesFuture = null;

  final Map<String, String>? _memory;
  final Future<SharedPreferences>? _preferencesFuture;

  static const storedHandsFreeEnabled = 'hands_free_enabled';
  static const storedNever = 'never';
  static const legacyHandsFreeOnly = 'hands_free_only';
  static const legacyAllVoiceInput = 'all_voice_input';

  static String prefKeyForUser(String userId) => 'voice_output_policy.$userId';

  Future<VoiceOutputPolicy> load(String userId) async {
    if (userId.isEmpty) {
      return VoiceOutputPolicy.handsFreeEnabled;
    }
    final raw = await _readRaw(userId);
    final policy = decode(raw);
    final canonical = encode(policy);
    if (raw != null && raw != canonical) {
      await save(userId, policy);
    }
    return policy;
  }

  Future<void> save(String userId, VoiceOutputPolicy policy) async {
    if (userId.isEmpty) {
      return;
    }
    final memory = _memory;
    if (memory != null) {
      memory[prefKeyForUser(userId)] = encode(policy);
      return;
    }
    final prefs = await _preferencesFuture!;
    await prefs.setString(prefKeyForUser(userId), encode(policy));
  }

  @visibleForTesting
  Future<String?> storedRaw(String userId) => _readRaw(userId);

  Future<String?> _readRaw(String userId) async {
    final memory = _memory;
    if (memory != null) {
      return memory[prefKeyForUser(userId)];
    }
    final prefs = await _preferencesFuture!;
    return prefs.getString(prefKeyForUser(userId));
  }

  static String encode(VoiceOutputPolicy policy) {
    switch (policy) {
      case VoiceOutputPolicy.handsFreeEnabled:
        return storedHandsFreeEnabled;
      case VoiceOutputPolicy.never:
        return storedNever;
    }
  }

  static VoiceOutputPolicy decode(String? raw) {
    switch (raw) {
      case storedNever:
        return VoiceOutputPolicy.never;
      case storedHandsFreeEnabled:
      case legacyHandsFreeOnly:
      case legacyAllVoiceInput:
      default:
        return VoiceOutputPolicy.handsFreeEnabled;
    }
  }
}
