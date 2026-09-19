import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart' as url_launcher;

import '../api/api_error.dart';
import '../api/api_models.dart';
import '../api/secretary_api_client.dart';
import '../auth/auth_controller.dart';
import '../assistant/hardware_voice_controller.dart';
import '../assistant/system_assistant_bridge.dart';
import '../assistant/voice_output_policy_controller.dart';
import '../ui/domain_labels.dart';
import '../ui/ui_text_scale.dart';
import 'account_labels_section.dart';
import 'account_layout.dart';
import 'client_disconnect.dart';
import 'hardware_voice_account_section.dart';
import 'identity_profile_template.dart';
import 'semantic_context_template.dart';
import 'source_preferences_list.dart';
import 'system_assistant_account_section.dart';
import 'telegram_mtproto_account_section.dart';
import 'voice_output_policy_account_section.dart';

class AccountScreen extends StatefulWidget {
  const AccountScreen({
    super.key,
    required this.apiClient,
    required this.authController,
    this.initialConnections,
    this.initialSettings,
    this.initialSourcePreferences,
    this.initialIdentity,
    this.initialSemanticContext,
    this.hardwareVoiceController,
    this.hardwareVoicePlatform,
    this.systemAssistantController,
    this.systemAssistantPlatform,
    this.voiceOutputPolicyController,
    this.voiceOutputPolicyPlatform,
  });

  final SecretaryApiClient apiClient;
  final AuthController authController;
  final Connections? initialConnections;
  final UserSettings? initialSettings;
  final List<SourcePreference>? initialSourcePreferences;
  final UserIdentity? initialIdentity;
  final UserSemanticContext? initialSemanticContext;
  final HardwareVoiceController? hardwareVoiceController;
  final TargetPlatform? hardwareVoicePlatform;
  final SystemAssistantController? systemAssistantController;
  final TargetPlatform? systemAssistantPlatform;
  final VoiceOutputPolicyController? voiceOutputPolicyController;
  final TargetPlatform? voiceOutputPolicyPlatform;

  @override
  State<AccountScreen> createState() => _AccountScreenState();
}

class _AccountScreenState extends State<AccountScreen>
    with WidgetsBindingObserver {
  Connections? _connections;
  UserSettings? _settings;
  List<SourcePreference>? _sourcePreferences;
  String? _error;
  String? _sourcePreferencesError;
  bool _loading = false;
  bool _sourcePreferencesLoading = false;
  bool _googleOAuthPending = false;
  bool _telegramLinkPending = false;
  bool _teamsOAuthPending = false;
  bool _teamsDisconnectPending = false;
  bool _profileSaving = false;
  bool _settingsSaving = false;
  bool _identityLoading = false;
  bool _identitySaving = false;
  String? _identityError;
  bool _semanticLoading = false;
  bool _semanticSaving = false;
  String? _semanticError;
  final Set<String> _savingSources = {};
  final Map<String, String> _sourcePreferenceRowErrors = {};
  late final TextEditingController _displayNameController;
  late final TextEditingController _timezoneController;
  late final TextEditingController _identityController;
  late final TextEditingController _semanticController;
  late final TextEditingController _openaiDailyTokenLimitController;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _displayNameController = TextEditingController(
      text: widget.authController.user?.displayName ?? '',
    );
    _timezoneController = TextEditingController(
      text: widget.initialSettings?.timezone ?? '',
    );
    _identityController = TextEditingController(
      text: widget.initialIdentity?.profileText ?? '',
    );
    _semanticController = TextEditingController(
      text: widget.initialSemanticContext?.contextText ?? '',
    );
    _openaiDailyTokenLimitController = TextEditingController(
      text: widget.initialSettings?.openaiDailyTokenLimit?.toString() ?? '',
    );
    if (widget.initialConnections != null &&
        widget.initialSettings != null &&
        widget.initialSourcePreferences != null &&
        widget.initialIdentity != null &&
        widget.initialSemanticContext != null) {
      _connections = widget.initialConnections;
      _settings = widget.initialSettings;
      _sourcePreferences = widget.initialSourcePreferences;
      _loading = false;
      _sourcePreferencesLoading = false;
      _identityLoading = false;
      _semanticLoading = false;
    } else if (widget.initialConnections != null &&
        widget.initialSettings != null &&
        widget.initialSourcePreferences != null) {
      _connections = widget.initialConnections;
      _settings = widget.initialSettings;
      _sourcePreferences = widget.initialSourcePreferences;
      _loading = false;
      _sourcePreferencesLoading = false;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) {
          _loadIdentity();
          _loadSemanticContext();
        }
      });
    } else {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) {
          _loadAccountData();
        }
      });
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _displayNameController.dispose();
    _timezoneController.dispose();
    _identityController.dispose();
    _semanticController.dispose();
    _openaiDailyTokenLimitController.dispose();
    super.dispose();
  }

  bool _lifecyclePaused = false;

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused) {
      _lifecyclePaused = true;
      return;
    }
    if (state == AppLifecycleState.resumed && _lifecyclePaused) {
      _lifecyclePaused = false;
      _loadAccountData();
      widget.systemAssistantController?.refresh();
    }
  }

  Future<void> _loadIdentity() async {
    setState(() {
      _identityLoading = true;
      _identityError = null;
    });
    try {
      final identity = await widget.apiClient.getIdentity();
      if (mounted) {
        setState(() {
          _identityController.text = identity.profileText;
          _identityError = null;
        });
      }
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _identityError = e.message);
      }
    } finally {
      if (mounted) {
        setState(() => _identityLoading = false);
      }
    }
  }

  Future<void> _loadAccountData() async {
    setState(() {
      _loading = true;
      _sourcePreferencesLoading = true;
      _identityLoading = true;
      _semanticLoading = true;
      _error = null;
      _sourcePreferencesError = null;
      _identityError = null;
      _semanticError = null;
    });
    Connections? connections;
    UserSettings? settings;
    List<SourcePreference>? sourcePreferences;
    String? error;
    String? sourcePreferencesError;
    String? identityError;
    String? semanticError;
    try {
      connections = await widget.apiClient.getConnections();
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
      return;
    } on ApiException catch (e) {
      error = e.message;
    }
    try {
      settings = await widget.apiClient.getSettings();
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
      return;
    } on ApiException catch (e) {
      error ??= e.message;
    }
    try {
      sourcePreferences = await widget.apiClient.getSourcePreferences();
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
      return;
    } on ApiException catch (e) {
      sourcePreferencesError = e.message;
    }
    try {
      final identity = await widget.apiClient.getIdentity();
      _identityController.text = identity.profileText;
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
      return;
    } on ApiException catch (e) {
      identityError = e.message;
    }
    try {
      final semantic = await widget.apiClient.getSemanticContext();
      _semanticController.text = semantic.contextText;
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
      return;
    } on ApiException catch (e) {
      semanticError = e.message;
    }
    if (mounted) {
      setState(() {
        _connections = connections;
        _settings = settings;
        _sourcePreferences = sourcePreferences;
        if (settings != null) {
          _timezoneController.text = settings.timezone;
          _openaiDailyTokenLimitController.text =
              settings.openaiDailyTokenLimit?.toString() ?? '';
        }
        _error = error;
        _sourcePreferencesError = sourcePreferencesError;
        _identityError = identityError;
        _semanticError = semanticError;
        _loading = false;
        _sourcePreferencesLoading = false;
        _identityLoading = false;
        _semanticLoading = false;
      });
    }
  }

  Future<void> _patchSourcePreference(
    String source,
    Future<SourcePreference> request,
  ) async {
    if (_savingSources.contains(source)) {
      return;
    }
    setState(() {
      _savingSources.add(source);
      _sourcePreferenceRowErrors.remove(source);
    });
    try {
      final updated = await request;
      if (mounted) {
        setState(() {
          _sourcePreferences = [
            for (final preference in _sourcePreferences ?? const [])
              preference.source == updated.source ? updated : preference,
          ];
        });
      }
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _sourcePreferenceRowErrors[source] = e.message);
      }
    } finally {
      if (mounted) {
        setState(() => _savingSources.remove(source));
      }
    }
  }

  Future<void> _toggleSourceEnabled(String source, bool enabled) async {
    await _patchSourcePreference(
      source,
      widget.apiClient.patchSourceEnabled(source, enabled),
    );
  }

  Future<void> _changeSourceCadence(String source, int seconds) async {
    await _patchSourcePreference(
      source,
      widget.apiClient.patchSourceSyncInterval(source, seconds),
    );
  }

  Future<void> _changeSourceHistory(String source, int days) async {
    await _patchSourcePreference(
      source,
      widget.apiClient.patchSourceHistoryDays(source, days),
    );
  }

  Future<void> _resetSourcePreference(String source) async {
    await _patchSourcePreference(
      source,
      widget.apiClient.resetSourcePreference(source),
    );
  }

  Future<void> _saveProfile() async {
    if (_profileSaving) {
      return;
    }
    setState(() => _profileSaving = true);
    try {
      await widget.apiClient.patchMe(
        displayName: _displayNameController.text.trim(),
      );
      await widget.authController.refreshUser();
      if (mounted) {
        setState(() => _error = null);
      }
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _error = e.message);
      }
    } finally {
      if (mounted) {
        setState(() => _profileSaving = false);
      }
    }
  }

  Future<void> _saveIdentity() async {
    if (_identitySaving) {
      return;
    }
    setState(() {
      _identitySaving = true;
      _identityError = null;
    });
    try {
      final updated = await widget.apiClient.putIdentity(
        profileText: _identityController.text,
      );
      if (mounted) {
        setState(() {
          _identityController.text = updated.profileText;
          _identityError = null;
        });
      }
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _identityError = e.message);
      }
    } finally {
      if (mounted) {
        setState(() => _identitySaving = false);
      }
    }
  }

  Future<void> _loadSemanticContext() async {
    setState(() {
      _semanticLoading = true;
      _semanticError = null;
    });
    try {
      final semantic = await widget.apiClient.getSemanticContext();
      if (mounted) {
        setState(() {
          _semanticController.text = semantic.contextText;
          _semanticError = null;
        });
      }
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _semanticError = e.message);
      }
    } finally {
      if (mounted) {
        setState(() => _semanticLoading = false);
      }
    }
  }

  Future<void> _saveSemanticContext() async {
    if (_semanticSaving) {
      return;
    }
    setState(() {
      _semanticSaving = true;
      _semanticError = null;
    });
    try {
      final updated = await widget.apiClient.putSemanticContext(
        contextText: _semanticController.text,
      );
      if (mounted) {
        setState(() {
          _semanticController.text = updated.contextText;
          _semanticError = null;
        });
      }
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _semanticError = e.message);
      }
    } finally {
      if (mounted) {
        setState(() => _semanticSaving = false);
      }
    }
  }

  Future<void> _saveTimezone() async {
    if (_settingsSaving || _settings == null) {
      return;
    }
    setState(() => _settingsSaving = true);
    try {
      final updated = await widget.apiClient.patchSettings(
        timezone: _timezoneController.text.trim(),
      );
      if (mounted) {
        setState(() {
          _settings = updated;
          _error = null;
        });
      }
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _error = e.message);
      }
    } finally {
      if (mounted) {
        setState(() => _settingsSaving = false);
      }
    }
  }

  Future<void> _saveAiPreferences({
    String? assistantModel,
    String? assistantReasoningEffort,
    String? assistantVerbosity,
    int? assistantMaxRounds,
    bool patchAssistantMaxRounds = false,
  }) async {
    if (_settingsSaving) {
      return;
    }
    setState(() => _settingsSaving = true);
    try {
      final updated = await widget.apiClient.patchSettings(
        assistantModel: assistantModel,
        assistantReasoningEffort: assistantReasoningEffort,
        assistantVerbosity: assistantVerbosity,
        assistantMaxRounds: assistantMaxRounds,
        patchAssistantMaxRounds: patchAssistantMaxRounds,
      );
      if (mounted) {
        setState(() {
          _settings = updated;
          _error = null;
        });
      }
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _error = e.message);
      }
    } finally {
      if (mounted) {
        setState(() => _settingsSaving = false);
      }
    }
  }

  Future<void> _saveAutoLabelEnabled(bool enabled) async {
    if (_settingsSaving) {
      return;
    }
    setState(() => _settingsSaving = true);
    try {
      final updated = await widget.apiClient.patchSettings(
        autoLabelEnabled: enabled,
      );
      if (mounted) {
        setState(() {
          _settings = updated;
          _error = null;
        });
      }
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _error = e.message);
      }
    } finally {
      if (mounted) {
        setState(() => _settingsSaving = false);
      }
    }
  }

  Future<void> _saveOpenaiDailyTokenLimit() async {
    if (_settingsSaving || _settings == null) {
      return;
    }
    final raw = _openaiDailyTokenLimitController.text.trim();
    int? limit;
    if (raw.isNotEmpty) {
      limit = int.tryParse(raw.replaceAll(RegExp(r'[\s\u00a0]'), ''));
      if (limit == null || limit < _settings!.minOpenaiDailyTokenLimit) {
        setState(() {
          _error =
              'Дневной лимит OpenAI должен быть положительным числом '
              'или пустым значением.';
        });
        return;
      }
    }
    setState(() {
      _settingsSaving = true;
      _error = null;
    });
    try {
      final updated = await widget.apiClient.patchSettings(
        openaiDailyTokenLimit: limit,
        patchOpenaiDailyTokenLimit: true,
      );
      if (mounted) {
        setState(() {
          _settings = updated;
          _openaiDailyTokenLimitController.text =
              updated.openaiDailyTokenLimit?.toString() ?? '';
          _error = null;
        });
      }
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _error = e.message);
      }
    } finally {
      if (mounted) {
        setState(() => _settingsSaving = false);
      }
    }
  }

  Future<void> _showOpenAiKeyDialog({required bool replace}) async {
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => _OpenAiKeyDialog(
        apiClient: widget.apiClient,
        authController: widget.authController,
        replace: replace,
        onUpdated: _loadAccountData,
      ),
    );
  }

  Future<void> _deleteOpenAiKey() async {
    try {
      await widget.apiClient.deleteOpenaiCredential();
      await _loadAccountData();
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _error = e.message);
      }
    }
  }

  Future<void> _startGoogleOAuth() async {
    if (_googleOAuthPending) {
      return;
    }
    setState(() => _googleOAuthPending = true);
    try {
      final result = await widget.apiClient.getGoogleAuthorizationUrl();
      final uri = Uri.tryParse(result.authorizationUrl);
      if (uri == null) {
        throw ServerException('Не удалось открыть страницу авторизации Google');
      }
      final launched = await url_launcher.launchUrl(
        uri,
        mode: url_launcher.LaunchMode.externalApplication,
      );
      if (!launched && mounted) {
        setState(
          () => _error = 'Не удалось открыть браузер для авторизации Google',
        );
      }
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _error = e.message);
      }
    } finally {
      if (mounted) {
        setState(() => _googleOAuthPending = false);
      }
    }
  }

  Future<void> _startTeamsOAuth() async {
    if (_teamsOAuthPending || _teamsDisconnectPending) {
      return;
    }
    setState(() => _teamsOAuthPending = true);
    try {
      final result = await widget.apiClient.getTeamsAuthorizationUrl();
      final uri = Uri.tryParse(result.authorizationUrl);
      if (uri == null) {
        throw ServerException(
          'Не удалось открыть страницу авторизации Microsoft Teams',
        );
      }
      final launched = await url_launcher.launchUrl(
        uri,
        mode: url_launcher.LaunchMode.externalApplication,
      );
      if (!launched && mounted) {
        setState(
          () => _error =
              'Не удалось открыть браузер для авторизации Microsoft Teams',
        );
      }
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _error = e.message);
      }
    } finally {
      if (mounted) {
        setState(() => _teamsOAuthPending = false);
      }
    }
  }

  Future<void> _disconnectTeams() async {
    if (_teamsDisconnectPending || _teamsOAuthPending) {
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => _TeamsDisconnectDialog(
        onCancel: () => Navigator.of(dialogContext).pop(false),
        onConfirm: () => Navigator.of(dialogContext).pop(true),
      ),
    );
    if (confirmed != true || !mounted) {
      return;
    }
    setState(() => _teamsDisconnectPending = true);
    try {
      await widget.apiClient.disconnectTeams();
      await _loadAccountData();
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _error = e.message);
      }
    } finally {
      if (mounted) {
        setState(() => _teamsDisconnectPending = false);
      }
    }
  }

  Future<void> _showConnectMattermostDialog() async {
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => _MattermostConnectDialog(
        apiClient: widget.apiClient,
        authController: widget.authController,
        onConnected: _loadAccountData,
      ),
    );
  }

  Future<void> _startTelegramLink() async {
    if (_telegramLinkPending) {
      return;
    }
    setState(() => _telegramLinkPending = true);
    try {
      final result = await widget.apiClient.linkTelegram();
      final uri = Uri.tryParse(result.telegramUrl);
      if (uri == null) {
        throw ServerException('Не удалось открыть ссылку Telegram');
      }
      final launched = await url_launcher.launchUrl(
        uri,
        mode: url_launcher.LaunchMode.externalApplication,
      );
      if (!launched && mounted) {
        setState(() => _error = 'Не удалось открыть Telegram');
      }
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _error = e.message);
      }
    } finally {
      if (mounted) {
        setState(() => _telegramLinkPending = false);
      }
    }
  }

  Future<void> _showConnectYandexDialog() async {
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => _YandexConnectDialog(
        apiClient: widget.apiClient,
        authController: widget.authController,
        onConnected: _loadAccountData,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final settings = _settings;

    return Scaffold(
      appBar: AppBar(title: const Text('Аккаунт')),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: accountContentMaxWidth),
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              AccountSectionCard(
                title: 'Профиль',
                children: [
                  Wrap(
                    spacing: 16,
                    runSpacing: 12,
                    children: [
                      SizedBox(
                        width: 320,
                        child: TextField(
                          controller: _displayNameController,
                          decoration: const InputDecoration(
                            labelText: 'Отображаемое имя',
                          ),
                        ),
                      ),
                      SizedBox(
                        width: 320,
                        child: TextField(
                          controller: _timezoneController,
                          decoration: const InputDecoration(
                            labelText: 'Часовой пояс (IANA)',
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      FilledButton(
                        onPressed: _profileSaving ? null : _saveProfile,
                        child: Text(
                          _profileSaving ? 'Сохранение…' : 'Сохранить имя',
                        ),
                      ),
                      OutlinedButton(
                        onPressed: _settingsSaving ? null : _saveTimezone,
                        child: Text(
                          _settingsSaving
                              ? 'Сохранение…'
                              : 'Сохранить часовой пояс',
                        ),
                      ),
                    ],
                  ),
                ],
              ),
              if (widget.systemAssistantController != null &&
                  systemAssistantSettingsVisible(
                    platform: widget.systemAssistantPlatform,
                  )) ...[
                const SizedBox(height: 16),
                SystemAssistantAccountSection(
                  controller: widget.systemAssistantController!,
                  platform: widget.systemAssistantPlatform,
                ),
              ],
              const SizedBox(height: 16),
              _InterfaceScaleCard(),
              const SizedBox(height: 16),
              AccountSectionCard(
                title: 'Моя идентичность',
                children: [
                  Text(
                    identityProfileExplanation,
                    style: Theme.of(context).textTheme.bodyMedium,
                  ),
                  const SizedBox(height: 12),
                  if (_identityLoading)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: 16),
                      child: Center(child: CircularProgressIndicator()),
                    )
                  else
                    TextField(
                      key: const Key('identity_profile_text'),
                      controller: _identityController,
                      decoration: InputDecoration(
                        labelText: 'Профиль идентичности',
                        hintText: identityProfileTemplateExample,
                        alignLabelWithHint: true,
                      ),
                      minLines: 8,
                      maxLines: 18,
                      enabled: !_identitySaving,
                    ),
                  if (_identityError != null) ...[
                    const SizedBox(height: 8),
                    Text(
                      _identityError!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                  ],
                  const SizedBox(height: 12),
                  FilledButton(
                    onPressed: _identitySaving || _identityLoading
                        ? null
                        : _saveIdentity,
                    child: Text(
                      _identitySaving
                          ? 'Сохранение…'
                          : 'Сохранить идентичность',
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              AccountSectionCard(
                key: const Key('account_semantic_context_section'),
                title: 'Контекст для Секретаря',
                children: [
                  Text(
                    semanticContextExplanation,
                    style: Theme.of(context).textTheme.bodyMedium,
                  ),
                  const SizedBox(height: 12),
                  if (_semanticLoading)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: 16),
                      child: Center(child: CircularProgressIndicator()),
                    )
                  else
                    TextField(
                      key: const Key('semantic_context_text'),
                      controller: _semanticController,
                      decoration: const InputDecoration(
                        labelText: 'Контекст',
                        hintText: semanticContextPlaceholder,
                        alignLabelWithHint: true,
                      ),
                      minLines: 8,
                      maxLines: 18,
                      enabled: !_semanticSaving,
                    ),
                  if (_semanticError != null) ...[
                    const SizedBox(height: 8),
                    Text(
                      _semanticError!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                  ],
                  const SizedBox(height: 12),
                  FilledButton(
                    key: const Key('semantic_context_save'),
                    onPressed: _semanticSaving || _semanticLoading
                        ? null
                        : _saveSemanticContext,
                    child: Text(
                      _semanticSaving ? 'Сохранение…' : 'Сохранить контекст',
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              AccountSectionCard(
                title: 'ИИ',
                children: [
                  if (settings != null) ...[
                    Text(
                      settings.openaiKeyConfigured
                          ? 'OpenAI API key: настроен'
                          : 'OpenAI API key: не настроен',
                    ),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        if (!settings.openaiKeyConfigured)
                          OutlinedButton(
                            onPressed: () =>
                                _showOpenAiKeyDialog(replace: false),
                            child: const Text('Установить ключ'),
                          ),
                        if (settings.openaiKeyConfigured)
                          OutlinedButton(
                            onPressed: () =>
                                _showOpenAiKeyDialog(replace: true),
                            child: const Text('Заменить ключ'),
                          ),
                        if (settings.openaiKeyConfigured)
                          OutlinedButton(
                            onPressed: _deleteOpenAiKey,
                            child: const Text('Удалить ключ'),
                          ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Wrap(
                      spacing: 16,
                      runSpacing: 12,
                      children: [
                        AccountLabeledControl(
                          label: 'Модель Assistant',
                          child: DropdownButton<String>(
                            value: _dropdownAssistantModel(settings),
                            items: settings.allowedAssistantModels
                                .map(
                                  (model) => DropdownMenuItem(
                                    value: model,
                                    child: Text(model),
                                  ),
                                )
                                .toList(),
                            onChanged: _settingsSaving
                                ? null
                                : (value) {
                                    if (value != null) {
                                      _saveAiPreferences(assistantModel: value);
                                    }
                                  },
                          ),
                        ),
                        AccountLabeledControl(
                          label: 'Reasoning effort',
                          child: DropdownButton<String>(
                            value: _dropdownReasoningEffort(settings),
                            items: const [
                              DropdownMenuItem(
                                value: 'none',
                                child: Text('none'),
                              ),
                              DropdownMenuItem(
                                value: 'low',
                                child: Text('low'),
                              ),
                              DropdownMenuItem(
                                value: 'medium',
                                child: Text('medium'),
                              ),
                              DropdownMenuItem(
                                value: 'high',
                                child: Text('high'),
                              ),
                            ],
                            onChanged: _settingsSaving
                                ? null
                                : (value) {
                                    if (value != null) {
                                      _saveAiPreferences(
                                        assistantReasoningEffort: value,
                                      );
                                    }
                                  },
                          ),
                        ),
                        AccountLabeledControl(
                          label: 'Verbosity',
                          child: DropdownButton<String>(
                            value: _dropdownVerbosity(settings),
                            items: const [
                              DropdownMenuItem(
                                value: 'low',
                                child: Text('low'),
                              ),
                              DropdownMenuItem(
                                value: 'medium',
                                child: Text('medium'),
                              ),
                              DropdownMenuItem(
                                value: 'high',
                                child: Text('high'),
                              ),
                            ],
                            onChanged: _settingsSaving
                                ? null
                                : (value) {
                                    if (value != null) {
                                      _saveAiPreferences(
                                        assistantVerbosity: value,
                                      );
                                    }
                                  },
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    AccountLabeledControl(
                      label: 'Максимум шагов Секретаря',
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          DropdownButton<String>(
                            value: _dropdownAssistantMaxRounds(settings),
                            items: [
                              DropdownMenuItem(
                                value: _assistantMaxRoundsDefaultValue,
                                child: Text(
                                  'По умолчанию (${settings.defaultAssistantMaxRounds})',
                                ),
                              ),
                              for (
                                var value = settings.minAssistantMaxRounds;
                                value <= settings.maxAssistantMaxRounds;
                                value++
                              )
                                DropdownMenuItem(
                                  value: value.toString(),
                                  child: Text(value.toString()),
                                ),
                            ],
                            onChanged: _settingsSaving
                                ? null
                                : (value) {
                                    if (value == null) {
                                      return;
                                    }
                                    if (value ==
                                        _assistantMaxRoundsDefaultValue) {
                                      _saveAiPreferences(
                                        patchAssistantMaxRounds: true,
                                      );
                                      return;
                                    }
                                    final parsed = int.tryParse(value);
                                    if (parsed != null) {
                                      _saveAiPreferences(
                                        assistantMaxRounds: parsed,
                                        patchAssistantMaxRounds: true,
                                      );
                                    }
                                  },
                          ),
                          const SizedBox(height: 4),
                          Text(
                            'Больше шагов — более глубокий поиск, но выше время ответа и расход токенов.',
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),
                    SwitchListTile(
                      key: const Key('account_auto_label_toggle'),
                      contentPadding: EdgeInsets.zero,
                      title: const Text('Автоматические метки'),
                      subtitle: const Text(
                        'Секретарь может автоматически добавлять только уже существующие '
                        'метки к новым и изменённым объектам. Новые метки не создаются.',
                      ),
                      value: settings.autoLabelEnabled,
                      onChanged: _settingsSaving
                          ? null
                          : (value) => _saveAutoLabelEnabled(value),
                    ),
                    const SizedBox(height: 16),
                    _OpenAiDailyBudgetControl(
                      settings: settings,
                      controller: _openaiDailyTokenLimitController,
                      saving: _settingsSaving,
                      onSave: _saveOpenaiDailyTokenLimit,
                    ),
                  ],
                ],
              ),
              if (widget.hardwareVoiceController != null &&
                  hardwareVoiceSettingsVisible(
                    platform: widget.hardwareVoicePlatform,
                  )) ...[
                const SizedBox(height: 16),
                HardwareVoiceAccountSection(
                  controller: widget.hardwareVoiceController!,
                  platform: widget.hardwareVoicePlatform,
                ),
              ],
              if (widget.voiceOutputPolicyController != null &&
                  voiceOutputPolicySettingsVisible(
                    platform: widget.voiceOutputPolicyPlatform,
                  )) ...[
                const SizedBox(height: 16),
                VoiceOutputPolicyAccountSection(
                  controller: widget.voiceOutputPolicyController!,
                  platform: widget.voiceOutputPolicyPlatform,
                ),
              ],
              const SizedBox(height: 16),
              AccountSectionCard(
                title: 'Подключения',
                children: [
                  if (_error != null)
                    Text(
                      _error!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                  if (_loading)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: 16),
                      child: Center(child: CircularProgressIndicator()),
                    )
                  else if (_connections != null)
                    _ConnectionsList(
                      connections: _connections!,
                      googleOAuthPending: _googleOAuthPending,
                      telegramLinkPending: _telegramLinkPending,
                      teamsOAuthPending: _teamsOAuthPending,
                      teamsDisconnectPending: _teamsDisconnectPending,
                      onConnectGoogle: _startGoogleOAuth,
                      onConnectYandex: _showConnectYandexDialog,
                      onConnectMattermost: _showConnectMattermostDialog,
                      onConnectTelegram: _startTelegramLink,
                      onConnectTeams: _startTeamsOAuth,
                      onDisconnectTeams: _disconnectTeams,
                    ),
                ],
              ),
              const SizedBox(height: 16),
              TelegramMtprotoAccountSection(
                apiClient: widget.apiClient,
                authController: widget.authController,
              ),
              const SizedBox(height: 16),
              AccountSectionCard(
                title: 'Синхронизация',
                children: [
                  if (_sourcePreferencesError != null)
                    Text(
                      _sourcePreferencesError!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                  if (_sourcePreferencesLoading)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: 16),
                      child: Center(child: CircularProgressIndicator()),
                    )
                  else if (_sourcePreferences != null &&
                      _connections != null) ...[
                    Text(
                      'Изменение глубины истории применяется постепенно при синхронизации.',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: 12),
                    SourcePreferencesList(
                      preferences: _sourcePreferences!,
                      connections: _connections!,
                      savingSources: _savingSources,
                      rowErrors: _sourcePreferenceRowErrors,
                      onToggleEnabled: _toggleSourceEnabled,
                      onCadenceChanged: _changeSourceCadence,
                      onHistoryChanged: _changeSourceHistory,
                      onReset: _resetSourcePreference,
                    ),
                  ],
                ],
              ),
              const SizedBox(height: 16),
              AccountLabelsSection(
                key: const Key('account_labels_section'),
                apiClient: widget.apiClient,
                authController: widget.authController,
              ),
              const SizedBox(height: 32),
              ClientDisconnectControl(authController: widget.authController),
            ],
          ),
        ),
      ),
    );
  }
}

String _dropdownAssistantModel(UserSettings settings) {
  if (settings.allowedAssistantModels.contains(settings.assistantModel)) {
    return settings.assistantModel;
  }
  if (settings.allowedAssistantModels.isNotEmpty) {
    return settings.allowedAssistantModels.first;
  }
  return settings.assistantModel;
}

String _dropdownReasoningEffort(UserSettings settings) {
  const allowed = ['none', 'low', 'medium', 'high'];
  if (allowed.contains(settings.assistantReasoningEffort)) {
    return settings.assistantReasoningEffort;
  }
  return 'low';
}

String _dropdownVerbosity(UserSettings settings) {
  const allowed = ['low', 'medium', 'high'];
  if (allowed.contains(settings.assistantVerbosity)) {
    return settings.assistantVerbosity;
  }
  return 'low';
}

const _assistantMaxRoundsDefaultValue = '__default__';

String _dropdownAssistantMaxRounds(UserSettings settings) {
  if (settings.assistantMaxRoundsOverride == null) {
    return _assistantMaxRoundsDefaultValue;
  }
  return settings.assistantMaxRoundsOverride.toString();
}

String googleOAuthButtonLabel(GoogleConnection google) {
  if (!google.connected) {
    return 'Подключить Google';
  }
  if (!google.driveAvailable) {
    return 'Разрешить Google Drive';
  }
  return 'Переподключить Google';
}

String yandexConnectButtonLabel(Connections connections) {
  if (!connections.yandexMail.connected &&
      !connections.yandexCalendar.connected) {
    return 'Подключить Яндекс';
  }
  return 'Обновить данные Яндекса';
}

class _ConnectionsList extends StatelessWidget {
  const _ConnectionsList({
    required this.connections,
    required this.googleOAuthPending,
    required this.telegramLinkPending,
    required this.teamsOAuthPending,
    required this.teamsDisconnectPending,
    required this.onConnectGoogle,
    required this.onConnectYandex,
    required this.onConnectMattermost,
    required this.onConnectTelegram,
    required this.onConnectTeams,
    required this.onDisconnectTeams,
  });

  final Connections connections;
  final bool googleOAuthPending;
  final bool telegramLinkPending;
  final bool teamsOAuthPending;
  final bool teamsDisconnectPending;
  final VoidCallback onConnectGoogle;
  final VoidCallback onConnectYandex;
  final VoidCallback onConnectMattermost;
  final VoidCallback onConnectTelegram;
  final VoidCallback onConnectTeams;
  final VoidCallback onDisconnectTeams;

  @override
  Widget build(BuildContext context) {
    final google = connections.google;
    final sectionTitle = Theme.of(context).textTheme.titleSmall;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Google', style: sectionTitle),
        const SizedBox(height: 4),
        _ConnectionRow(
          label: 'Google',
          connected: google.connected,
          detail: google.email,
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 12,
          runSpacing: 4,
          children: [
            _ConnectionRow(
              label: 'Gmail доступен',
              connected: google.gmailAvailable,
            ),
            _ConnectionRow(
              label: 'Google Календарь доступен',
              connected: google.calendarAvailable,
            ),
            _ConnectionRow(
              label: 'Google Drive доступен',
              connected: google.driveAvailable,
            ),
          ],
        ),
        const SizedBox(height: 8),
        OutlinedButton(
          onPressed: googleOAuthPending ? null : onConnectGoogle,
          child: Text(googleOAuthButtonLabel(google)),
        ),
        const Divider(height: 24),
        Text('Яндекс', style: sectionTitle),
        const SizedBox(height: 4),
        _ConnectionRow(
          label: 'Яндекс Почта',
          connected: connections.yandexMail.connected,
          detail: connections.yandexMail.email,
        ),
        _ConnectionRow(
          label: 'Яндекс Календарь',
          connected: connections.yandexCalendar.connected,
          detail: connections.yandexCalendar.email,
        ),
        const SizedBox(height: 8),
        OutlinedButton(
          onPressed: onConnectYandex,
          child: Text(yandexConnectButtonLabel(connections)),
        ),
        const Divider(height: 24),
        Text('Mattermost', style: sectionTitle),
        const SizedBox(height: 4),
        for (final account in connections.mattermost)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Text(mattermostConnectionLabel(account)),
          ),
        const SizedBox(height: 8),
        OutlinedButton(
          onPressed: onConnectMattermost,
          child: const Text('Подключить Mattermost'),
        ),
        const Divider(height: 24),
        Text('Telegram', style: sectionTitle),
        const SizedBox(height: 4),
        _ConnectionRow(
          label: telegramConnectionLabel(connections.telegram),
          connected:
              connections.telegram.configured &&
              connections.telegram.identityLinked &&
              connections.telegram.businessConnected,
          detail: telegramConnectionDetail(connections.telegram),
        ),
        const SizedBox(height: 8),
        Text(
          telegramSetupHelpText(connections.telegram),
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: 8),
        if (connections.telegram.configured)
          OutlinedButton(
            key: const Key('telegram_connect_button'),
            onPressed: telegramLinkPending ? null : onConnectTelegram,
            child: const Text('Подключить Telegram'),
          )
        else
          Text(
            'Telegram не настроен на сервере.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        const Divider(height: 24),
        Text('Microsoft Teams', style: sectionTitle),
        const SizedBox(height: 4),
        _ConnectionRow(
          label: teamsConnectionLabel(connections.teams),
          connected: connections.teams.connected,
          detail: teamsConnectionDetail(connections.teams),
        ),
        const SizedBox(height: 8),
        Text(
          teamsSetupHelpText(connections.teams),
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: 8),
        if (connections.teams.configured)
          Wrap(
            spacing: 12,
            runSpacing: 8,
            children: [
              OutlinedButton(
                key: const Key('teams_connect_button'),
                onPressed: teamsOAuthPending || teamsDisconnectPending
                    ? null
                    : onConnectTeams,
                child: Text(teamsConnectButtonLabel(connections.teams)),
              ),
              if (connections.teams.connected)
                OutlinedButton(
                  key: const Key('teams_disconnect_button'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: Theme.of(context).colorScheme.error,
                    side: BorderSide(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                  onPressed: teamsOAuthPending || teamsDisconnectPending
                      ? null
                      : onDisconnectTeams,
                  child: const Text('Отключить Microsoft Teams'),
                ),
            ],
          )
        else
          Text(
            'Microsoft Teams не настроен на сервере.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
      ],
    );
  }
}

String mattermostConnectionLabel(MattermostConnection account) {
  final displayName = account.displayName?.trim();
  final name = displayName != null && displayName.isNotEmpty
      ? displayName
      : account.username;
  final host = account.serverUrl.replaceFirst(RegExp(r'^https?://'), '');
  return 'Mattermost: $name @ $host';
}

String telegramConnectionLabel(TelegramConnection telegram) {
  if (!telegram.configured) {
    return 'Telegram не настроен на сервере';
  }
  if (!telegram.identityLinked) {
    return 'Telegram: аккаунт не связан';
  }
  if (!telegram.businessConnected) {
    return 'Telegram: связан, Secretary Mode не подключён';
  }
  if (!telegram.canReply) {
    return 'Telegram: подключён, без права ответа';
  }
  return 'Telegram: подключён, можно отвечать';
}

String? telegramConnectionDetail(TelegramConnection telegram) {
  final displayName = telegram.displayName?.trim();
  if (displayName != null && displayName.isNotEmpty) {
    return displayName;
  }
  final username = telegram.telegramUsername?.trim();
  if (username != null && username.isNotEmpty) {
    return '@$username';
  }
  return telegram.botUsername;
}

String telegramSetupHelpText(TelegramConnection telegram) {
  return 'Сначала нажмите «Подключить Telegram» и Start в боте. '
      'Затем подключите этого бота к аккаунту в режиме Секретаря/Business Bot. '
      'Разрешите только нужные личные чаты и право ответа, если нужно отправлять сообщения. '
      'Секретарь получает только чаты, разрешённые ему в Telegram. '
      'Обычный mute Telegram сам по себе не является фильтром.';
}

String teamsConnectionLabel(TeamsConnection teams) {
  if (!teams.configured) {
    return 'Microsoft Teams не настроен на сервере';
  }
  if (!teams.connected) {
    return 'Microsoft Teams: аккаунт не подключён';
  }
  if (teams.reconnectRequired) {
    return 'Microsoft Teams: требуется повторное подключение';
  }
  return 'Microsoft Teams: подключён';
}

String? teamsConnectionDetail(TeamsConnection teams) {
  final displayName = teams.displayName?.trim();
  final upn = teams.upn?.trim();
  if (displayName != null && displayName.isNotEmpty) {
    return displayName;
  }
  if (upn != null && upn.isNotEmpty) {
    return upn;
  }
  return teams.tenantId;
}

String teamsSetupHelpText(TeamsConnection teams) {
  if (teams.reconnectRequired) {
    return 'Microsoft отозвал доступ. Переподключите тот же рабочий или учебный аккаунт. '
        'Уже сохранённые сообщения Teams не удаляются.';
  }
  return 'Подключите рабочий или учебный аккаунт Microsoft. '
      'Личные (consumer) аккаунты Microsoft не поддерживаются. '
      'Секретарь синхронизирует только личные и групповые чаты Teams, не каналы.';
}

String teamsConnectButtonLabel(TeamsConnection teams) {
  if (teams.connected) {
    return 'Переподключить Microsoft Teams';
  }
  return 'Подключить Microsoft Teams';
}

class _TeamsDisconnectDialog extends StatelessWidget {
  const _TeamsDisconnectDialog({
    required this.onCancel,
    required this.onConfirm,
  });

  final VoidCallback onCancel;
  final VoidCallback onConfirm;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return AlertDialog(
      key: const Key('teams_disconnect_dialog'),
      title: const Text('Отключить Microsoft Teams?'),
      content: const Text(
        'Локальные учётные данные Teams будут удалены, повторная синхронизация остановится. '
        'Уже сохранённые сообщения останутся. '
        'Это не удаляет данные в Microsoft Teams.',
      ),
      actions: [
        TextButton(
          key: const Key('teams_disconnect_cancel'),
          onPressed: onCancel,
          child: const Text('Отмена'),
        ),
        OutlinedButton(
          key: const Key('teams_disconnect_confirm'),
          style: OutlinedButton.styleFrom(
            foregroundColor: scheme.error,
            side: BorderSide(color: scheme.error),
          ),
          onPressed: onConfirm,
          child: const Text('Отключить'),
        ),
      ],
    );
  }
}

class _YandexConnectDialog extends StatefulWidget {
  const _YandexConnectDialog({
    required this.apiClient,
    required this.authController,
    required this.onConnected,
  });

  final SecretaryApiClient apiClient;
  final AuthController authController;
  final Future<void> Function() onConnected;

  @override
  State<_YandexConnectDialog> createState() => _YandexConnectDialogState();
}

class _YandexConnectDialogState extends State<_YandexConnectDialog> {
  final _emailController = TextEditingController();
  final _mailPasswordController = TextEditingController();
  final _calendarPasswordController = TextEditingController();
  bool _connectMail = true;
  bool _connectCalendar = true;
  bool _submitting = false;
  String? _error;

  @override
  void dispose() {
    _emailController.dispose();
    _mailPasswordController.dispose();
    _calendarPasswordController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_submitting) {
      return;
    }
    final email = _emailController.text.trim();
    final mailPassword = _mailPasswordController.text.trim();
    final calendarPassword = _calendarPasswordController.text.trim();
    if (email.isEmpty) {
      setState(() {
        _error = 'Укажите email';
      });
      return;
    }
    if (!_connectMail && !_connectCalendar) {
      setState(() {
        _error = 'Выберите хотя бы один сервис';
      });
      return;
    }
    if (_connectMail && mailPassword.isEmpty) {
      setState(() {
        _error = 'Укажите пароль приложения для Яндекс Почты';
      });
      return;
    }
    if (_connectCalendar && calendarPassword.isEmpty) {
      setState(() {
        _error = 'Укажите пароль приложения для Яндекс Календаря';
      });
      return;
    }

    setState(() {
      _submitting = true;
      _error = null;
    });

    final errors = <String>[];

    if (_connectMail) {
      try {
        await widget.apiClient.connectYandexMail(
          email: email,
          appPassword: mailPassword,
        );
      } on AuthenticationException {
        widget.authController.handleAuthenticationFailure();
        if (mounted) {
          Navigator.of(context).pop();
        }
        return;
      } on ApiException catch (e) {
        errors.add('Не удалось подключить Яндекс Почту: ${e.message}');
      }
    }

    if (_connectCalendar) {
      try {
        await widget.apiClient.connectYandexCalendar(
          email: email,
          appPassword: calendarPassword,
        );
      } on AuthenticationException {
        widget.authController.handleAuthenticationFailure();
        if (mounted) {
          Navigator.of(context).pop();
        }
        return;
      } on ApiException catch (e) {
        errors.add('Не удалось подключить Яндекс Календарь: ${e.message}');
      }
    }

    _mailPasswordController.clear();
    _calendarPasswordController.clear();
    await widget.onConnected();

    if (!mounted) {
      return;
    }

    if (errors.isEmpty) {
      Navigator.of(context).pop();
      return;
    }

    setState(() {
      _error = errors.join('\n');
      _submitting = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Подключить Яндекс'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextField(
              controller: _emailController,
              decoration: const InputDecoration(
                labelText: 'Email',
                hintText: 'user@yandex.ru',
              ),
              enabled: !_submitting,
              keyboardType: TextInputType.emailAddress,
              textInputAction: TextInputAction.next,
              autocorrect: false,
            ),
            const SizedBox(height: 8),
            Text(
              'Яндекс Почта и Календарь используют разные пароли приложения.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 12),
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Яндекс Почта'),
              value: _connectMail,
              onChanged: _submitting
                  ? null
                  : (value) => setState(() => _connectMail = value ?? false),
            ),
            if (_connectMail) ...[
              TextField(
                key: const Key('yandex_mail_app_password'),
                controller: _mailPasswordController,
                decoration: const InputDecoration(
                  labelText: 'Пароль приложения — Почта',
                ),
                enabled: !_submitting,
                obscureText: true,
                autocorrect: false,
                enableSuggestions: false,
                textInputAction: TextInputAction.next,
              ),
              const SizedBox(height: 8),
            ],
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Яндекс Календарь'),
              value: _connectCalendar,
              onChanged: _submitting
                  ? null
                  : (value) =>
                        setState(() => _connectCalendar = value ?? false),
            ),
            if (_connectCalendar) ...[
              TextField(
                key: const Key('yandex_calendar_app_password'),
                controller: _calendarPasswordController,
                decoration: const InputDecoration(
                  labelText: 'Пароль приложения — Календарь',
                ),
                enabled: !_submitting,
                obscureText: true,
                autocorrect: false,
                enableSuggestions: false,
                textInputAction: TextInputAction.done,
                onSubmitted: (_) => _submit(),
              ),
            ],
            if (_submitting) ...[
              const SizedBox(height: 16),
              const Center(
                child: SizedBox(
                  width: 24,
                  height: 24,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              ),
            ],
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _submitting ? null : () => Navigator.of(context).pop(),
          child: const Text('Отмена'),
        ),
        FilledButton(
          onPressed: _submitting ? null : _submit,
          child: const Text('Подключить'),
        ),
      ],
    );
  }
}

class _MattermostConnectDialog extends StatefulWidget {
  const _MattermostConnectDialog({
    required this.apiClient,
    required this.authController,
    required this.onConnected,
  });

  final SecretaryApiClient apiClient;
  final AuthController authController;
  final Future<void> Function() onConnected;

  @override
  State<_MattermostConnectDialog> createState() =>
      _MattermostConnectDialogState();
}

class _MattermostConnectDialogState extends State<_MattermostConnectDialog> {
  final _serverController = TextEditingController();
  final _patController = TextEditingController();
  bool _submitting = false;
  String? _error;

  @override
  void dispose() {
    _serverController.dispose();
    _patController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_submitting) {
      return;
    }
    final serverUrl = _serverController.text.trim();
    final accessToken = _patController.text.trim();
    if (serverUrl.isEmpty || accessToken.isEmpty) {
      setState(() {
        _error = 'Укажите URL сервера и Personal Access Token';
      });
      return;
    }

    setState(() {
      _submitting = true;
      _error = null;
    });

    try {
      await widget.apiClient.connectMattermost(
        serverUrl: serverUrl,
        accessToken: accessToken,
      );
      _patController.clear();
      await widget.onConnected();
      if (mounted) {
        Navigator.of(context).pop();
      }
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
      if (mounted) {
        Navigator.of(context).pop();
      }
    } on ApiException catch (e) {
      _patController.clear();
      if (mounted) {
        setState(() {
          _error = e.message;
          _submitting = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Подключить Mattermost'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextField(
              controller: _serverController,
              decoration: const InputDecoration(
                labelText: 'Server URL',
                hintText: 'https://mattermost.example.com',
              ),
              enabled: !_submitting,
              keyboardType: TextInputType.url,
              textInputAction: TextInputAction.next,
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _patController,
              decoration: const InputDecoration(
                labelText: 'Personal Access Token',
              ),
              enabled: !_submitting,
              obscureText: true,
              autocorrect: false,
              enableSuggestions: false,
              textInputAction: TextInputAction.done,
              onSubmitted: (_) => _submit(),
            ),
            if (_submitting) ...[
              const SizedBox(height: 16),
              const Center(
                child: SizedBox(
                  width: 24,
                  height: 24,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              ),
            ],
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _submitting ? null : () => Navigator.of(context).pop(),
          child: const Text('Отмена'),
        ),
        FilledButton(
          onPressed: _submitting ? null : _submit,
          child: const Text('Подключить'),
        ),
      ],
    );
  }
}

class _OpenAiKeyDialog extends StatefulWidget {
  const _OpenAiKeyDialog({
    required this.apiClient,
    required this.authController,
    required this.replace,
    required this.onUpdated,
  });

  final SecretaryApiClient apiClient;
  final AuthController authController;
  final bool replace;
  final Future<void> Function() onUpdated;

  @override
  State<_OpenAiKeyDialog> createState() => _OpenAiKeyDialogState();
}

class _OpenAiKeyDialogState extends State<_OpenAiKeyDialog> {
  final _keyController = TextEditingController();
  bool _submitting = false;
  String? _error;

  @override
  void dispose() {
    _keyController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_submitting) {
      return;
    }
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      await widget.apiClient.putOpenaiCredential(_keyController.text);
      _keyController.clear();
      await widget.onUpdated();
      if (mounted) {
        Navigator.of(context).pop();
      }
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
      if (mounted) {
        Navigator.of(context).pop();
      }
    } on ApiException catch (e) {
      _keyController.clear();
      if (mounted) {
        setState(() => _error = e.message);
      }
    } finally {
      if (mounted) {
        setState(() => _submitting = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(
        widget.replace ? 'Заменить OpenAI ключ' : 'Установить OpenAI ключ',
      ),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TextField(
            controller: _keyController,
            decoration: const InputDecoration(labelText: 'API key'),
            obscureText: true,
            autocorrect: false,
            enableSuggestions: false,
            enabled: !_submitting,
          ),
          if (_error != null) ...[
            const SizedBox(height: 8),
            Text(
              _error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ],
        ],
      ),
      actions: [
        TextButton(
          onPressed: _submitting ? null : () => Navigator.of(context).pop(),
          child: const Text('Отмена'),
        ),
        FilledButton(
          onPressed: _submitting ? null : _submit,
          child: Text(widget.replace ? 'Заменить' : 'Установить'),
        ),
      ],
    );
  }
}

class _ConnectionRow extends StatelessWidget {
  const _ConnectionRow({
    required this.label,
    required this.connected,
    this.detail,
  });

  final String label;
  final bool connected;
  final String? detail;

  @override
  Widget build(BuildContext context) {
    final status = connectionStatusLabel(connected);
    final suffix = detail != null && detail!.isNotEmpty ? ' ($detail)' : '';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Text('$label: $status$suffix'),
    );
  }
}

String formatTokenCount(int value) {
  final digits = value.abs().toString();
  final buffer = StringBuffer(value < 0 ? '-' : '');
  for (var index = 0; index < digits.length; index++) {
    if (index > 0 && (digits.length - index) % 3 == 0) {
      buffer.write('\u00a0');
    }
    buffer.write(digits[index]);
  }
  return buffer.toString();
}

class _OpenAiDailyBudgetControl extends StatelessWidget {
  const _OpenAiDailyBudgetControl({
    required this.settings,
    required this.controller,
    required this.saving,
    required this.onSave,
  });

  final UserSettings settings;
  final TextEditingController controller;
  final bool saving;
  final Future<void> Function() onSave;

  @override
  Widget build(BuildContext context) {
    final budget = settings.openaiDailyBudget;
    final theme = Theme.of(context);
    final usage = budget.dailyTokenLimit == null
        ? 'Сегодня: ${formatTokenCount(budget.tokensUsedToday)} токенов. '
              'Дневной лимит не задан.'
        : 'Сегодня: ${formatTokenCount(budget.tokensUsedToday)} / '
              '${formatTokenCount(budget.dailyTokenLimit!)} токенов';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Дневной лимит OpenAI', style: theme.textTheme.titleSmall),
        const SizedBox(height: 4),
        Text(
          'Когда дневной расход достигает лимита, Секретарь перестаёт обращаться '
          'к OpenAI до начала следующих суток. Остальные функции работают как обычно. '
          'Пустое поле отключает лимит.',
          style: theme.textTheme.bodySmall,
        ),
        const SizedBox(height: 12),
        Wrap(
          spacing: 16,
          runSpacing: 12,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            SizedBox(
              width: 320,
              child: TextField(
                key: const Key('account_openai_daily_token_limit'),
                controller: controller,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'Дневной лимит OpenAI, токенов',
                ),
              ),
            ),
            OutlinedButton(
              key: const Key('account_openai_daily_token_limit_save'),
              onPressed: saving ? null : () => onSave(),
              child: Text(saving ? 'Сохранение…' : 'Сохранить лимит'),
            ),
          ],
        ),
        const SizedBox(height: 8),
        Text(
          usage,
          key: const Key('account_openai_daily_budget_usage'),
          style: theme.textTheme.bodySmall,
        ),
        if (budget.exhausted) ...[
          const SizedBox(height: 4),
          Text(
            openAiDailyBudgetExhaustedMessage,
            key: const Key('account_openai_daily_budget_exhausted'),
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.error,
            ),
          ),
        ],
      ],
    );
  }
}

class _InterfaceScaleCard extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final controller = UiTextScaleScope.maybeOf(context);
    if (controller == null) {
      return const SizedBox.shrink();
    }
    return AnimatedBuilder(
      animation: controller,
      builder: (context, _) {
        return AccountSectionCard(
          title: 'Интерфейс',
          children: [
            Text(
              'Масштаб текста на этом устройстве: ${controller.percent}%',
              key: const Key('ui_text_scale_label'),
            ),
            Slider(
              key: const Key('ui_text_scale_slider'),
              value: controller.factor,
              min: kUiTextScaleMin,
              max: kUiTextScaleMax,
              divisions: kUiTextScaleDivisions,
              label: '${controller.percent}%',
              onChanged: controller.setFactor,
            ),
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton(
                key: const Key('ui_text_scale_reset'),
                onPressed: controller.factor == kUiTextScaleDefault
                    ? null
                    : controller.reset,
                child: const Text('100% / по умолчанию'),
              ),
            ),
          ],
        );
      },
    );
  }
}
