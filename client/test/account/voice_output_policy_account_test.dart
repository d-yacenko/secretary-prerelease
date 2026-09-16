import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/account/account_screen.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/assistant/voice_output_policy.dart';
import 'package:personal_secretary/assistant/voice_output_policy_controller.dart';
import 'package:personal_secretary/assistant/voice_output_policy_store.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'account_test_helpers.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  Future<VoiceOutputPolicyController> buildPolicy(AuthController auth) async {
    final controller = VoiceOutputPolicyController(
      authController: auth,
      store: VoiceOutputPolicyStore(
        preferences: await SharedPreferences.getInstance(),
      ),
    );
    await controller.attach();
    return controller;
  }

  AccountScreen screen({
    required AuthController auth,
    required VoiceOutputPolicyController policy,
    TargetPlatform platform = TargetPlatform.linux,
  }) {
    return AccountScreen(
      apiClient: auth.apiClient,
      authController: auth,
      initialConnections: Connections.fromJson(accountConnectionsJson()),
      initialSettings: UserSettings.fromJson(accountSettingsJson()),
      initialSourcePreferences: SourcePreferenceList.fromJson(
        accountSourcePreferencesJson(),
      ).preferences,
      initialIdentity: UserIdentity.fromJson(accountIdentityJson()),
      initialSemanticContext: UserSemanticContext.fromJson(
        accountSemanticContextJson(),
      ),
      voiceOutputPolicyController: policy,
      voiceOutputPolicyPlatform: platform,
    );
  }

  testWidgets('Linux and Android account show local auto-speech preference', (
    tester,
  ) async {
    final client = buildAccountApiClient();
    final auth = AuthController(
      apiClient: client,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    auth.user = UserMe(
      id: 'user-1',
      displayName: 'Alice',
      createdAt: '2026-01-01T00:00:00Z',
    );
    final policy = await buildPolicy(auth);
    await pumpAccountReady(tester, screen(auth: auth, policy: policy));
    expect(find.text('Автоозвучивание ответов'), findsOneWidget);
    expect(find.text('Озвучивать ответы в hands-free режиме'), findsOneWidget);
    expect(
      find.text(
        'Экранный микрофон используется только для диктовки и не '
        'включает автоозвучивание.',
      ),
      findsOneWidget,
    );
    expect(find.text('После любого голосового ввода'), findsNothing);
    expect(find.text('Только hands-free'), findsNothing);
    expect(policy.policy, VoiceOutputPolicy.handsFreeEnabled);
    await tester.tap(
      find.byKey(const Key('voice_output_policy_hands_free_enabled')),
    );
    await tester.pump();
    expect(policy.policy, VoiceOutputPolicy.never);
    policy.dispose();
  });

  testWidgets('Windows account hides auto-speech preference', (tester) async {
    final client = buildAccountApiClient();
    final auth = AuthController(
      apiClient: client,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    auth.user = UserMe(
      id: 'user-1',
      displayName: 'Alice',
      createdAt: '2026-01-01T00:00:00Z',
    );
    final policy = await buildPolicy(auth);
    await pumpAccountReady(
      tester,
      screen(auth: auth, policy: policy, platform: TargetPlatform.windows),
    );
    expect(find.text('Автоозвучивание ответов'), findsNothing);
    policy.dispose();
  });
}
