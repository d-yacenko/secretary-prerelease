import 'package:flutter/foundation.dart';

import '../auth/auth_controller.dart';
import 'voice_output_policy.dart';
import 'voice_output_policy_store.dart';

class VoiceOutputPolicyController extends ChangeNotifier {
  VoiceOutputPolicyController({
    required AuthController authController,
    VoiceOutputPolicyStore? store,
    VoiceOutputPolicy initialPolicy = VoiceOutputPolicy.handsFreeEnabled,
  }) : _authController = authController,
       _store = store ?? VoiceOutputPolicyStore(),
       _policy = initialPolicy {
    _authController.addListener(_onAuthChanged);
  }

  final AuthController _authController;
  final VoiceOutputPolicyStore _store;

  VoiceOutputPolicy _policy;
  String? _userId;

  VoiceOutputPolicy get policy => _policy;

  Future<void> attach() async {
    await _loadFor(_authController.user?.id);
  }

  Future<void> setPolicy(VoiceOutputPolicy value) async {
    _policy = value;
    notifyListeners();
    final userId = _userId;
    if (userId == null || userId.isEmpty) {
      return;
    }
    await _store.save(userId, value);
  }

  Future<void> _onAuthChanged() async {
    await _loadFor(_authController.user?.id);
  }

  Future<void> _loadFor(String? userId) async {
    if (userId == null || userId.isEmpty) {
      _userId = null;
      _policy = VoiceOutputPolicy.handsFreeEnabled;
      notifyListeners();
      return;
    }
    if (userId == _userId) {
      return;
    }
    _userId = userId;
    _policy = await _store.load(userId);
    notifyListeners();
  }

  @override
  void dispose() {
    _authController.removeListener(_onAuthChanged);
    super.dispose();
  }
}
