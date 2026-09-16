import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'app.dart';
import 'api/secretary_api_client.dart';
import 'assistant/voice_session_app.dart';
import 'auth/auth_controller.dart';
import 'auth/secure_token_store.dart';
import 'auth/server_url_store.dart';

const String voiceSessionRoute = '/voice_session';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  const defaultBaseUrl = String.fromEnvironment('SECRETARY_API_BASE_URL');

  final prefs = await SharedPreferences.getInstance();
  final apiClient = SecretaryApiClient();
  final authController = AuthController(
    apiClient: apiClient,
    tokenStore: SecureTokenStore(),
    serverUrlStore: SharedPreferencesServerUrlStore(prefs),
    defaultBaseUrl: defaultBaseUrl.isEmpty ? null : defaultBaseUrl,
  );

  final route = WidgetsBinding.instance.platformDispatcher.defaultRouteName;
  if (route == voiceSessionRoute) {
    runApp(VoiceSessionApp(authController: authController));
    return;
  }

  runApp(PersonalSecretaryApp(authController: authController));
}
