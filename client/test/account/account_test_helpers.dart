import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/account/account_screen.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';

Map<String, dynamic> accountConnectionsJson({
  bool googleConnected = true,
  bool gmailAvailable = true,
  bool calendarAvailable = true,
  bool driveAvailable = false,
  List<Map<String, dynamic>> mattermost = const [],
  Map<String, dynamic>? telegram,
  Map<String, dynamic>? teams,
}) {
  return {
    'google': {
      'connected': googleConnected,
      'email': 'alice@gmail.com',
      'gmail_available': gmailAvailable,
      'calendar_available': calendarAvailable,
      'drive_available': driveAvailable,
    },
    'yandex_mail': {'connected': false, 'email': null},
    'yandex_calendar': {'connected': false, 'email': null},
    'mattermost': mattermost,
    'telegram': telegram ??
        {
          'configured': false,
          'identity_linked': false,
          'business_connected': false,
          'can_reply': false,
          'telegram_username': null,
          'display_name': null,
          'bot_username': null,
        },
    'teams': teams ??
        {
          'configured': false,
          'connected': false,
          'reconnect_required': false,
          'display_name': null,
          'upn': null,
          'tenant_id': null,
        },
  };
}

Map<String, dynamic> accountSettingsJson({
  String timezone = 'Europe/Amsterdam',
  String assistantModel = 'gpt-5.6-luna',
  String assistantReasoningEffort = 'low',
  String assistantVerbosity = 'low',
  int assistantMaxRounds = 6,
  int? assistantMaxRoundsOverride,
  int defaultAssistantMaxRounds = 6,
  int minAssistantMaxRounds = 1,
  int maxAssistantMaxRounds = 12,
  bool openaiKeyConfigured = false,
  List<String> allowedAssistantModels = const ['gpt-5.6-luna', 'gpt-5.6-terra'],
  bool autoLabelEnabled = false,
  int? openaiDailyTokenLimit,
  int tokensUsedToday = 0,
  bool budgetExhausted = false,
  String budgetResetAt = '2026-09-13T00:00:00+00:00',
}) {
  return {
    'timezone': timezone,
    'assistant_model': assistantModel,
    'assistant_reasoning_effort': assistantReasoningEffort,
    'assistant_verbosity': assistantVerbosity,
    'assistant_max_rounds': assistantMaxRounds,
    'assistant_max_rounds_override': assistantMaxRoundsOverride,
    'default_assistant_max_rounds': defaultAssistantMaxRounds,
    'min_assistant_max_rounds': minAssistantMaxRounds,
    'max_assistant_max_rounds': maxAssistantMaxRounds,
    'openai_key_configured': openaiKeyConfigured,
    'allowed_assistant_models': allowedAssistantModels,
    'auto_label_enabled': autoLabelEnabled,
    'temporal_signals_enabled': false,
    'openai_daily_token_limit': openaiDailyTokenLimit,
    'min_openai_daily_token_limit': 1,
    'max_openai_daily_token_limit': 1000000000,
    'openai_daily_budget': {
      'daily_token_limit': openaiDailyTokenLimit,
      'tokens_used_today': tokensUsedToday,
      'exhausted': budgetExhausted,
      'reset_at': budgetResetAt,
    },
  };
}

bool isAccountSettingsRequest(Uri url) => url.path.endsWith('/me/settings');

Map<String, dynamic> accountIdentityJson({
  String profileText = '',
  String? fullName,
  String? preferredName,
}) {
  return {
    'profile_text': profileText,
    'full_name': fullName,
    'preferred_name': preferredName,
    'parsed': {
      'full_name': fullName,
      'preferred_name': preferredName,
      'aliases': <String>[],
      'roles': <String>[],
      'organizations': <String>[],
      'emails': <String>[],
      'phones': <String>[],
      'telegram': <String>[],
      'other_identifiers': <String>[],
    },
  };
}

bool isAccountIdentityRequest(Uri url) => url.path.endsWith('/me/identity');

Map<String, dynamic> accountSemanticContextJson({String contextText = ''}) {
  return {'context_text': contextText};
}

bool isAccountSemanticContextRequest(Uri url) =>
    url.path.endsWith('/me/semantic-context');

Map<String, dynamic> accountSourcePreferenceEntryJson({
  String source = 'gmail',
  bool enabled = true,
  int syncIntervalSeconds = 300,
  int defaultSyncIntervalSeconds = 300,
  int minSyncIntervalSeconds = 60,
  int maxSyncIntervalSeconds = 86400,
  int historyDays = 30,
  int defaultHistoryDays = 30,
  int minHistoryDays = 1,
  int maxHistoryDays = 90,
}) {
  return {
    'source': source,
    'enabled': enabled,
    'sync_interval_seconds': syncIntervalSeconds,
    'default_sync_interval_seconds': defaultSyncIntervalSeconds,
    'min_sync_interval_seconds': minSyncIntervalSeconds,
    'max_sync_interval_seconds': maxSyncIntervalSeconds,
    'history_days': historyDays,
    'default_history_days': defaultHistoryDays,
    'min_history_days': minHistoryDays,
    'max_history_days': maxHistoryDays,
  };
}

Map<String, dynamic> accountSourcePreferencesJson({
  int minInterval = 60,
  int maxInterval = 86400,
  int minHistoryDays = 1,
  int maxHistoryDays = 90,
}) {
  Map<String, dynamic> pref(
      String source, int defaultSeconds, int historyDays) {
    return accountSourcePreferenceEntryJson(
      source: source,
      syncIntervalSeconds: defaultSeconds,
      defaultSyncIntervalSeconds: defaultSeconds,
      minSyncIntervalSeconds: minInterval,
      maxSyncIntervalSeconds: maxInterval,
      historyDays: historyDays,
      defaultHistoryDays: historyDays,
      minHistoryDays: minHistoryDays,
      maxHistoryDays: maxHistoryDays,
    );
  }

  return {
    'preferences': [
      pref('gmail', 300, 30),
      pref('google_calendar', 300, 30),
      pref('yandex_mail', 300, 30),
      pref('yandex_calendar', 300, 30),
      pref('mattermost', 120, 14),
      pref('teams', 60, 1),
    ],
  };
}

bool isAccountSourcePreferencesRequest(Uri url) =>
    url.path.endsWith('/me/source-preferences');

class StubSecretaryApiClient extends SecretaryApiClient {
  StubSecretaryApiClient({
    required Connections connections,
    required UserSettings settings,
    List<SourcePreference>? sourcePreferences,
    UserIdentity? identity,
    http.Client? httpClient,
  })  : _connections = connections,
        _settings = settings,
        _sourcePreferences = sourcePreferences ??
            SourcePreferenceList.fromJson(accountSourcePreferencesJson())
                .preferences,
        _identity = identity ?? UserIdentity.fromJson(accountIdentityJson()),
        _semanticContext = UserSemanticContext.fromJson(
          accountSemanticContextJson(),
        ),
        super(
            httpClient: httpClient ??
                MockClient((_) async => http.Response('{}', 404)));

  final Connections _connections;
  final UserSettings _settings;
  final List<SourcePreference> _sourcePreferences;
  final UserIdentity _identity;
  UserSemanticContext _semanticContext;

  @override
  Future<Connections> getConnections() async => _connections;

  @override
  Future<UserSettings> getSettings() async => _settings;

  @override
  Future<List<SourcePreference>> getSourcePreferences() async =>
      List<SourcePreference>.from(_sourcePreferences);

  @override
  Future<UserIdentity> getIdentity() async => _identity;

  @override
  Future<UserIdentity> putIdentity({required String profileText}) async {
    return UserIdentity(
      profileText: profileText,
      fullName: _identity.fullName,
      preferredName: _identity.preferredName,
    );
  }

  @override
  Future<UserSemanticContext> getSemanticContext() async => _semanticContext;

  @override
  Future<UserSemanticContext> putSemanticContext({
    required String contextText,
  }) async {
    _semanticContext = UserSemanticContext(contextText: contextText);
    return _semanticContext;
  }

  @override
  Future<LabelList> listLabels({int limit = 100}) async {
    return LabelList(labels: const []);
  }
}

SecretaryApiClient buildAccountApiClient({
  Map<String, dynamic>? connectionsJson,
  Map<String, dynamic>? settingsJson,
  Map<String, dynamic>? sourcePreferencesJson,
  http.Client? httpClient,
}) {
  return StubSecretaryApiClient(
    connections:
        Connections.fromJson(connectionsJson ?? accountConnectionsJson()),
    settings: UserSettings.fromJson(settingsJson ?? accountSettingsJson()),
    sourcePreferences: sourcePreferencesJson == null
        ? null
        : SourcePreferenceList.fromJson(sourcePreferencesJson).preferences,
    httpClient: httpClient,
  );
}

AccountScreen buildAccountScreen({
  required SecretaryApiClient apiClient,
  required AuthController authController,
  Map<String, dynamic>? connectionsJson,
  Map<String, dynamic>? settingsJson,
  Map<String, dynamic>? sourcePreferencesJson,
  Map<String, dynamic>? identityJson,
  Map<String, dynamic>? semanticContextJson,
}) {
  final connections =
      Connections.fromJson(connectionsJson ?? accountConnectionsJson());
  final settings = UserSettings.fromJson(settingsJson ?? accountSettingsJson());
  final sourcePreferences = sourcePreferencesJson == null
      ? SourcePreferenceList.fromJson(accountSourcePreferencesJson())
          .preferences
      : SourcePreferenceList.fromJson(sourcePreferencesJson).preferences;
  final identity =
      UserIdentity.fromJson(identityJson ?? accountIdentityJson());
  final semanticContext = UserSemanticContext.fromJson(
    semanticContextJson ?? accountSemanticContextJson(),
  );
  return AccountScreen(
    apiClient: apiClient,
    authController: authController,
    initialConnections: connections,
    initialSettings: settings,
    initialSourcePreferences: sourcePreferences,
    initialIdentity: identity,
    initialSemanticContext: semanticContext,
  );
}

Future<void> pumpAccountReady(WidgetTester tester, Widget child) async {
  final binding = tester.binding;
  binding.window.physicalSizeTestValue = const Size(800, 3000);
  binding.window.devicePixelRatioTestValue = 1.0;
  addTearDown(binding.window.clearPhysicalSizeTestValue);
  addTearDown(binding.window.clearDevicePixelRatioTestValue);

  await tester.pumpWidget(MaterialApp(home: child));
  await tester.pump();
  for (var i = 0; i < 20; i++) {
    await tester.pump(const Duration(milliseconds: 50));
    if (find.textContaining('Gmail доступен').evaluate().isNotEmpty) {
      return;
    }
  }
}

Future<void> tapAccountText(WidgetTester tester, String text) async {
  final finder = find.text(text);
  await tester.ensureVisible(finder);
  await tester.pump();
  await tester.tap(finder);
}
