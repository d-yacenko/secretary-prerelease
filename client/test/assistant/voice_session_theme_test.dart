import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/app.dart';
import 'package:personal_secretary/assistant/system_assistant_bridge.dart';
import 'package:personal_secretary/assistant/voice_session_app.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  AuthController buildAuth() {
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((_) async => http.Response('{}', 404)),
    );
    return AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
  }

  testWidgets('VoiceSessionApp uses dark theme under system dark brightness', (
    tester,
  ) async {
    tester.platformDispatcher.platformBrightnessTestValue = Brightness.dark;
    addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
    final auth = buildAuth();
    final systemAssistant = SystemAssistantController(
      bridge: NoopSystemAssistantBridge(),
    );
    await tester.pumpWidget(
      VoiceSessionApp(authController: auth, systemAssistant: systemAssistant),
    );
    await tester.pump();
    for (var i = 0; i < 20; i++) {
      await tester.pump(const Duration(milliseconds: 20));
      if (find.byType(Scaffold).evaluate().isNotEmpty) {
        break;
      }
    }
    final app = tester.widget<MaterialApp>(find.byType(MaterialApp));
    expect(app.themeMode, ThemeMode.system);
    expect(app.darkTheme, isNotNull);
    expect(app.theme?.brightness, Brightness.light);
    expect(app.darkTheme?.brightness, Brightness.dark);
    final ctx = tester.element(find.byType(Scaffold).first);
    expect(Theme.of(ctx).brightness, Brightness.dark);
    expect(Theme.of(ctx).colorScheme.surface, isNot(Colors.white));
    systemAssistant.dispose();
  });

  testWidgets('VoiceSessionApp uses light theme under system light brightness', (
    tester,
  ) async {
    tester.platformDispatcher.platformBrightnessTestValue = Brightness.light;
    addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
    final auth = buildAuth();
    final systemAssistant = SystemAssistantController(
      bridge: NoopSystemAssistantBridge(),
    );
    await tester.pumpWidget(
      VoiceSessionApp(authController: auth, systemAssistant: systemAssistant),
    );
    await tester.pump();
    for (var i = 0; i < 20; i++) {
      await tester.pump(const Duration(milliseconds: 20));
      if (find.byType(Scaffold).evaluate().isNotEmpty) {
        break;
      }
    }
    final ctx = tester.element(find.byType(Scaffold).first);
    expect(Theme.of(ctx).brightness, Brightness.light);
    systemAssistant.dispose();
  });

  testWidgets('ordinary Secretary app keeps a light-only theme', (tester) async {
    tester.platformDispatcher.platformBrightnessTestValue = Brightness.dark;
    addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
    final auth = buildAuth();
    await tester.pumpWidget(PersonalSecretaryApp(authController: auth));
    await tester.pump();
    final app = tester.widget<MaterialApp>(find.byType(MaterialApp));
    expect(app.darkTheme, isNull);
    expect(app.theme?.brightness, Brightness.light);
  });
}
