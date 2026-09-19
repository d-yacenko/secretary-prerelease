import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';

import 'api_error.dart';
import 'api_models.dart';
import '../config/url_utils.dart';
import '../timezone/client_timezone_context.dart';

/// Typed HTTP client for Secretary personal APIs.
class SecretaryApiClient {
  SecretaryApiClient({
    http.Client? httpClient,
    Duration? timeout,
    ClientTimezoneProvider? timezoneProvider,
  }) : _httpClient = httpClient ?? http.Client(),
       _timeout = timeout ?? const Duration(seconds: 30),
       _timezoneProvider =
           timezoneProvider ?? const SystemClientTimezoneProvider();

  final http.Client _httpClient;
  final Duration _timeout;
  final ClientTimezoneProvider _timezoneProvider;

  Uri? _baseUri;
  String? _token;

  String? get baseUrl => _baseUri?.toString();

  void configure({required String baseUrl, String? token}) {
    final normalized = parseApiBaseUrl(baseUrl);
    if (normalized == null) {
      throw ArgumentError('Invalid base URL');
    }
    _baseUri = normalized;
    _token = token;
  }

  void clearToken() {
    _token = null;
  }

  Future<HealthStatus> getHealth() async {
    final body = await _request('GET', '/health', authenticated: false);
    return HealthStatus.fromJson(body);
  }

  Future<UserMe> getMe() async {
    final body = await _request('GET', '/me');
    return UserMe.fromJson(body);
  }

  Future<UserMe> patchMe({required String displayName}) async {
    final body = await _request(
      'PATCH',
      '/me',
      jsonBody: {'display_name': displayName},
    );
    return UserMe.fromJson(body);
  }

  Future<UserSettings> getSettings() async {
    final body = await _request('GET', '/me/settings');
    return UserSettings.fromJson(body);
  }

  Future<UserSettings> patchSettings({
    String? timezone,
    String? assistantModel,
    String? assistantReasoningEffort,
    String? assistantVerbosity,
    int? assistantMaxRounds,
    bool patchAssistantMaxRounds = false,
    bool? autoLabelEnabled,
    int? openaiDailyTokenLimit,
    bool patchOpenaiDailyTokenLimit = false,
  }) async {
    final jsonBody = <String, dynamic>{};
    if (timezone != null) {
      jsonBody['timezone'] = timezone;
    }
    if (assistantModel != null) {
      jsonBody['assistant_model'] = assistantModel;
    }
    if (assistantReasoningEffort != null) {
      jsonBody['assistant_reasoning_effort'] = assistantReasoningEffort;
    }
    if (assistantVerbosity != null) {
      jsonBody['assistant_verbosity'] = assistantVerbosity;
    }
    if (patchAssistantMaxRounds) {
      jsonBody['assistant_max_rounds'] = assistantMaxRounds;
    }
    if (autoLabelEnabled != null) {
      jsonBody['auto_label_enabled'] = autoLabelEnabled;
    }
    if (patchOpenaiDailyTokenLimit) {
      jsonBody['openai_daily_token_limit'] = openaiDailyTokenLimit;
    }
    final body = await _request('PATCH', '/me/settings', jsonBody: jsonBody);
    return UserSettings.fromJson(body);
  }

  Future<UserIdentity> getIdentity() async {
    final body = await _request('GET', '/me/identity');
    return UserIdentity.fromJson(body);
  }

  Future<UserIdentity> putIdentity({required String profileText}) async {
    final body = await _request(
      'PUT',
      '/me/identity',
      jsonBody: {'profile_text': profileText},
    );
    return UserIdentity.fromJson(body);
  }

  Future<UserSemanticContext> getSemanticContext() async {
    final body = await _request('GET', '/me/semantic-context');
    return UserSemanticContext.fromJson(body);
  }

  Future<UserSemanticContext> putSemanticContext({
    required String contextText,
  }) async {
    final body = await _request(
      'PUT',
      '/me/semantic-context',
      jsonBody: {'context_text': contextText},
    );
    return UserSemanticContext.fromJson(body);
  }

  Future<void> putOpenaiCredential(String apiKey) async {
    await _request(
      'PUT',
      '/me/credentials/openai',
      jsonBody: {'api_key': apiKey},
    );
  }

  Future<void> deleteOpenaiCredential() async {
    await _request('DELETE', '/me/credentials/openai');
  }

  Future<Connections> getConnections() async {
    final body = await _request('GET', '/connections');
    return Connections.fromJson(body);
  }

  Future<List<SourcePreference>> getSourcePreferences() async {
    final body = await _request('GET', '/me/source-preferences');
    return SourcePreferenceList.fromJson(body).preferences;
  }

  Future<SourcePreference> patchSourceEnabled(
    String source,
    bool? enabled,
  ) async {
    final body = await _request(
      'PATCH',
      '/me/source-preferences/$source',
      jsonBody: {'enabled': enabled},
    );
    return SourcePreference.fromJson(body);
  }

  Future<SourcePreference> patchSourceSyncInterval(
    String source,
    int? seconds,
  ) async {
    final body = await _request(
      'PATCH',
      '/me/source-preferences/$source',
      jsonBody: {'sync_interval_seconds': seconds},
    );
    return SourcePreference.fromJson(body);
  }

  Future<SourcePreference> patchSourceHistoryDays(
    String source,
    int? days,
  ) async {
    final body = await _request(
      'PATCH',
      '/me/source-preferences/$source',
      jsonBody: {'history_days': days},
    );
    return SourcePreference.fromJson(body);
  }

  Future<SourcePreference> resetSourcePreference(String source) async {
    final body = await _request(
      'PATCH',
      '/me/source-preferences/$source',
      jsonBody: {
        'enabled': null,
        'sync_interval_seconds': null,
        'history_days': null,
      },
    );
    return SourcePreference.fromJson(body);
  }

  Future<GoogleAuthorizationUrl> getGoogleAuthorizationUrl() async {
    final body = await _request(
      'POST',
      '/auth/google/authorization-url',
      jsonBody: {},
    );
    return GoogleAuthorizationUrl.fromJson(body);
  }

  Future<MattermostConnectResult> connectMattermost({
    required String serverUrl,
    required String accessToken,
  }) async {
    try {
      final body = await _request(
        'POST',
        '/connectors/mattermost/connect',
        jsonBody: {'server_url': serverUrl, 'access_token': accessToken},
      );
      return MattermostConnectResult.fromJson(body);
    } on AuthenticationException catch (e) {
      // Mattermost PAT failures use HTTP 401; treat as connect error, not session logout.
      throw ServerException(e.message);
    }
  }

  Future<TelegramLinkResult> linkTelegram() async {
    final body = await _request('POST', '/telegram/link');
    return TelegramLinkResult.fromJson(body);
  }

  Future<TelegramMtprotoStatus> getTelegramMtprotoStatus() async {
    final body = await _request('GET', '/telegram/mtproto/status');
    return TelegramMtprotoStatus.fromJson(body);
  }

  Future<TelegramMtprotoAuthStart> startTelegramMtprotoAuth({
    required String phone,
  }) async {
    final body = await _request(
      'POST',
      '/telegram/mtproto/auth/start',
      jsonBody: {'phone': phone},
    );
    return TelegramMtprotoAuthStart.fromJson(body);
  }

  Future<TelegramMtprotoAuthCode> submitTelegramMtprotoCode({
    required String challengeId,
    required String code,
  }) async {
    final body = await _request(
      'POST',
      '/telegram/mtproto/auth/code',
      jsonBody: {'challenge_id': challengeId, 'code': code},
    );
    return TelegramMtprotoAuthCode.fromJson(body);
  }

  Future<TelegramMtprotoAccount> submitTelegramMtprotoPassword({
    required String challengeId,
    required String password,
  }) async {
    final body = await _request(
      'POST',
      '/telegram/mtproto/auth/password',
      jsonBody: {'challenge_id': challengeId, 'password': password},
    );
    return TelegramMtprotoAccount.fromJson(body);
  }

  Future<TelegramMtprotoFolderList> getTelegramMtprotoFolders() async {
    final body = await _request('GET', '/telegram/mtproto/folders');
    return TelegramMtprotoFolderList.fromJson(body);
  }

  Future<TelegramMtprotoConfiguredFolders>
  getTelegramMtprotoSyncFolders() async {
    final body = await _request('GET', '/telegram/mtproto/sync-folders');
    return TelegramMtprotoConfiguredFolders.fromJson(body);
  }

  Future<TelegramMtprotoConfiguredFolders> putTelegramMtprotoSyncFolders({
    required List<String> folderNames,
    required bool ignoreMuted,
  }) async {
    final body = await _request(
      'PUT',
      '/telegram/mtproto/sync-folders',
      jsonBody: {'folder_names': folderNames, 'ignore_muted': ignoreMuted},
    );
    return TelegramMtprotoConfiguredFolders.fromJson(body);
  }

  Future<TelegramMtprotoScopePreview> previewTelegramMtprotoScope() async {
    final body = await _request('GET', '/telegram/mtproto/sync-scope/preview');
    return TelegramMtprotoScopePreview.fromJson(body);
  }

  Future<TelegramMtprotoScopeReconcile> reconcileTelegramMtprotoScope() async {
    final body = await _request(
      'POST',
      '/telegram/mtproto/sync-scope/reconcile',
    );
    return TelegramMtprotoScopeReconcile.fromJson(body);
  }

  Future<TelegramMtprotoHistorySync> syncTelegramMtprotoScopePeer(
    int peerId,
  ) async {
    final body = await _request(
      'POST',
      '/telegram/mtproto/sync-scope/peers/$peerId/sync',
    );
    return TelegramMtprotoHistorySync.fromJson(body);
  }

  Future<TelegramMtprotoGroupList> getTelegramMtprotoGroups() async {
    final body = await _request('GET', '/telegram/mtproto/groups');
    return TelegramMtprotoGroupList.fromJson(body);
  }

  Future<TelegramMtprotoGroupSelection> setTelegramMtprotoGroupSelected({
    required int peerId,
    required bool selected,
  }) async {
    final body = await _request(
      'PATCH',
      '/telegram/mtproto/groups/$peerId',
      jsonBody: {'selected': selected},
    );
    return TelegramMtprotoGroupSelection.fromJson(body);
  }

  Future<TelegramMtprotoHistorySync> syncTelegramMtprotoGroup(
    int peerId,
  ) async {
    final body = await _request(
      'POST',
      '/telegram/mtproto/groups/$peerId/sync',
    );
    return TelegramMtprotoHistorySync.fromJson(body);
  }

  Future<TeamsAuthorizationUrl> getTeamsAuthorizationUrl() async {
    final body = await _request(
      'POST',
      '/auth/teams/authorization-url',
      jsonBody: {},
    );
    return TeamsAuthorizationUrl.fromJson(body);
  }

  Future<void> disconnectTeams() async {
    await _request('POST', '/auth/teams/disconnect', jsonBody: {});
  }

  Future<YandexConnectResult> connectYandexMail({
    required String email,
    required String appPassword,
  }) async {
    try {
      final body = await _request(
        'POST',
        '/connectors/yandex/mail/connect',
        jsonBody: {'email': email, 'app_password': appPassword},
      );
      return YandexConnectResult.fromJson(body);
    } on AuthenticationException catch (e) {
      throw ServerException(e.message);
    }
  }

  Future<YandexConnectResult> connectYandexCalendar({
    required String email,
    required String appPassword,
  }) async {
    try {
      final body = await _request(
        'POST',
        '/connectors/yandex/calendar/connect',
        jsonBody: {'email': email, 'app_password': appPassword},
      );
      return YandexConnectResult.fromJson(body);
    } on AuthenticationException catch (e) {
      throw ServerException(e.message);
    }
  }

  Future<CaptureTaskResponse> captureTask(CaptureTaskRequest request) async {
    final body = await _request(
      'POST',
      '/capture/task',
      jsonBody: request.toJson(),
      successStatuses: {201},
    );
    return CaptureTaskResponse.fromJson(body);
  }

  Future<CaptureNoteResponse> captureNote(CaptureNoteRequest request) async {
    final body = await _request(
      'POST',
      '/capture/note',
      jsonBody: request.toJson(),
      successStatuses: {201},
    );
    return CaptureNoteResponse.fromJson(body);
  }

  Future<List<NotificationOut>> listUnresolvedNotifications() async {
    final body = await _request(
      'GET',
      '/notifications',
      queryParameters: {'status': 'unresolved'},
    );
    return (body['notifications'] as List<dynamic>)
        .map((e) => NotificationOut.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<NotificationOut> markNotificationRead(String notificationId) async {
    final body = await _request('POST', '/notifications/$notificationId/read');
    return NotificationOut.fromJson(body);
  }

  Future<NotificationOut> acceptNotification(String notificationId) async {
    final body = await _request(
      'POST',
      '/notifications/$notificationId/accept',
    );
    return NotificationOut.fromJson(body);
  }

  Future<NotificationOut> ignoreNotification(String notificationId) async {
    final body = await _request(
      'POST',
      '/notifications/$notificationId/ignore',
    );
    return NotificationOut.fromJson(body);
  }

  Future<InboxOut> getInbox({int recentLimit = 30}) async {
    final body = await _request(
      'GET',
      '/inbox',
      queryParameters: {'recent_limit': recentLimit.toString()},
    );
    return InboxOut.fromJson(body);
  }

  Future<InboxFeedPage> getInboxFeed({
    required String cursor,
    int limit = 30,
  }) async {
    final body = await _request(
      'GET',
      '/inbox/feed',
      queryParameters: {'cursor': cursor, 'limit': limit.toString()},
    );
    return InboxFeedPage.fromJson(body);
  }

  Future<InboxReviewMarker> putInboxReviewMarker(String afterObjectId) async {
    final body = await _request(
      'PUT',
      '/inbox/review-marker',
      jsonBody: {'after_object_id': afterObjectId},
    );
    return InboxReviewMarker.fromJson(body);
  }

  Future<void> deleteInboxReviewMarker() async {
    await _request('DELETE', '/inbox/review-marker');
  }

  Future<InboxReviewCompleteResult> completeInboxReviewMarker(
    InboxReviewReceipt receipt,
  ) async {
    final body = await _request(
      'POST',
      '/inbox/review-marker/complete',
      jsonBody: receipt.toJson(),
    );
    return InboxReviewCompleteResult.fromJson(body);
  }

  Future<Map<String, String>> bookmarksByObjects(List<String> objectIds) async {
    final decoded = await _requestJson(
      'POST',
      '/object-bookmarks/by-objects',
      jsonBody: {'object_ids': objectIds},
    );
    if (decoded is! Map<String, dynamic>) {
      throw ServerException('Unexpected bookmarks-by-objects response format');
    }
    final raw = decoded['objects'];
    if (raw is! Map<String, dynamic>) {
      throw ServerException('Unexpected bookmarks-by-objects response format');
    }
    return {
      for (final entry in raw.entries)
        entry.key: (entry.value as Map<String, dynamic>)['color'] as String,
    };
  }

  Future<String> putObjectBookmark(String objectId, String color) async {
    final body = await _request(
      'PUT',
      '/object-bookmarks/$objectId',
      jsonBody: {'color': color},
    );
    return body['color'] as String;
  }

  Future<void> deleteObjectBookmark(String objectId) async {
    await _request('DELETE', '/object-bookmarks/$objectId');
  }

  Future<IntakeLinkResult> intakeLink(String url, {String? accountId}) async {
    final body = await _request(
      'POST',
      '/intake/link',
      jsonBody: {'url': url, if (accountId != null) 'account_id': accountId},
    );
    return IntakeLinkResult.fromJson(body);
  }

  Future<List<SourceSyncStatusOut>> getSourceStatus() async {
    final body = await _request('GET', '/sources/status');
    return (body['sources'] as List<dynamic>)
        .map((e) => SourceSyncStatusOut.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<void> triggerSourceSync() async {
    await _request('POST', '/sources/sync');
  }

  Future<TodayOut> getToday() async {
    final timezone = await _timezoneProvider.current();
    final body = await _request(
      'GET',
      '/today',
      queryParameters: timezone.queryParameters(),
    );
    return TodayOut.fromJson(body);
  }

  Future<WeekOut> getWeek({String? weekStart}) async {
    final timezone = await _timezoneProvider.current();
    final query = timezone.queryParameters();
    if (weekStart != null && weekStart.isNotEmpty) {
      query['week_start'] = weekStart;
    }
    final body = await _request('GET', '/week', queryParameters: query);
    return WeekOut.fromJson(body);
  }

  Future<AvailabilityOut> getAvailability({
    required DateTime startAt,
    required DateTime endAt,
    int minDurationMinutes = 30,
  }) async {
    final timezone = await _timezoneProvider.current();
    final query = timezone.queryParameters();
    query['start_at'] = startAt.toUtc().toIso8601String();
    query['end_at'] = endAt.toUtc().toIso8601String();
    query['min_duration_minutes'] = minDurationMinutes.toString();
    final body = await _request('GET', '/availability', queryParameters: query);
    return AvailabilityOut.fromJson(body);
  }

  Future<SecretaryObject> getObject(String objectId) async {
    final body = await _request('GET', '/objects/$objectId');
    return SecretaryObject.fromJson(body);
  }

  Future<SecretaryObject> patchObject(
    String objectId,
    Map<String, dynamic> jsonBody,
  ) async {
    final body = await _request(
      'PATCH',
      '/objects/$objectId',
      jsonBody: jsonBody,
    );
    return SecretaryObject.fromJson(body);
  }

  Future<NeighborsResponse> getObjectNeighbors(String objectId) async {
    final body = await _request('GET', '/objects/$objectId/neighbors');
    return NeighborsResponse.fromJson(body);
  }

  Future<ContextResponse> getObjectContext(String objectId) async {
    final body = await _request('GET', '/objects/$objectId/context');
    return ContextResponse.fromJson(body);
  }

  Future<OpenTarget> getOpenTarget(String objectId) async {
    final body = await _request('GET', '/objects/$objectId/open-target');
    return OpenTarget.fromJson(body);
  }

  Future<LocalDeviceRegisterResult> registerLocalDevice({
    required String deviceKey,
    required String displayName,
  }) async {
    final body = await _request(
      'POST',
      '/local/devices/register',
      jsonBody: {'device_key': deviceKey, 'display_name': displayName},
      successStatuses: {201},
    );
    return LocalDeviceRegisterResult.fromJson(body);
  }

  Future<Map<String, dynamic>> registerLocalRoot({
    required String deviceKey,
    required String rootPath,
    String defaultPolicy = 'metadata_only',
    String? clientSourcePath,
  }) async {
    return await _request(
      'POST',
      '/local/roots/register',
      jsonBody: {
        'device_key': deviceKey,
        'root_path': rootPath,
        'default_policy': defaultPolicy,
        if (clientSourcePath != null) 'client_source_path': clientSourcePath,
      },
      successStatuses: {201},
    );
  }

  Future<Map<String, dynamic>> reportLocalFiles({
    required String deviceKey,
    required String rootPath,
    required List<Map<String, dynamic>> files,
  }) async {
    return await _request(
      'POST',
      '/local/files/report',
      jsonBody: {
        'device_key': deviceKey,
        'root_path': rootPath,
        'files': files,
      },
    );
  }

  Future<ClientFileIntakeResult> clientFileIntake({
    required String deviceKey,
    required String sourcePath,
    required String filename,
    required int size,
    required String modifiedAt,
    required String contentRevision,
    List<Map<String, dynamic>> representations = const [],
    String? contentHash,
    bool metadataOnly = false,
    String? rootPath,
    String? clientAbsolutePath,
    String? intakeMode,
  }) async {
    final body = await _request(
      'POST',
      '/local/files/client-intake',
      jsonBody: {
        'device_key': deviceKey,
        'source_path': sourcePath,
        'filename': filename,
        'size': size,
        'modified_at': modifiedAt,
        'content_revision': contentRevision,
        'representations': representations,
        if (contentHash != null) 'content_hash': contentHash,
        'metadata_only': metadataOnly,
        if (rootPath != null) 'root_path': rootPath,
        if (clientAbsolutePath != null)
          'client_absolute_path': clientAbsolutePath,
        if (intakeMode != null) 'intake_mode': intakeMode,
      },
      successStatuses: {201},
    );
    return ClientFileIntakeResult.fromJson(body);
  }

  Future<ClientFolderIntakeResult> clientFolderIntake({
    required String deviceKey,
    required String rootPath,
    required String clientSourcePath,
    String? displayName,
  }) async {
    final body = await _request(
      'POST',
      '/local/folders/client-intake',
      jsonBody: {
        'device_key': deviceKey,
        'root_path': rootPath,
        'client_source_path': clientSourcePath,
        if (displayName != null) 'display_name': displayName,
      },
      successStatuses: {201},
    );
    return ClientFolderIntakeResult.fromJson(body);
  }

  Future<GraphWorkspaceOut> getGraphWorkspace({
    String? rootId,
    int? seedLimit,
    int? neighborLimit,
    int? nodeLimit,
  }) async {
    final queryParameters = <String, String>{};
    if (rootId != null) {
      queryParameters['root_id'] = rootId;
    }
    if (seedLimit != null) {
      queryParameters['seed_limit'] = '$seedLimit';
    }
    if (neighborLimit != null) {
      queryParameters['neighbor_limit'] = '$neighborLimit';
    }
    if (nodeLimit != null) {
      queryParameters['node_limit'] = '$nodeLimit';
    }
    final body = await _request(
      'GET',
      '/graph/workspace',
      queryParameters: queryParameters,
    );
    return GraphWorkspaceOut.fromJson(body);
  }

  Future<TaskMutationResponse> patchTask(
    String taskId,
    TaskPatchRequest request,
  ) async {
    final body = await _request(
      'PATCH',
      '/tasks/$taskId',
      jsonBody: request.toJson(),
    );
    return TaskMutationResponse.fromJson(body);
  }

  Future<TaskStatusResponse> setTaskStatus(String taskId, String status) async {
    final body = await _request(
      'POST',
      '/tasks/$taskId/status',
      jsonBody: {'status': status},
    );
    return TaskStatusResponse.fromJson(body);
  }

  Future<TaskStatusResponse> softDeleteTask(String taskId) async {
    final body = await _request('DELETE', '/tasks/$taskId');
    return TaskStatusResponse.fromJson(body);
  }

  Future<ObjectDeleteResponse> deleteObject(String objectId) async {
    final body = await _request('DELETE', '/objects/$objectId');
    return ObjectDeleteResponse.fromJson(body);
  }

  Future<RelationCreateResponse> createRelation({
    required String sourceId,
    required String targetId,
    required String type,
  }) async {
    final body = await _request(
      'POST',
      '/relations',
      jsonBody: {'source_id': sourceId, 'target_id': targetId, 'type': type},
      successStatuses: {200, 201},
    );
    return RelationCreateResponse.fromJson(body);
  }

  Future<void> deleteRelation(String edgeId) async {
    await _requestJson('DELETE', '/relations/$edgeId', successStatuses: {204});
  }

  Future<RelationDecisionResponse> decideRelation({
    required String edgeId,
    required String decision,
  }) async {
    final body = await _request(
      'POST',
      '/relations/$edgeId/decision',
      jsonBody: {'decision': decision},
      successStatuses: {200},
    );
    return RelationDecisionResponse.fromJson(body);
  }

  Future<List<SecretaryObject>> searchObjects({
    required String query,
    String? kind,
    String? provider,
    String? labelId,
    String sort = 'relevance',
    int limit = 20,
  }) async {
    final queryParameters = <String, String>{
      'q': query,
      'limit': '$limit',
      'sort': sort,
    };
    if (kind != null && kind.isNotEmpty) {
      queryParameters['kind'] = kind;
    }
    if (provider != null && provider.isNotEmpty) {
      queryParameters['provider'] = provider;
    }
    if (labelId != null && labelId.isNotEmpty) {
      queryParameters['label_id'] = labelId;
    }
    final decoded = await _requestJson(
      'GET',
      '/search',
      queryParameters: queryParameters,
    );
    if (decoded is! List<dynamic>) {
      throw ServerException('Unexpected search response format');
    }
    return decoded
        .map((e) => SecretaryObject.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<LabelList> listLabels({int limit = 100}) async {
    final decoded = await _requestJson(
      'GET',
      '/labels',
      queryParameters: {'limit': '$limit'},
    );
    if (decoded is! Map<String, dynamic>) {
      throw ServerException('Unexpected labels response format');
    }
    return LabelList.fromJson(decoded);
  }

  Future<Map<String, List<LabelItem>>> labelsByObjects(
    List<String> objectIds,
  ) async {
    final decoded = await _requestJson(
      'POST',
      '/labels/by-objects',
      jsonBody: {'object_ids': objectIds},
    );
    if (decoded is! Map<String, dynamic>) {
      throw ServerException('Unexpected labels-by-objects response format');
    }
    final raw = decoded['objects'];
    if (raw is! Map<String, dynamic>) {
      throw ServerException('Unexpected labels-by-objects response format');
    }
    return {
      for (final entry in raw.entries)
        entry.key: (entry.value as List<dynamic>)
            .map((e) => LabelItem.fromJson(e as Map<String, dynamic>))
            .toList(),
    };
  }

  Future<LabelWriteResult> createLabel(
    String name, {
    String? description,
  }) async {
    final jsonBody = <String, dynamic>{'name': name};
    if (description != null) {
      jsonBody['description'] = description;
    }
    final decoded = await _requestJson('POST', '/labels', jsonBody: jsonBody);
    if (decoded is! Map<String, dynamic>) {
      throw ServerException('Unexpected label create response format');
    }
    return LabelWriteResult.fromJson(decoded);
  }

  Future<LabelWriteResult> renameLabel({
    required String labelId,
    required String name,
  }) async {
    return updateLabel(labelId: labelId, name: name);
  }

  Future<LabelWriteResult> updateLabel({
    required String labelId,
    String? name,
    String? description,
    bool descriptionSet = false,
  }) async {
    final jsonBody = <String, dynamic>{};
    if (name != null) {
      jsonBody['name'] = name;
    }
    if (descriptionSet) {
      jsonBody['description'] = description;
    }
    final decoded = await _requestJson(
      'PATCH',
      '/labels/$labelId',
      jsonBody: jsonBody,
    );
    if (decoded is! Map<String, dynamic>) {
      throw ServerException('Unexpected label rename response format');
    }
    return LabelWriteResult.fromJson(decoded);
  }

  Future<LabelWriteResult> deleteLabel(String labelId) async {
    final decoded = await _requestJson('DELETE', '/labels/$labelId');
    if (decoded is! Map<String, dynamic>) {
      throw ServerException('Unexpected label delete response format');
    }
    return LabelWriteResult.fromJson(decoded);
  }

  Future<ObjectLabels> getObjectLabels(String objectId) async {
    final decoded = await _requestJson('GET', '/objects/$objectId/labels');
    if (decoded is! Map<String, dynamic>) {
      throw ServerException('Unexpected object labels response format');
    }
    return ObjectLabels.fromJson(decoded);
  }

  Future<AssignLabelResult> assignLabel({
    required String objectId,
    required String labelId,
  }) async {
    final decoded = await _requestJson(
      'POST',
      '/objects/$objectId/labels/$labelId',
    );
    if (decoded is! Map<String, dynamic>) {
      throw ServerException('Unexpected assign label response format');
    }
    return AssignLabelResult.fromJson(decoded);
  }

  Future<RemoveLabelResult> removeObjectLabel({
    required String objectId,
    required String labelId,
  }) async {
    final decoded = await _requestJson(
      'DELETE',
      '/objects/$objectId/labels/$labelId',
    );
    if (decoded is! Map<String, dynamic>) {
      throw ServerException('Unexpected remove label response format');
    }
    return RemoveLabelResult.fromJson(decoded);
  }

  Future<SearchFacetsOut> getSearchFacets() async {
    final decoded = await _requestJson('GET', '/search/facets');
    if (decoded is! Map<String, dynamic>) {
      throw ServerException('Unexpected search facets response format');
    }
    return SearchFacetsOut.fromJson(decoded);
  }

  Future<AssistantMessageResponse> sendAssistantMessage(
    AssistantMessageRequest request,
  ) async {
    final timezone = await _timezoneProvider.current();
    final payload = request.toJson();
    if (request.clientTimezoneId == null && timezone.zoneId != null) {
      payload['client_timezone_id'] = timezone.zoneId;
    }
    if (request.clientUtcOffsetMinutes == null) {
      payload['client_utc_offset_minutes'] = timezone.utcOffsetMinutes;
    }
    final body = await _request(
      'POST',
      '/assistant/message',
      jsonBody: payload,
    );
    return AssistantMessageResponse.fromJson(body);
  }

  Future<ActionPlanResponse> approveActionPlan(String planId) async {
    return _postActionPlan('/assistant/action-plans/$planId/approve');
  }

  Future<ActionPlanResponse> rejectActionPlan(String planId) async {
    return _postActionPlan('/assistant/action-plans/$planId/reject');
  }

  Future<ActionPlanResponse> _postActionPlan(String path) async {
    if (_baseUri == null) {
      throw StateError('API client is not configured with a base URL');
    }
    if (_token == null || _token!.isEmpty) {
      throw AuthenticationException();
    }

    final uri = buildApiEndpointUri(_baseUri!, path);
    final headers = <String, String>{
      'Accept': 'application/json',
      'Authorization': 'Bearer $_token',
    };

    try {
      final response = await _httpClient
          .post(uri, headers: headers)
          .timeout(_timeout);

      if (response.statusCode == 200 || response.statusCode == 409) {
        if (response.body.isEmpty) {
          throw ServerException('Unexpected response format');
        }
        Map<String, dynamic>? decoded;
        try {
          final raw = jsonDecode(response.body);
          if (raw is Map<String, dynamic>) {
            decoded = raw;
          }
        } on FormatException {
          throw ServerException('Unexpected response format');
        }
        if (decoded != null) {
          final parsed = ActionPlanResponse.tryParse(decoded);
          if (parsed != null) {
            return parsed;
          }
        }
        if (response.statusCode == 409) {
          final detail = parseApiErrorDetail(response);
          throw ServerException(
            sanitizeErrorMessage(detail.message),
            detail.code,
          );
        }
        throw ServerException('Unexpected response format');
      }

      final detail = parseApiErrorDetail(response);
      final safeMessage = sanitizeErrorMessage(detail.message);
      switch (response.statusCode) {
        case 401:
          throw AuthenticationException(safeMessage);
        case 404:
          throw NotFoundException(safeMessage);
        case 422:
          throw ValidationException(safeMessage, code: detail.code);
        case 413:
          throw ValidationException(safeMessage, code: detail.code);
        default:
          if (response.statusCode >= 500) {
            throw ServerException(safeMessage, detail.code);
          }
          throw ServerException(safeMessage, detail.code);
      }
    } on TimeoutException {
      throw NetworkException();
    } on http.ClientException {
      throw NetworkException();
    }
  }

  Future<ActionPlanResumeResponse> resumeActionPlan(String planId) async {
    final body = await _request(
      'POST',
      '/assistant/action-plans/$planId/resume',
    );
    return ActionPlanResumeResponse.fromJson(body);
  }

  Future<String> transcribeAudio({
    required List<int> audioBytes,
    required String filename,
    String? contentType,
  }) async {
    if (_baseUri == null) {
      throw StateError('API client is not configured with a base URL');
    }
    if (_token == null || _token!.isEmpty) {
      throw AuthenticationException();
    }

    final uri = buildApiEndpointUri(_baseUri!, '/assistant/transcribe');
    final request = http.MultipartRequest('POST', uri);
    request.headers['Accept'] = 'application/json';
    request.headers['Authorization'] = 'Bearer $_token';
    request.files.add(
      http.MultipartFile.fromBytes(
        'audio',
        audioBytes,
        filename: filename,
        contentType: contentType != null ? MediaType.parse(contentType) : null,
      ),
    );

    try {
      final streamed = await _httpClient.send(request).timeout(_timeout);
      final response = await http.Response.fromStream(streamed);
      final decoded = _mapResponse(response, const {200});
      if (decoded is Map<String, dynamic>) {
        final text = decoded['text'];
        if (text is String) {
          return text;
        }
      }
      throw ServerException('Unexpected response format');
    } on TimeoutException {
      throw NetworkException();
    } on http.ClientException {
      throw NetworkException();
    }
  }

  Future<List<int>> synthesizeSpeech(String text) async {
    if (_baseUri == null) {
      throw StateError('API client is not configured with a base URL');
    }
    if (_token == null || _token!.isEmpty) {
      throw AuthenticationException();
    }

    final uri = buildApiEndpointUri(_baseUri!, '/assistant/speech');
    final request = http.Request('POST', uri)
      ..headers['Accept'] = 'audio/mpeg, application/json'
      ..headers['Content-Type'] = 'application/json'
      ..headers['Authorization'] = 'Bearer $_token'
      ..body = jsonEncode({'text': text});

    try {
      final streamed = await _httpClient
          .send(request)
          .timeout(const Duration(seconds: 60));
      final response = await http.Response.fromStream(streamed);
      if (response.statusCode == 200) {
        if (response.bodyBytes.isEmpty) {
          throw ServerException('Unexpected response format');
        }
        return response.bodyBytes;
      }
      _mapResponse(response, const {200});
      throw ServerException('Unexpected response format');
    } on TimeoutException {
      throw NetworkException();
    } on http.ClientException {
      throw NetworkException();
    }
  }

  Future<Map<String, dynamic>> _request(
    String method,
    String path, {
    Map<String, dynamic>? jsonBody,
    Map<String, String>? queryParameters,
    bool authenticated = true,
    Set<int> successStatuses = const {200},
  }) async {
    final decoded = await _requestJson(
      method,
      path,
      jsonBody: jsonBody,
      queryParameters: queryParameters,
      authenticated: authenticated,
      successStatuses: successStatuses,
    );
    if (decoded is Map<String, dynamic>) {
      return decoded;
    }
    throw ServerException('Unexpected response format');
  }

  Future<dynamic> _requestJson(
    String method,
    String path, {
    Map<String, dynamic>? jsonBody,
    Map<String, String>? queryParameters,
    bool authenticated = true,
    Set<int> successStatuses = const {200},
  }) async {
    if (_baseUri == null) {
      throw StateError('API client is not configured with a base URL');
    }
    if (authenticated && (_token == null || _token!.isEmpty)) {
      throw AuthenticationException();
    }

    final uri = buildApiEndpointUri(
      _baseUri!,
      path,
    ).replace(queryParameters: queryParameters);
    final headers = <String, String>{
      'Accept': 'application/json',
      if (jsonBody != null) 'Content-Type': 'application/json',
      if (authenticated && _token != null) 'Authorization': 'Bearer $_token',
    };

    try {
      final response = await _httpClient
          .send(
            http.Request(method, uri)
              ..headers.addAll(headers)
              ..body = jsonBody == null ? '' : jsonEncode(jsonBody),
          )
          .timeout(_timeout)
          .then(http.Response.fromStream);

      return _mapResponse(response, successStatuses);
    } on TimeoutException {
      throw NetworkException();
    } on http.ClientException {
      throw NetworkException();
    }
  }

  dynamic _mapResponse(http.Response response, Set<int> successStatuses) {
    if (successStatuses.contains(response.statusCode)) {
      if (response.body.isEmpty) {
        return {};
      }
      final decoded = jsonDecode(response.body);
      return decoded;
    }

    final detail = parseApiErrorDetail(response);
    final safeMessage = sanitizeErrorMessage(detail.message);

    switch (response.statusCode) {
      case 401:
        throw AuthenticationException(safeMessage);
      case 404:
        throw NotFoundException(safeMessage);
      case 422:
        throw ValidationException(safeMessage, code: detail.code);
      case 413:
        throw ValidationException(safeMessage, code: detail.code);
      default:
        if (response.statusCode >= 500) {
          throw ServerException(safeMessage, detail.code);
        }
        throw ServerException(safeMessage, detail.code);
    }
  }

  /// Removes bearer tokens from error text so they never appear in UI/logs.
  static String sanitizeErrorMessage(String message) {
    if (message.isEmpty) {
      return 'Request failed';
    }
    final bearerPattern = RegExp(
      r'Bearer\s+[A-Za-z0-9._\-+/=]+',
      caseSensitive: false,
    );
    final sanitized = message.replaceAll(bearerPattern, 'Bearer [redacted]');
    if (sanitized == 'google drive scope not granted') {
      return 'Для Google Drive нужно обновить разрешения Google';
    }
    return sanitized;
  }
}
