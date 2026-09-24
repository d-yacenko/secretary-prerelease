class UserMe {
  UserMe({
    required this.id,
    required this.displayName,
    required this.createdAt,
  });

  final String id;
  final String displayName;
  final String createdAt;

  factory UserMe.fromJson(Map<String, dynamic> json) {
    return UserMe(
      id: json['id'] as String,
      displayName: json['display_name'] as String,
      createdAt: json['created_at'] as String,
    );
  }
}

class OpenAIDailyBudget {
  OpenAIDailyBudget({
    required this.dailyTokenLimit,
    required this.tokensUsedToday,
    required this.exhausted,
    required this.resetAt,
  });

  final int? dailyTokenLimit;
  final int tokensUsedToday;
  final bool exhausted;
  final String resetAt;

  factory OpenAIDailyBudget.fromJson(Map<String, dynamic> json) {
    return OpenAIDailyBudget(
      dailyTokenLimit: json['daily_token_limit'] as int?,
      tokensUsedToday: json['tokens_used_today'] as int? ?? 0,
      exhausted: json['exhausted'] as bool? ?? false,
      resetAt: json['reset_at'] as String? ?? '',
    );
  }
}

class UserSettings {
  UserSettings({
    required this.timezone,
    required this.assistantModel,
    required this.assistantReasoningEffort,
    required this.assistantVerbosity,
    required this.assistantMaxRounds,
    required this.assistantMaxRoundsOverride,
    required this.defaultAssistantMaxRounds,
    required this.minAssistantMaxRounds,
    required this.maxAssistantMaxRounds,
    required this.openaiKeyConfigured,
    required this.allowedAssistantModels,
    required this.openaiDailyBudget,
    this.autoLabelEnabled = false,
    this.temporalSignalsEnabled = false,
    this.openaiDailyTokenLimit,
    this.minOpenaiDailyTokenLimit = 1,
    this.maxOpenaiDailyTokenLimit = 1000000000,
  });

  final String timezone;
  final String assistantModel;
  final String assistantReasoningEffort;
  final String assistantVerbosity;
  final int assistantMaxRounds;
  final int? assistantMaxRoundsOverride;
  final int defaultAssistantMaxRounds;
  final int minAssistantMaxRounds;
  final int maxAssistantMaxRounds;
  final bool openaiKeyConfigured;
  final List<String> allowedAssistantModels;
  final bool autoLabelEnabled;
  final bool temporalSignalsEnabled;
  final int? openaiDailyTokenLimit;
  final int minOpenaiDailyTokenLimit;
  final int maxOpenaiDailyTokenLimit;
  final OpenAIDailyBudget openaiDailyBudget;

  factory UserSettings.fromJson(Map<String, dynamic> json) {
    return UserSettings(
      timezone: json['timezone'] as String,
      assistantModel: json['assistant_model'] as String,
      assistantReasoningEffort: json['assistant_reasoning_effort'] as String,
      assistantVerbosity: json['assistant_verbosity'] as String,
      assistantMaxRounds: json['assistant_max_rounds'] as int,
      assistantMaxRoundsOverride: json['assistant_max_rounds_override'] as int?,
      defaultAssistantMaxRounds: json['default_assistant_max_rounds'] as int,
      minAssistantMaxRounds: json['min_assistant_max_rounds'] as int,
      maxAssistantMaxRounds: json['max_assistant_max_rounds'] as int,
      openaiKeyConfigured: json['openai_key_configured'] as bool,
      allowedAssistantModels:
          (json['allowed_assistant_models'] as List<dynamic>)
              .map((item) => item as String)
              .toList(),
      autoLabelEnabled: json['auto_label_enabled'] as bool? ?? false,
      temporalSignalsEnabled:
          json['temporal_signals_enabled'] as bool? ?? false,
      openaiDailyTokenLimit: json['openai_daily_token_limit'] as int?,
      minOpenaiDailyTokenLimit:
          json['min_openai_daily_token_limit'] as int? ?? 1,
      maxOpenaiDailyTokenLimit:
          json['max_openai_daily_token_limit'] as int? ?? 1000000000,
      openaiDailyBudget: OpenAIDailyBudget.fromJson(
        (json['openai_daily_budget'] as Map<String, dynamic>?) ??
            const <String, dynamic>{},
      ),
    );
  }
}

class UserIdentity {
  UserIdentity({required this.profileText, this.fullName, this.preferredName});

  final String profileText;
  final String? fullName;
  final String? preferredName;

  factory UserIdentity.fromJson(Map<String, dynamic> json) {
    return UserIdentity(
      profileText: json['profile_text'] as String? ?? '',
      fullName: json['full_name'] as String?,
      preferredName: json['preferred_name'] as String?,
    );
  }
}

class UserSemanticContext {
  UserSemanticContext({required this.contextText});

  final String contextText;

  factory UserSemanticContext.fromJson(Map<String, dynamic> json) {
    return UserSemanticContext(
      contextText: json['context_text'] as String? ?? '',
    );
  }
}

class GoogleConnection {
  GoogleConnection({
    required this.connected,
    this.email,
    required this.gmailAvailable,
    required this.calendarAvailable,
    required this.driveAvailable,
  });

  final bool connected;
  final String? email;
  final bool gmailAvailable;
  final bool calendarAvailable;
  final bool driveAvailable;

  factory GoogleConnection.fromJson(Map<String, dynamic> json) {
    return GoogleConnection(
      connected: json['connected'] as bool,
      email: json['email'] as String?,
      gmailAvailable: json['gmail_available'] as bool? ?? false,
      calendarAvailable: json['calendar_available'] as bool? ?? false,
      driveAvailable: json['drive_available'] as bool? ?? false,
    );
  }
}

class GoogleAuthorizationUrl {
  GoogleAuthorizationUrl({required this.authorizationUrl});

  final String authorizationUrl;

  factory GoogleAuthorizationUrl.fromJson(Map<String, dynamic> json) {
    return GoogleAuthorizationUrl(
      authorizationUrl: json['authorization_url'] as String,
    );
  }
}

class YandexMailConnection {
  YandexMailConnection({required this.connected, this.email});

  final bool connected;
  final String? email;

  factory YandexMailConnection.fromJson(Map<String, dynamic> json) {
    return YandexMailConnection(
      connected: json['connected'] as bool,
      email: json['email'] as String?,
    );
  }
}

class YandexCalendarConnection {
  YandexCalendarConnection({required this.connected, this.email});

  final bool connected;
  final String? email;

  factory YandexCalendarConnection.fromJson(Map<String, dynamic> json) {
    return YandexCalendarConnection(
      connected: json['connected'] as bool,
      email: json['email'] as String?,
    );
  }
}

class MattermostConnection {
  MattermostConnection({
    required this.accountId,
    required this.serverUrl,
    required this.remoteUserId,
    required this.username,
    this.displayName,
    this.email,
  });

  final String accountId;
  final String serverUrl;
  final String remoteUserId;
  final String username;
  final String? displayName;
  final String? email;

  factory MattermostConnection.fromJson(Map<String, dynamic> json) {
    return MattermostConnection(
      accountId: json['account_id'] as String,
      serverUrl: json['server_url'] as String,
      remoteUserId: json['remote_user_id'] as String,
      username: json['username'] as String,
      displayName: json['display_name'] as String?,
      email: json['email'] as String?,
    );
  }
}

class MattermostConnectResult {
  MattermostConnectResult({
    required this.status,
    required this.accountId,
    required this.serverUrl,
    required this.remoteUserId,
    required this.username,
    this.displayName,
    this.email,
  });

  final String status;
  final String accountId;
  final String serverUrl;
  final String remoteUserId;
  final String username;
  final String? displayName;
  final String? email;

  factory MattermostConnectResult.fromJson(Map<String, dynamic> json) {
    return MattermostConnectResult(
      status: json['status'] as String,
      accountId: json['account_id'] as String,
      serverUrl: json['server_url'] as String,
      remoteUserId: json['remote_user_id'] as String,
      username: json['username'] as String,
      displayName: json['display_name'] as String?,
      email: json['email'] as String?,
    );
  }
}

class TelegramMtprotoAccount {
  TelegramMtprotoAccount({
    required this.id,
    required this.telegramUserId,
    this.username,
    this.displayName,
  });

  final String id;
  final int telegramUserId;
  final String? username;
  final String? displayName;

  factory TelegramMtprotoAccount.fromJson(Map<String, dynamic> json) {
    return TelegramMtprotoAccount(
      id: json['id'] as String,
      telegramUserId: json['telegram_user_id'] as int,
      username: json['username'] as String?,
      displayName: json['display_name'] as String?,
    );
  }
}

class TelegramMtprotoStatus {
  TelegramMtprotoStatus({
    required this.configured,
    required this.connected,
    this.account,
  });

  final bool configured;
  final bool connected;
  final TelegramMtprotoAccount? account;

  factory TelegramMtprotoStatus.fromJson(Map<String, dynamic> json) {
    final account = json['account'];
    return TelegramMtprotoStatus(
      configured: json['configured'] as bool? ?? false,
      connected: json['connected'] as bool? ?? false,
      account: account is Map<String, dynamic>
          ? TelegramMtprotoAccount.fromJson(account)
          : null,
    );
  }
}

class TelegramMtprotoAuthStart {
  TelegramMtprotoAuthStart({
    required this.challengeId,
    required this.expiresAt,
  });

  final String challengeId;
  final String expiresAt;

  factory TelegramMtprotoAuthStart.fromJson(Map<String, dynamic> json) {
    return TelegramMtprotoAuthStart(
      challengeId: json['challenge_id'] as String,
      expiresAt: json['expires_at'] as String,
    );
  }
}

class TelegramMtprotoAuthCode {
  TelegramMtprotoAuthCode({required this.status, this.account});

  final String status;
  final TelegramMtprotoAccount? account;

  factory TelegramMtprotoAuthCode.fromJson(Map<String, dynamic> json) {
    final account = json['account'];
    return TelegramMtprotoAuthCode(
      status: json['status'] as String,
      account: account is Map<String, dynamic>
          ? TelegramMtprotoAccount.fromJson(account)
          : null,
    );
  }
}

class TelegramMtprotoFolder {
  TelegramMtprotoFolder({required this.folderId, required this.name});

  final int folderId;
  final String name;

  factory TelegramMtprotoFolder.fromJson(Map<String, dynamic> json) {
    return TelegramMtprotoFolder(
      folderId: json['folder_id'] as int,
      name: json['name'] as String,
    );
  }
}

class TelegramMtprotoConfiguredFolder {
  TelegramMtprotoConfiguredFolder({
    required this.folderId,
    required this.name,
    required this.ignoreMuted,
  });

  final int folderId;
  final String name;
  final bool ignoreMuted;

  factory TelegramMtprotoConfiguredFolder.fromJson(Map<String, dynamic> json) {
    return TelegramMtprotoConfiguredFolder(
      folderId: json['folder_id'] as int,
      name: json['name'] as String,
      ignoreMuted: json['ignore_muted'] as bool? ?? true,
    );
  }
}

class TelegramMtprotoFolderList {
  TelegramMtprotoFolderList({required this.folders, required this.truncated});

  final List<TelegramMtprotoFolder> folders;
  final bool truncated;

  factory TelegramMtprotoFolderList.fromJson(Map<String, dynamic> json) {
    return TelegramMtprotoFolderList(
      folders: (json['folders'] as List<dynamic>? ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(TelegramMtprotoFolder.fromJson)
          .toList(),
      truncated: json['truncated'] as bool? ?? false,
    );
  }
}

class TelegramMtprotoConfiguredFolders {
  TelegramMtprotoConfiguredFolders({
    required this.folders,
    required this.ignoreMuted,
  });

  final List<TelegramMtprotoConfiguredFolder> folders;
  final bool ignoreMuted;

  factory TelegramMtprotoConfiguredFolders.fromJson(Map<String, dynamic> json) {
    return TelegramMtprotoConfiguredFolders(
      folders: (json['folders'] as List<dynamic>? ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(TelegramMtprotoConfiguredFolder.fromJson)
          .toList(),
      ignoreMuted: json['ignore_muted'] as bool? ?? true,
    );
  }
}

class TelegramMtprotoDialog {
  TelegramMtprotoDialog({
    required this.peerId,
    required this.kind,
    required this.title,
    this.username,
    required this.isMuted,
  });

  final int peerId;
  final String kind;
  final String title;
  final String? username;
  final bool isMuted;

  factory TelegramMtprotoDialog.fromJson(Map<String, dynamic> json) {
    return TelegramMtprotoDialog(
      peerId: json['peer_id'] as int,
      kind: json['kind'] as String,
      title: json['title'] as String,
      username: json['username'] as String?,
      isMuted: json['is_muted'] as bool? ?? false,
    );
  }
}

class TelegramMtprotoScopePreview {
  TelegramMtprotoScopePreview({
    required this.dialogs,
    required this.truncated,
    required this.skippedCounts,
    required this.configuredFolderCount,
  });

  final List<TelegramMtprotoDialog> dialogs;
  final bool truncated;
  final Map<String, int> skippedCounts;
  final int configuredFolderCount;

  factory TelegramMtprotoScopePreview.fromJson(Map<String, dynamic> json) {
    final skipped = json['skipped_counts'];
    return TelegramMtprotoScopePreview(
      dialogs: (json['dialogs'] as List<dynamic>? ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(TelegramMtprotoDialog.fromJson)
          .toList(),
      truncated: json['truncated'] as bool? ?? false,
      skippedCounts: skipped is Map<String, dynamic>
          ? skipped.map((key, value) => MapEntry(key, value as int))
          : const {},
      configuredFolderCount: json['configured_folder_count'] as int? ?? 0,
    );
  }
}

class TelegramMtprotoScopeReconcile {
  TelegramMtprotoScopeReconcile({
    required this.active,
    required this.activated,
    required this.deactivated,
    required this.unchanged,
    required this.peers,
  });

  final int active;
  final int activated;
  final int deactivated;
  final int unchanged;
  final List<TelegramMtprotoDialog> peers;

  factory TelegramMtprotoScopeReconcile.fromJson(Map<String, dynamic> json) {
    return TelegramMtprotoScopeReconcile(
      active: json['active'] as int? ?? 0,
      activated: json['activated'] as int? ?? 0,
      deactivated: json['deactivated'] as int? ?? 0,
      unchanged: json['unchanged'] as int? ?? 0,
      peers: (json['peers'] as List<dynamic>? ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(TelegramMtprotoDialog.fromJson)
          .toList(),
    );
  }
}

class TelegramMtprotoGroup {
  TelegramMtprotoGroup({
    required this.peerId,
    required this.kind,
    required this.title,
    this.username,
    required this.isForum,
    required this.selected,
    required this.available,
  });

  final int peerId;
  final String kind;
  final String title;
  final String? username;
  final bool isForum;
  final bool selected;
  final bool available;

  factory TelegramMtprotoGroup.fromJson(Map<String, dynamic> json) {
    return TelegramMtprotoGroup(
      peerId: json['peer_id'] as int,
      kind: json['kind'] as String,
      title: json['title'] as String,
      username: json['username'] as String?,
      isForum: json['is_forum'] as bool? ?? false,
      selected: json['selected'] as bool? ?? false,
      available: json['available'] as bool? ?? false,
    );
  }
}

class TelegramMtprotoGroupList {
  TelegramMtprotoGroupList({required this.groups, required this.truncated});

  final List<TelegramMtprotoGroup> groups;
  final bool truncated;

  factory TelegramMtprotoGroupList.fromJson(Map<String, dynamic> json) {
    return TelegramMtprotoGroupList(
      groups: (json['groups'] as List<dynamic>? ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(TelegramMtprotoGroup.fromJson)
          .toList(),
      truncated: json['truncated'] as bool? ?? false,
    );
  }
}

class TelegramMtprotoGroupSelection {
  TelegramMtprotoGroupSelection({required this.peerId, required this.selected});

  final int peerId;
  final bool selected;

  factory TelegramMtprotoGroupSelection.fromJson(Map<String, dynamic> json) {
    return TelegramMtprotoGroupSelection(
      peerId: json['peer_id'] as int,
      selected: json['selected'] as bool? ?? false,
    );
  }
}

class TelegramMtprotoHistorySync {
  TelegramMtprotoHistorySync({
    required this.peerId,
    required this.scanned,
    required this.materialized,
    required this.created,
    required this.updated,
    required this.unchanged,
    required this.skipped,
    required this.jobsEnqueued,
    required this.historyComplete,
  });

  final int peerId;
  final int scanned;
  final int materialized;
  final int created;
  final int updated;
  final int unchanged;
  final int skipped;
  final int jobsEnqueued;
  final bool historyComplete;

  factory TelegramMtprotoHistorySync.fromJson(Map<String, dynamic> json) {
    return TelegramMtprotoHistorySync(
      peerId: json['peer_id'] as int,
      scanned: json['scanned'] as int? ?? 0,
      materialized: json['materialized'] as int? ?? 0,
      created: json['created'] as int? ?? 0,
      updated: json['updated'] as int? ?? 0,
      unchanged: json['unchanged'] as int? ?? 0,
      skipped: json['skipped'] as int? ?? 0,
      jobsEnqueued: json['jobs_enqueued'] as int? ?? 0,
      historyComplete: json['history_complete'] as bool? ?? false,
    );
  }
}

class TeamsConnection {
  TeamsConnection({
    required this.configured,
    required this.connected,
    this.reconnectRequired = false,
    this.displayName,
    this.upn,
    this.tenantId,
  });

  final bool configured;
  final bool connected;
  final bool reconnectRequired;
  final String? displayName;
  final String? upn;
  final String? tenantId;

  factory TeamsConnection.unavailable() {
    return TeamsConnection(configured: false, connected: false);
  }

  factory TeamsConnection.fromJson(Map<String, dynamic> json) {
    return TeamsConnection(
      configured: json['configured'] as bool? ?? false,
      connected: json['connected'] as bool? ?? false,
      reconnectRequired: json['reconnect_required'] as bool? ?? false,
      displayName: json['display_name'] as String?,
      upn: json['upn'] as String?,
      tenantId: json['tenant_id'] as String?,
    );
  }
}

class TeamsAuthorizationUrl {
  TeamsAuthorizationUrl({required this.authorizationUrl});

  final String authorizationUrl;

  factory TeamsAuthorizationUrl.fromJson(Map<String, dynamic> json) {
    return TeamsAuthorizationUrl(
      authorizationUrl: json['authorization_url'] as String,
    );
  }
}

class YandexConnectResult {
  YandexConnectResult({
    required this.status,
    required this.accountId,
    required this.email,
  });

  final String status;
  final String accountId;
  final String email;

  factory YandexConnectResult.fromJson(Map<String, dynamic> json) {
    return YandexConnectResult(
      status: json['status'] as String,
      accountId: json['account_id'] as String,
      email: json['email'] as String,
    );
  }
}

class Connections {
  Connections({
    required this.google,
    required this.yandexMail,
    required this.yandexCalendar,
    required this.mattermost,
    required this.teams,
  });

  final GoogleConnection google;
  final YandexMailConnection yandexMail;
  final YandexCalendarConnection yandexCalendar;
  final List<MattermostConnection> mattermost;
  final TeamsConnection teams;

  factory Connections.fromJson(Map<String, dynamic> json) {
    final mattermostRaw = json['mattermost'];
    final teamsRaw = json['teams'];
    return Connections(
      google: GoogleConnection.fromJson(json['google'] as Map<String, dynamic>),
      yandexMail: YandexMailConnection.fromJson(
        json['yandex_mail'] as Map<String, dynamic>,
      ),
      yandexCalendar: YandexCalendarConnection.fromJson(
        json['yandex_calendar'] as Map<String, dynamic>,
      ),
      mattermost: mattermostRaw is List<dynamic>
          ? mattermostRaw
                .map(
                  (e) =>
                      MattermostConnection.fromJson(e as Map<String, dynamic>),
                )
                .toList()
          : const [],
      teams: teamsRaw is Map<String, dynamic>
          ? TeamsConnection.fromJson(teamsRaw)
          : TeamsConnection.unavailable(),
    );
  }
}

class CaptureTaskRequest {
  CaptureTaskRequest({
    required this.text,
    this.title,
    this.contextObjectIds = const [],
    this.dependsOnIds = const [],
  });

  final String text;
  final String? title;
  final List<String> contextObjectIds;
  final List<String> dependsOnIds;

  Map<String, dynamic> toJson() {
    return {
      'text': text,
      if (title != null) 'title': title,
      'context_object_ids': contextObjectIds,
      'depends_on_ids': dependsOnIds,
    };
  }
}

class CaptureTaskResponse {
  CaptureTaskResponse({
    required this.taskId,
    required this.contextEdgeIds,
    required this.dependencyEdgeIds,
  });

  final String taskId;
  final List<String> contextEdgeIds;
  final List<String> dependencyEdgeIds;

  factory CaptureTaskResponse.fromJson(Map<String, dynamic> json) {
    return CaptureTaskResponse(
      taskId: json['task_id'] as String,
      contextEdgeIds: (json['context_edge_ids'] as List<dynamic>)
          .map((e) => e as String)
          .toList(),
      dependencyEdgeIds: (json['dependency_edge_ids'] as List<dynamic>)
          .map((e) => e as String)
          .toList(),
    );
  }
}

class CaptureNoteRequest {
  CaptureNoteRequest({required this.text, this.title});

  final String text;
  final String? title;

  Map<String, dynamic> toJson() {
    return {'text': text, if (title != null) 'title': title};
  }
}

class CaptureNoteResponse {
  CaptureNoteResponse({required this.noteId});

  final String noteId;

  factory CaptureNoteResponse.fromJson(Map<String, dynamic> json) {
    return CaptureNoteResponse(noteId: json['note_id'] as String);
  }
}

class HealthStatus {
  HealthStatus({required this.status});
  final String status;

  factory HealthStatus.fromJson(Map<String, dynamic> json) {
    return HealthStatus(status: json['status'] as String);
  }
}

class SecretaryObject {
  SecretaryObject({
    required this.id,
    required this.kind,
    required this.title,
    this.body,
    this.provider,
    this.externalId,
    this.canonicalUri,
    this.status,
    this.startAt,
    this.dueAt,
    this.plannedStartAt,
    this.plannedEndAt,
    this.occurredAt,
    this.deletedAt,
    required this.metadata,
    required this.origin,
    required this.state,
    this.confidence,
    required this.createdAt,
    required this.updatedAt,
  });

  final String id;
  final String kind;
  final String title;
  final String? body;
  final String? provider;
  final String? externalId;
  final String? canonicalUri;
  final String? status;
  final String? startAt;
  final String? dueAt;
  final String? plannedStartAt;
  final String? plannedEndAt;
  final String? occurredAt;
  final String? deletedAt;
  final Map<String, dynamic> metadata;
  final String origin;
  final String state;
  final double? confidence;
  final String createdAt;
  final String updatedAt;

  factory SecretaryObject.fromJson(Map<String, dynamic> json) {
    return SecretaryObject(
      id: json['id'] as String,
      kind: json['kind'] as String,
      title: json['title'] as String,
      body: json['body'] as String?,
      provider: json['provider'] as String?,
      externalId: json['external_id'] as String?,
      canonicalUri: json['canonical_uri'] as String?,
      status: json['status'] as String?,
      startAt: json['start_at'] as String?,
      dueAt: json['due_at'] as String?,
      plannedStartAt: json['planned_start_at'] as String?,
      plannedEndAt: json['planned_end_at'] as String?,
      occurredAt: json['occurred_at'] as String?,
      deletedAt: json['deleted_at'] as String?,
      metadata: Map<String, dynamic>.from(
        (json['metadata'] as Map?) ?? const <String, dynamic>{},
      ),
      origin: json['origin'] as String,
      state: json['state'] as String,
      confidence: (json['confidence'] as num?)?.toDouble(),
      createdAt: json['created_at'] as String,
      updatedAt: json['updated_at'] as String,
    );
  }
}

class SecretaryEdge {
  SecretaryEdge({
    required this.id,
    required this.sourceId,
    required this.targetId,
    required this.type,
    required this.origin,
    this.confidence,
    required this.state,
    required this.metadata,
    required this.createdAt,
    required this.updatedAt,
  });

  final String id;
  final String sourceId;
  final String targetId;
  final String type;
  final String origin;
  final double? confidence;
  final String state;
  final Map<String, dynamic> metadata;
  final String createdAt;
  final String updatedAt;

  factory SecretaryEdge.fromJson(Map<String, dynamic> json) {
    return SecretaryEdge(
      id: json['id'] as String,
      sourceId: json['source_id'] as String,
      targetId: json['target_id'] as String,
      type: json['type'] as String,
      origin: json['origin'] as String,
      confidence: (json['confidence'] as num?)?.toDouble(),
      state: json['state'] as String,
      metadata: Map<String, dynamic>.from(
        (json['metadata'] as Map?) ?? const <String, dynamic>{},
      ),
      createdAt: json['created_at'] as String,
      updatedAt: json['updated_at'] as String,
    );
  }
}

class NeighborOut {
  NeighborOut({
    required this.object,
    required this.edge,
    required this.direction,
  });

  final SecretaryObject object;
  final SecretaryEdge edge;
  final String direction;

  factory NeighborOut.fromJson(Map<String, dynamic> json) {
    return NeighborOut(
      object: SecretaryObject.fromJson(json['object'] as Map<String, dynamic>),
      edge: SecretaryEdge.fromJson(json['edge'] as Map<String, dynamic>),
      direction: json['direction'] as String,
    );
  }
}

class NeighborsResponse {
  NeighborsResponse({required this.objectId, required this.neighbors});

  final String objectId;
  final List<NeighborOut> neighbors;

  factory NeighborsResponse.fromJson(Map<String, dynamic> json) {
    return NeighborsResponse(
      objectId: json['object_id'] as String,
      neighbors: (json['neighbors'] as List<dynamic>)
          .map((e) => NeighborOut.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }
}

class ContextResponse {
  ContextResponse({
    required this.object,
    required this.edges,
    required this.neighbors,
  });

  final SecretaryObject object;
  final List<SecretaryEdge> edges;
  final List<SecretaryObject> neighbors;

  factory ContextResponse.fromJson(Map<String, dynamic> json) {
    return ContextResponse(
      object: SecretaryObject.fromJson(json['object'] as Map<String, dynamic>),
      edges: (json['edges'] as List<dynamic>)
          .map((e) => SecretaryEdge.fromJson(e as Map<String, dynamic>))
          .toList(),
      neighbors: (json['neighbors'] as List<dynamic>)
          .map((e) => SecretaryObject.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }
}

class NotificationOut {
  NotificationOut({
    required this.id,
    required this.title,
    this.body,
    required this.priority,
    required this.status,
    this.sourceObjectId,
    this.relatedObjectId,
    this.resultObjectId,
    required this.proposal,
    this.readAt,
    required this.createdAt,
    required this.updatedAt,
  });

  final String id;
  final String title;
  final String? body;
  final String priority;
  final String status;
  final String? sourceObjectId;
  final String? relatedObjectId;
  final String? resultObjectId;
  final Map<String, dynamic> proposal;
  final String? readAt;
  final String createdAt;
  final String updatedAt;

  String? get proposalType => proposal['type'] as String?;

  String? get proposedAction => proposal['action'] as String?;

  String? get proposalDescription => proposal['description'] as String? ?? body;

  String? get telegramTransportEventType {
    if (proposal['type'] != 'transport_event' ||
        proposal['provider'] != 'telegram' ||
        proposal['transport'] != 'mtproto') {
      return null;
    }
    final value = proposal['event_type'];
    if (value is! String ||
        !const {
          'message_created',
          'message_edited',
          'message_deleted',
        }.contains(value)) {
      return null;
    }
    return value;
  }

  bool get isTelegramMtprotoTransportEvent =>
      telegramTransportEventType != null;

  String? get telegramTransportConversationTitle {
    final value = proposal['conversation_title'];
    return value is String && value.trim().isNotEmpty ? value.trim() : null;
  }

  String? get telegramTransportOccurredAt {
    final value = proposal['occurred_at'];
    return value is String && DateTime.tryParse(value) != null ? value : null;
  }

  String? get telegramTransportEditedAt {
    final value = proposal['edited_at'];
    return value is String && DateTime.tryParse(value) != null ? value : null;
  }

  factory NotificationOut.fromJson(Map<String, dynamic> json) {
    return NotificationOut(
      id: json['id'] as String,
      title: json['title'] as String,
      body: json['body'] as String?,
      priority: json['priority'] as String,
      status: json['status'] as String,
      sourceObjectId: json['source_object_id'] as String?,
      relatedObjectId: json['related_object_id'] as String?,
      resultObjectId: json['result_object_id'] as String?,
      proposal: Map<String, dynamic>.from(
        (json['proposal'] as Map?) ?? const <String, dynamic>{},
      ),
      readAt: json['read_at'] as String?,
      createdAt: json['created_at'] as String,
      updatedAt: json['updated_at'] as String,
    );
  }
}

class InboxSourceObjectOut {
  InboxSourceObjectOut({
    required this.id,
    required this.title,
    required this.kind,
    required this.provider,
    required this.origin,
    required this.state,
    required this.status,
    required this.primaryAt,
    required this.excerpt,
    this.feedAt,
  });

  final String id;
  final String title;
  final String kind;
  final String? provider;
  final String origin;
  final String state;
  final String? status;
  final String? primaryAt;
  final String? excerpt;
  final String? feedAt;

  String get feedStamp => (feedAt != null && feedAt!.trim().isNotEmpty)
      ? feedAt!
      : (primaryAt ?? '');

  factory InboxSourceObjectOut.fromJson(Map<String, dynamic> json) {
    return InboxSourceObjectOut(
      id: json['id'] as String,
      title: json['title'] as String,
      kind: json['kind'] as String,
      provider: json['provider'] as String?,
      origin: json['origin'] as String? ?? 'source',
      state: json['state'] as String,
      status: json['status'] as String?,
      primaryAt: json['primary_at'] as String?,
      excerpt: json['excerpt'] as String?,
      feedAt: json['feed_at'] as String?,
    );
  }
}

class InboxConversationStack {
  const InboxConversationStack({
    required this.stackId,
    required this.fingerprint,
    required this.objectIds,
    required this.displayObjectIds,
    required this.provider,
    required this.conversationLabel,
    required this.messageCount,
    required this.startAt,
    required this.endAt,
    required this.fallbackSummary,
    this.summary,
    this.summaryStatus = 'fallback',
  });

  final String stackId;
  final String fingerprint;
  final List<String> objectIds;
  final List<String> displayObjectIds;
  final String provider;
  final String conversationLabel;
  final int messageCount;
  final String startAt;
  final String endAt;
  final String? summary;
  final String fallbackSummary;
  final String summaryStatus;

  factory InboxConversationStack.fromJson(Map<String, dynamic> json) {
    return InboxConversationStack(
      stackId: json['stack_id'] as String,
      fingerprint: json['fingerprint'] as String? ?? json['stack_id'] as String,
      objectIds: (json['object_ids'] as List<dynamic>)
          .map((e) => e as String)
          .toList(),
      displayObjectIds:
          (json['display_object_ids'] as List<dynamic>? ??
                  json['object_ids'] as List<dynamic>)
              .map((e) => e as String)
              .toList(),
      provider: json['provider'] as String,
      conversationLabel: json['conversation_label'] as String,
      messageCount: json['message_count'] as int,
      startAt: json['start_at'] as String,
      endAt: json['end_at'] as String,
      summary: json['summary'] as String?,
      fallbackSummary: json['fallback_summary'] as String,
      summaryStatus: json['summary_status'] as String? ?? 'fallback',
    );
  }
}

class InboxConversationGroup {
  const InboxConversationGroup({required this.type, this.objectId, this.stack});

  final String type;
  final String? objectId;
  final InboxConversationStack? stack;

  List<String> get coveredIds {
    if (stack != null) {
      return stack!.displayObjectIds;
    }
    final id = objectId;
    return id == null ? const [] : [id];
  }

  factory InboxConversationGroup.fromJson(Map<String, dynamic> json) {
    final rawStack = json['stack'];
    return InboxConversationGroup(
      type: json['type'] as String,
      objectId: json['object_id'] as String?,
      stack: rawStack is Map<String, dynamic>
          ? InboxConversationStack.fromJson(rawStack)
          : null,
    );
  }
}

class SourceSyncStatusOut {
  SourceSyncStatusOut({
    required this.source,
    required this.provider,
    required this.accountId,
    required this.accountLabel,
    required this.status,
    this.enabled,
    required this.lastSuccessAt,
    required this.lastAttemptAt,
    required this.nextSyncAt,
    required this.lastError,
    this.errorKind,
    this.retryable = false,
  });

  final String source;
  final String provider;
  final String accountId;
  final String accountLabel;
  final String status;
  final bool? enabled;
  final String? lastSuccessAt;
  final String? lastAttemptAt;
  final String? nextSyncAt;
  final String? lastError;
  final String? errorKind;
  final bool retryable;

  factory SourceSyncStatusOut.fromJson(Map<String, dynamic> json) {
    return SourceSyncStatusOut(
      source: json['source'] as String,
      provider: json['provider'] as String,
      accountId: json['account_id'] as String,
      accountLabel: json['account_label'] as String,
      status: json['status'] as String,
      enabled: json['enabled'] as bool?,
      lastSuccessAt: json['last_success_at'] as String?,
      lastAttemptAt: json['last_attempt_at'] as String?,
      nextSyncAt: json['next_sync_at'] as String?,
      lastError: json['last_error'] as String?,
      errorKind: json['error_kind'] as String?,
      retryable: json['retryable'] as bool? ?? false,
    );
  }
}

class InboxReviewMarker {
  const InboxReviewMarker({
    required this.anchorFeedAt,
    required this.anchorObjectId,
    required this.updatedAt,
  });

  final String anchorFeedAt;
  final String anchorObjectId;
  final String updatedAt;

  factory InboxReviewMarker.fromJson(Map<String, dynamic> json) {
    return InboxReviewMarker(
      anchorFeedAt: json['anchor_feed_at'] as String,
      anchorObjectId: json['anchor_object_id'] as String,
      updatedAt: json['updated_at'] as String,
    );
  }
}

class InboxOut {
  InboxOut({
    required this.unresolvedNotifications,
    required this.recentSourceObjects,
    required this.sourceSyncStatus,
    this.recentNextCursor,
    this.recentHasMore = false,
    this.reviewMarker,
    this.conversationGroups = const [],
  });

  final List<NotificationOut> unresolvedNotifications;
  final List<InboxSourceObjectOut> recentSourceObjects;
  final List<SourceSyncStatusOut> sourceSyncStatus;
  final String? recentNextCursor;
  final bool recentHasMore;
  final InboxReviewMarker? reviewMarker;
  final List<InboxConversationGroup> conversationGroups;

  factory InboxOut.fromJson(Map<String, dynamic> json) {
    final rawMarker = json['review_marker'];
    return InboxOut(
      unresolvedNotifications:
          (json['unresolved_notifications'] as List<dynamic>)
              .map((e) => NotificationOut.fromJson(e as Map<String, dynamic>))
              .toList(),
      recentSourceObjects: (json['recent_source_objects'] as List<dynamic>)
          .map((e) => InboxSourceObjectOut.fromJson(e as Map<String, dynamic>))
          .toList(),
      sourceSyncStatus: (json['source_sync_status'] as List<dynamic>)
          .map((e) => SourceSyncStatusOut.fromJson(e as Map<String, dynamic>))
          .toList(),
      recentNextCursor: json['recent_next_cursor'] as String?,
      recentHasMore: json['recent_has_more'] as bool? ?? false,
      reviewMarker: rawMarker is Map<String, dynamic>
          ? InboxReviewMarker.fromJson(rawMarker)
          : null,
      conversationGroups:
          (json['conversation_groups'] as List<dynamic>? ?? const [])
              .map(
                (e) =>
                    InboxConversationGroup.fromJson(e as Map<String, dynamic>),
              )
              .toList(),
    );
  }
}

class InboxFeedPage {
  InboxFeedPage({
    required this.items,
    required this.nextCursor,
    required this.hasMore,
    this.conversationGroups = const [],
  });

  final List<InboxSourceObjectOut> items;
  final String? nextCursor;
  final bool hasMore;
  final List<InboxConversationGroup> conversationGroups;

  factory InboxFeedPage.fromJson(Map<String, dynamic> json) {
    return InboxFeedPage(
      items: (json['items'] as List<dynamic>)
          .map((e) => InboxSourceObjectOut.fromJson(e as Map<String, dynamic>))
          .toList(),
      nextCursor: json['next_cursor'] as String?,
      hasMore: json['has_more'] as bool? ?? false,
      conversationGroups:
          (json['conversation_groups'] as List<dynamic>? ?? const [])
              .map(
                (e) =>
                    InboxConversationGroup.fromJson(e as Map<String, dynamic>),
              )
              .toList(),
    );
  }
}

class TodayOut {
  TodayOut({
    required this.date,
    required this.timezone,
    required this.dayStart,
    required this.tasks,
    required this.calendarEvents,
    required this.notifications,
  });

  final String date;
  final String timezone;
  final String dayStart;
  final List<SecretaryObject> tasks;
  final List<SecretaryObject> calendarEvents;
  final List<NotificationOut> notifications;

  factory TodayOut.fromJson(Map<String, dynamic> json) {
    return TodayOut(
      date: json['date'] as String,
      timezone: json['timezone'] as String,
      dayStart: json['day_start'] as String,
      tasks: (json['tasks'] as List<dynamic>)
          .map((e) => SecretaryObject.fromJson(e as Map<String, dynamic>))
          .toList(),
      calendarEvents: (json['calendar_events'] as List<dynamic>)
          .map((e) => SecretaryObject.fromJson(e as Map<String, dynamic>))
          .toList(),
      notifications: (json['notifications'] as List<dynamic>)
          .map((e) => NotificationOut.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }

  /// Task is overdue when its due instant is before the Secretary local day start.
  bool isTaskOverdue(SecretaryObject task) {
    final dueAt = task.dueAt;
    if (dueAt == null) {
      return false;
    }
    final due = DateTime.tryParse(dueAt);
    final start = DateTime.tryParse(dayStart);
    if (due == null || start == null) {
      return false;
    }
    return due.isBefore(start);
  }
}

class WeekEvent {
  WeekEvent({required this.object, required this.allDay});

  final SecretaryObject object;
  final bool allDay;

  factory WeekEvent.fromJson(Map<String, dynamic> json) {
    return WeekEvent(
      object: SecretaryObject.fromJson(json),
      allDay: json['all_day'] as bool? ?? false,
    );
  }
}

class WeekTemporalHint {
  WeekTemporalHint({
    required this.id,
    required this.title,
    required this.startAt,
    this.dueAt,
    required this.endPrecision,
    required this.participation,
    this.primaryProvider,
    this.primaryKind,
    this.evidenceCount = 1,
    this.extractionConfidence,
  });

  final String id;
  final String title;
  final String startAt;
  final String? dueAt;
  final String endPrecision;
  final String participation;
  final String? primaryProvider;
  final String? primaryKind;
  final int evidenceCount;
  final double? extractionConfidence;

  bool get endUnknown => dueAt == null || endPrecision == 'unknown';

  factory WeekTemporalHint.fromJson(Map<String, dynamic> json) {
    return WeekTemporalHint(
      id: json['id'] as String,
      title: json['title'] as String,
      startAt: json['start_at'] as String,
      dueAt: json['due_at'] as String?,
      endPrecision: json['end_precision'] as String? ?? 'unknown',
      participation: json['participation'] as String? ?? '',
      primaryProvider: json['primary_provider'] as String?,
      primaryKind: json['primary_kind'] as String?,
      evidenceCount: json['evidence_count'] as int? ?? 1,
      extractionConfidence: (json['extraction_confidence'] as num?)?.toDouble(),
    );
  }
}

class WeekScheduledWork {
  WeekScheduledWork({
    required this.id,
    required this.title,
    required this.plannedStartAt,
    required this.plannedEndAt,
    this.status,
  });

  final String id;
  final String title;
  final String plannedStartAt;
  final String plannedEndAt;
  final String? status;

  bool get completed => status == 'done' || status == 'completed';

  factory WeekScheduledWork.fromJson(Map<String, dynamic> json) {
    return WeekScheduledWork(
      id: json['id'] as String,
      title: json['title'] as String,
      plannedStartAt: json['planned_start_at'] as String,
      plannedEndAt: json['planned_end_at'] as String,
      status: json['status'] as String?,
    );
  }
}

class WeekDay {
  WeekDay({
    required this.date,
    required this.isToday,
    required this.events,
    this.scheduledWork = const [],
    this.temporalHints = const [],
  });

  final String date;
  final bool isToday;
  final List<WeekEvent> events;
  final List<WeekScheduledWork> scheduledWork;
  final List<WeekTemporalHint> temporalHints;

  factory WeekDay.fromJson(Map<String, dynamic> json) {
    return WeekDay(
      date: json['date'] as String,
      isToday: json['is_today'] as bool? ?? false,
      events: (json['events'] as List<dynamic>? ?? const [])
          .map((e) => WeekEvent.fromJson(e as Map<String, dynamic>))
          .toList(),
      scheduledWork: (json['scheduled_work'] as List<dynamic>? ?? const [])
          .map((e) => WeekScheduledWork.fromJson(e as Map<String, dynamic>))
          .toList(),
      temporalHints: (json['temporal_hints'] as List<dynamic>? ?? const [])
          .map((e) => WeekTemporalHint.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }
}

class WeekOut {
  WeekOut({
    required this.weekStart,
    required this.weekEnd,
    required this.timezone,
    required this.windowStart,
    required this.windowEnd,
    required this.todayDate,
    required this.isCurrentWeek,
    required this.days,
  });

  final String weekStart;
  final String weekEnd;
  final String timezone;
  final String windowStart;
  final String windowEnd;
  final String todayDate;
  final bool isCurrentWeek;
  final List<WeekDay> days;

  factory WeekOut.fromJson(Map<String, dynamic> json) {
    return WeekOut(
      weekStart: json['week_start'] as String,
      weekEnd: json['week_end'] as String,
      timezone: json['timezone'] as String,
      windowStart: json['window_start'] as String,
      windowEnd: json['window_end'] as String,
      todayDate: json['today_date'] as String,
      isCurrentWeek: json['is_current_week'] as bool? ?? false,
      days: (json['days'] as List<dynamic>)
          .map((e) => WeekDay.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }
}

class AvailabilityBusyInterval {
  AvailabilityBusyInterval({
    required this.startAt,
    required this.endAt,
    required this.eventIds,
  });

  final String startAt;
  final String endAt;
  final List<String> eventIds;

  factory AvailabilityBusyInterval.fromJson(Map<String, dynamic> json) {
    return AvailabilityBusyInterval(
      startAt: json['start_at'] as String,
      endAt: json['end_at'] as String,
      eventIds: (json['event_ids'] as List<dynamic>? ?? const [])
          .map((e) => e.toString())
          .toList(),
    );
  }
}

class AvailabilityFreeInterval {
  AvailabilityFreeInterval({
    required this.startAt,
    required this.endAt,
    required this.durationMinutes,
  });

  final String startAt;
  final String endAt;
  final int durationMinutes;

  factory AvailabilityFreeInterval.fromJson(Map<String, dynamic> json) {
    return AvailabilityFreeInterval(
      startAt: json['start_at'] as String,
      endAt: json['end_at'] as String,
      durationMinutes: json['duration_minutes'] as int,
    );
  }
}

class AvailabilityOut {
  AvailabilityOut({
    required this.timezone,
    required this.windowStart,
    required this.windowEnd,
    required this.minDurationMinutes,
    required this.availabilityComplete,
    required this.busyIntervals,
    required this.freeIntervals,
    required this.unknownEndEventIds,
  });

  final String timezone;
  final String windowStart;
  final String windowEnd;
  final int minDurationMinutes;
  final bool availabilityComplete;
  final List<AvailabilityBusyInterval> busyIntervals;
  final List<AvailabilityFreeInterval> freeIntervals;
  final List<String> unknownEndEventIds;

  factory AvailabilityOut.fromJson(Map<String, dynamic> json) {
    return AvailabilityOut(
      timezone: json['timezone'] as String,
      windowStart: json['window_start'] as String,
      windowEnd: json['window_end'] as String,
      minDurationMinutes: json['min_duration_minutes'] as int,
      availabilityComplete: json['availability_complete'] as bool? ?? false,
      busyIntervals: (json['busy_intervals'] as List<dynamic>? ?? const [])
          .map(
            (e) => AvailabilityBusyInterval.fromJson(e as Map<String, dynamic>),
          )
          .toList(),
      freeIntervals: (json['free_intervals'] as List<dynamic>? ?? const [])
          .map(
            (e) => AvailabilityFreeInterval.fromJson(e as Map<String, dynamic>),
          )
          .toList(),
      unknownEndEventIds:
          (json['unknown_end_event_ids'] as List<dynamic>? ?? const [])
              .map((e) => e.toString())
              .toList(),
    );
  }
}

class CaptureContextRef {
  const CaptureContextRef({
    required this.id,
    required this.title,
    required this.kind,
  });

  final String id;
  final String title;
  final String kind;

  String get displayLabel {
    final normalizedKind = kind.trim();
    if (normalizedKind.isEmpty) {
      return title;
    }
    return '$normalizedKind: $title';
  }
}

class AssistantHistoryMessage {
  AssistantHistoryMessage({required this.role, required this.content});

  final String role;
  final String content;

  Map<String, dynamic> toJson() => {'role': role, 'content': content};
}

class AssistantMessageRequest {
  AssistantMessageRequest({
    required this.message,
    this.history = const [],
    this.contextObjectId,
    this.contextNotificationId,
    this.clientTimezoneId,
    this.clientUtcOffsetMinutes,
  });

  final String message;
  final List<AssistantHistoryMessage> history;
  final String? contextObjectId;
  final String? contextNotificationId;
  final String? clientTimezoneId;
  final int? clientUtcOffsetMinutes;

  Map<String, dynamic> toJson() {
    return {
      'message': message,
      'history': history.map((e) => e.toJson()).toList(),
      if (contextObjectId != null) 'context_object_id': contextObjectId,
      if (contextNotificationId != null)
        'context_notification_id': contextNotificationId,
      if (clientTimezoneId != null) 'client_timezone_id': clientTimezoneId,
      if (clientUtcOffsetMinutes != null)
        'client_utc_offset_minutes': clientUtcOffsetMinutes,
    };
  }
}

class AssistantReference {
  AssistantReference({
    required this.objectId,
    required this.title,
    required this.kind,
    this.canonicalUri,
    this.provider,
    this.primaryAt,
  });

  final String objectId;
  final String title;
  final String kind;
  final String? canonicalUri;
  final String? provider;
  final String? primaryAt;

  factory AssistantReference.fromJson(Map<String, dynamic> json) {
    return AssistantReference(
      objectId: json['object_id'] as String,
      title: json['title'] as String,
      kind: json['kind'] as String,
      canonicalUri: json['canonical_uri'] as String?,
      provider: json['provider'] as String?,
      primaryAt: json['primary_at'] as String?,
    );
  }

  String get displayLabel => '$kind: $title';
}

class InboxReviewReceipt {
  const InboxReviewReceipt({
    required this.anchorBeforeObjectId,
    required this.anchorBeforeFeedAt,
    required this.snapshotTopObjectId,
    required this.snapshotTopFeedAt,
    required this.totalCount,
  });

  final String anchorBeforeObjectId;
  final String anchorBeforeFeedAt;
  final String snapshotTopObjectId;
  final String snapshotTopFeedAt;
  final int totalCount;

  factory InboxReviewReceipt.fromJson(Map<String, dynamic> json) {
    return InboxReviewReceipt(
      anchorBeforeObjectId: json['anchor_before_object_id'] as String,
      anchorBeforeFeedAt: json['anchor_before_feed_at'] as String,
      snapshotTopObjectId: json['snapshot_top_object_id'] as String,
      snapshotTopFeedAt: json['snapshot_top_feed_at'] as String,
      totalCount: json['total_count'] as int,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'anchor_before_object_id': anchorBeforeObjectId,
      'anchor_before_feed_at': anchorBeforeFeedAt,
      'snapshot_top_object_id': snapshotTopObjectId,
      'snapshot_top_feed_at': snapshotTopFeedAt,
      'total_count': totalCount,
    };
  }
}

class InboxReviewCompleteResult {
  const InboxReviewCompleteResult({required this.status, this.reviewMarker});

  final String status;
  final InboxReviewMarker? reviewMarker;

  factory InboxReviewCompleteResult.fromJson(Map<String, dynamic> json) {
    final rawMarker = json['review_marker'];
    return InboxReviewCompleteResult(
      status: json['status'] as String,
      reviewMarker: rawMarker is Map<String, dynamic>
          ? InboxReviewMarker.fromJson(rawMarker)
          : null,
    );
  }
}

class AssistantMessageResponse {
  AssistantMessageResponse({
    required this.answer,
    required this.references,
    required this.affectedObjects,
    this.pendingActionPlan,
    this.inboxReviewReceipt,
  });

  final String answer;
  final List<AssistantReference> references;
  final List<AssistantAffectedObject> affectedObjects;
  final PendingActionPlan? pendingActionPlan;
  final InboxReviewReceipt? inboxReviewReceipt;

  factory AssistantMessageResponse.fromJson(Map<String, dynamic> json) {
    final pendingRaw = json['pending_action_plan'];
    final receiptRaw = json['inbox_review_receipt'];
    return AssistantMessageResponse(
      answer: json['answer'] as String,
      references: (json['references'] as List<dynamic>)
          .map((e) => AssistantReference.fromJson(e as Map<String, dynamic>))
          .toList(),
      affectedObjects: (json['affected_objects'] as List<dynamic>)
          .map(
            (e) => AssistantAffectedObject.fromJson(e as Map<String, dynamic>),
          )
          .toList(),
      pendingActionPlan: pendingRaw == null
          ? null
          : PendingActionPlan.fromJson(pendingRaw as Map<String, dynamic>),
      inboxReviewReceipt: receiptRaw is Map<String, dynamic>
          ? InboxReviewReceipt.fromJson(receiptRaw)
          : null,
    );
  }
}

class PendingAction {
  PendingAction({required this.toolName, required this.arguments});

  final String toolName;
  final Map<String, dynamic> arguments;

  factory PendingAction.fromJson(Map<String, dynamic> json) {
    return PendingAction(
      toolName: json['tool_name'] as String,
      arguments: Map<String, dynamic>.from(json['arguments'] as Map),
    );
  }

  String get displayLabel {
    final objectId = _frozenObjectId(arguments);
    switch (toolName) {
      case 'create_task':
        final title = arguments['title'];
        if (title is String && title.trim().isNotEmpty) {
          return 'Create task: $title';
        }
        return 'Create task';
      case 'update_task':
        if (objectId != null) {
          return 'Update task: $objectId';
        }
        return 'Update task';
      case 'set_task_status':
        final status = arguments['status'];
        final statusText = status is String && status.trim().isNotEmpty
            ? status
            : 'status';
        if (objectId != null) {
          return 'Set task status: $objectId -> $statusText';
        }
        return 'Set task status: $statusText';
      case 'delete_task':
        if (objectId != null) {
          return 'Delete task: $objectId';
        }
        return 'Delete task';
      case 'link_objects':
        return 'Link objects';
      case 'create_calendar_event':
        return _calendarEventLabel(arguments);
      case 'send_email':
        return _sendEmailLabel(arguments);
      case 'send_message':
        return _sendMessageLabel(arguments);
      default:
        return toolName.replaceAll('_', ' ');
    }
  }

  String? get voiceNarrationText {
    switch (toolName) {
      case 'send_email':
        return _sendEmailVoiceNarration(arguments);
      case 'send_message':
        return _sendMessageVoiceNarration(arguments);
      default:
        return null;
    }
  }

  static bool planIsVoiceApprovable(List<PendingAction> actions) {
    if (actions.isEmpty) {
      return false;
    }
    return actions.every((action) => action.voiceNarrationText != null);
  }

  static String? planVoicePreview(List<PendingAction> actions) {
    if (!planIsVoiceApprovable(actions)) {
      return null;
    }
    final blocks = actions
        .map((action) => action.voiceNarrationText!)
        .where((text) => text.isNotEmpty)
        .toList();
    if (blocks.isEmpty) {
      return null;
    }
    return '${blocks.join('\n\n')}\nОтправить?';
  }

  static String? _frozenObjectId(Map<String, dynamic> arguments) {
    final raw = arguments['object_id'];
    if (raw is String && raw.trim().isNotEmpty) {
      return raw.trim();
    }
    return null;
  }

  static String _calendarEventLabel(Map<String, dynamic> arguments) {
    final parts = <String>['Create calendar event'];
    final provider = arguments['provider'];
    if (provider is String && provider.trim().isNotEmpty) {
      parts.add('Provider: ${_externalProviderLabel(provider)}');
    }
    final summary = arguments['summary'];
    if (summary is String && summary.trim().isNotEmpty) {
      parts.add(summary.trim());
    }
    final account = arguments['account_email'];
    if (account is String && account.trim().isNotEmpty) {
      parts.add(account.trim());
    }
    final calendarLabel = arguments['calendar_label'];
    if (calendarLabel is String && calendarLabel.trim().isNotEmpty) {
      parts.add('calendar: ${calendarLabel.trim()}');
    } else {
      parts.add('calendar: primary');
    }
    final start = arguments['start_at'];
    final end = arguments['end_at'];
    if (start != null && end != null) {
      parts.add('$start -> $end');
    }
    final description = arguments['description'];
    if (description is String && description.trim().isNotEmpty) {
      parts.add(description.trim());
    }
    final location = arguments['location'];
    if (location is String && location.trim().isNotEmpty) {
      parts.add(location.trim());
    }
    return parts.join(' | ');
  }

  static String _sendEmailLabel(Map<String, dynamic> arguments) {
    final from = arguments['account_email'];
    final toRaw = arguments['to'];
    final to = toRaw is List
        ? toRaw.map((e) => e.toString()).join(', ')
        : (toRaw == null ? '' : toRaw.toString());
    final subject = arguments['subject'];
    final body = arguments['body'];
    final parts = <String>['Отправить письмо'];
    final provider = arguments['provider'];
    if (provider is String && provider.trim().isNotEmpty) {
      parts.add('Provider: ${_externalProviderLabel(provider)}');
    }
    if (from is String && from.trim().isNotEmpty) {
      parts.add('From: ${from.trim()}');
    }
    if (to.trim().isNotEmpty) {
      parts.add('To: $to');
    }
    if (subject is String && subject.trim().isNotEmpty) {
      parts.add('Subject: ${subject.trim()}');
    }
    if (body is String && body.isNotEmpty) {
      parts.add('Body: $body');
    }
    return parts.join('\n');
  }

  static String _sendMessageLabel(Map<String, dynamic> arguments) {
    final route = _sendMessageRoute(arguments);
    final provider = arguments['provider']?.toString() ?? '';
    final mode = arguments['mode']?.toString() ?? '';
    final body = arguments['body']?.toString() ?? '';
    final parts = <String>[];
    if (provider == 'teams') {
      parts.add('Microsoft Teams');
      final display = route['chat_display_title']?.toString().trim();
      if (display != null && display.isNotEmpty) {
        parts.add(display);
      }
    } else if (provider == 'telegram') {
      parts.add('Telegram');
      final display = route['chat_display_name']?.toString().trim();
      final username = route['chat_username']?.toString().trim();
      if (display != null && display.isNotEmpty) {
        parts.add(display);
      } else if (username != null && username.isNotEmpty) {
        parts.add('@$username');
      }
    } else {
      parts.add('Mattermost');
      final display =
          (route['channel_display_name'] ?? arguments['channel_display_name'])
              ?.toString()
              .trim();
      if (display != null && display.isNotEmpty) {
        parts.add(display);
      }
    }
    parts.add(mode == 'reply' ? 'Ответ' : 'Новое сообщение');
    if (body.isNotEmpty) {
      parts.add(body);
    }
    return parts.join('\n');
  }

  static Map<String, dynamic> _sendMessageRoute(
    Map<String, dynamic> arguments,
  ) {
    final raw = arguments['route'];
    if (raw is Map) {
      return Map<String, dynamic>.from(raw);
    }
    return arguments;
  }

  static String _externalProviderLabel(String provider) {
    switch (provider.trim().toLowerCase()) {
      case 'yandex':
        return 'Yandex';
      case 'google':
        return 'Google';
      case 'teams':
        return 'Microsoft Teams';
      case 'telegram':
        return 'Telegram';
      case 'mattermost':
        return 'Mattermost';
      default:
        return provider;
    }
  }

  static String? _sendEmailVoiceNarration(Map<String, dynamic> arguments) {
    final toRaw = arguments['to'];
    final to = toRaw is List
        ? toRaw.map((e) => e.toString()).join(', ')
        : (toRaw == null ? '' : toRaw.toString());
    final subject = arguments['subject']?.toString() ?? '';
    final body = arguments['body']?.toString() ?? '';
    if (to.trim().isEmpty || subject.trim().isEmpty) {
      return null;
    }
    return 'Подготовлено письмо.\n'
        'Кому: ${to.trim()}\n'
        'Тема: ${subject.trim()}\n'
        'Текст: $body';
  }

  static String? _sendMessageVoiceNarration(Map<String, dynamic> arguments) {
    final route = _sendMessageRoute(arguments);
    final provider = arguments['provider']?.toString() ?? '';
    if (provider.trim().isEmpty) {
      return null;
    }
    final destination = _sendMessageDestination(provider, route, arguments);
    if (destination == null || destination.isEmpty) {
      return null;
    }
    final mode = arguments['mode']?.toString() ?? '';
    final body = arguments['body']?.toString() ?? '';
    final modeLabel = mode == 'reply' ? 'ответ' : 'новое сообщение';
    return 'Подготовлено сообщение.\n'
        'Куда: ${_externalProviderLabel(provider)}, $destination\n'
        'Режим: $modeLabel\n'
        'Текст: $body';
  }

  static String? _sendMessageDestination(
    String provider,
    Map<String, dynamic> route,
    Map<String, dynamic> arguments,
  ) {
    if (provider == 'teams') {
      final display = route['chat_display_title']?.toString().trim();
      if (display != null && display.isNotEmpty) {
        return display;
      }
    } else if (provider == 'telegram') {
      final display = route['chat_display_name']?.toString().trim();
      if (display != null && display.isNotEmpty) {
        return display;
      }
      final username = route['chat_username']?.toString().trim();
      if (username != null && username.isNotEmpty) {
        return '@$username';
      }
    } else {
      final display =
          (route['channel_display_name'] ?? arguments['channel_display_name'])
              ?.toString()
              .trim();
      if (display != null && display.isNotEmpty) {
        return display;
      }
    }
    return null;
  }
}

class PendingActionPlan {
  PendingActionPlan({
    required this.id,
    required this.status,
    required this.expiresAt,
    required this.actions,
  });

  final String id;
  final String status;
  final String expiresAt;
  final List<PendingAction> actions;

  factory PendingActionPlan.fromJson(Map<String, dynamic> json) {
    return PendingActionPlan(
      id: json['id'] as String,
      status: json['status'] as String,
      expiresAt: json['expires_at'] as String,
      actions: (json['actions'] as List<dynamic>)
          .map((e) => PendingAction.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }
}

class ActionPlanResponse {
  ActionPlanResponse({
    required this.id,
    required this.status,
    required this.expiresAt,
    required this.actions,
    this.result,
    this.failure,
  });

  final String id;
  final String status;
  final String expiresAt;
  final List<PendingAction> actions;
  final Map<String, dynamic>? result;
  final String? failure;

  factory ActionPlanResponse.fromJson(Map<String, dynamic> json) {
    final resultRaw = json['result'];
    return ActionPlanResponse(
      id: json['id'] as String,
      status: json['status'] as String,
      expiresAt: json['expires_at'] as String,
      actions: (json['actions'] as List<dynamic>)
          .map((e) => PendingAction.fromJson(e as Map<String, dynamic>))
          .toList(),
      result: resultRaw == null
          ? null
          : Map<String, dynamic>.from(resultRaw as Map),
      failure: json['failure'] as String?,
    );
  }

  /// Parses structured action-plan terminal responses; returns null for generic conflicts.
  static ActionPlanResponse? tryParse(Map<String, dynamic> json) {
    if (json.containsKey('detail') && !json.containsKey('actions')) {
      return null;
    }
    final id = json['id'];
    final status = json['status'];
    final expiresAt = json['expires_at'];
    final actions = json['actions'];
    if (id is! String ||
        status is! String ||
        expiresAt is! String ||
        actions is! List) {
      return null;
    }
    try {
      return ActionPlanResponse.fromJson(json);
    } catch (_) {
      return null;
    }
  }
}

class ActionPlanResumeResponse {
  ActionPlanResumeResponse({
    required this.answer,
    required this.affectedObjects,
  });

  final String answer;
  final List<AssistantAffectedObject> affectedObjects;

  factory ActionPlanResumeResponse.fromJson(Map<String, dynamic> json) {
    return ActionPlanResumeResponse(
      answer: json['answer'] as String,
      affectedObjects: (json['affected_objects'] as List<dynamic>)
          .map(
            (e) => AssistantAffectedObject.fromJson(e as Map<String, dynamic>),
          )
          .toList(),
    );
  }
}

class AssistantAffectedObject {
  AssistantAffectedObject({
    required this.objectId,
    required this.title,
    required this.kind,
    required this.state,
    this.status,
  });

  final String objectId;
  final String title;
  final String kind;
  final String state;
  final String? status;

  factory AssistantAffectedObject.fromJson(Map<String, dynamic> json) {
    return AssistantAffectedObject(
      objectId: json['object_id'] as String,
      title: json['title'] as String,
      kind: json['kind'] as String,
      state: json['state'] as String,
      status: json['status'] as String?,
    );
  }

  String get lifecycleLabel {
    if (status != null && status!.trim().isNotEmpty) {
      return status!;
    }
    return state;
  }

  String get displayLabel => '$kind: $title — $lifecycleLabel';
}

class AssistantContextRef {
  const AssistantContextRef({
    required this.id,
    required this.title,
    required this.kind,
  });

  final String id;
  final String title;
  final String kind;

  String get displayLabel => '$kind — $title';
}

class SearchResultSnippet {
  static String fromBody(String? body, {int maxChars = 200}) {
    if (body == null || body.trim().isEmpty) {
      return '';
    }
    final normalized = body.replaceAll(RegExp(r'\s+'), ' ').trim();
    if (normalized.length <= maxChars) {
      return normalized;
    }
    return '${normalized.substring(0, maxChars)}…';
  }
}

extension SecretaryObjectLifecycle on SecretaryObject {
  String get lifecycleLabel {
    if (status != null && status!.trim().isNotEmpty) {
      if (status == 'completed') {
        return 'completed';
      }
      return status!;
    }
    return state;
  }

  bool get isDeletedTask => kind == 'task' && status == 'deleted';

  bool get isTombstoned => deletedAt != null;
}

class GraphWorkspaceOut {
  GraphWorkspaceOut({
    this.rootId,
    required this.seedIds,
    required this.nodes,
    required this.edges,
    required this.truncated,
  });

  final String? rootId;
  final List<String> seedIds;
  final List<SecretaryObject> nodes;
  final List<SecretaryEdge> edges;
  final bool truncated;

  factory GraphWorkspaceOut.fromJson(Map<String, dynamic> json) {
    return GraphWorkspaceOut(
      rootId: json['root_id'] as String?,
      seedIds: (json['seed_ids'] as List<dynamic>)
          .map((e) => e as String)
          .toList(),
      nodes: (json['nodes'] as List<dynamic>)
          .map((e) => SecretaryObject.fromJson(e as Map<String, dynamic>))
          .toList(),
      edges: (json['edges'] as List<dynamic>)
          .map((e) => SecretaryEdge.fromJson(e as Map<String, dynamic>))
          .toList(),
      truncated: json['truncated'] as bool? ?? false,
    );
  }
}

class OpenTarget {
  OpenTarget({
    required this.available,
    required this.action,
    required this.label,
    this.url,
    this.deviceKey,
    this.localPath,
    this.reason,
  });

  final bool available;
  final String action;
  final String label;
  final String? url;
  final String? deviceKey;
  final String? localPath;
  final String? reason;

  factory OpenTarget.fromJson(Map<String, dynamic> json) {
    return OpenTarget(
      available: json['available'] as bool? ?? false,
      action: json['action'] as String? ?? 'unavailable',
      label: json['label'] as String? ?? 'Открыть в источнике',
      url: json['url'] as String?,
      deviceKey: json['device_key'] as String?,
      localPath: json['local_path'] as String?,
      reason: json['reason'] as String?,
    );
  }
}

class ClientFileIntakeResult {
  ClientFileIntakeResult({
    required this.objectId,
    required this.status,
    required this.jobsEnqueued,
    required this.representationsCreated,
    required this.metadataOnly,
  });

  final String objectId;
  final String status;
  final int jobsEnqueued;
  final int representationsCreated;
  final bool metadataOnly;

  factory ClientFileIntakeResult.fromJson(Map<String, dynamic> json) {
    return ClientFileIntakeResult(
      objectId: json['object_id'] as String,
      status: json['status'] as String,
      jobsEnqueued: json['jobs_enqueued'] as int? ?? 0,
      representationsCreated: json['representations_created'] as int? ?? 0,
      metadataOnly: json['metadata_only'] as bool? ?? false,
    );
  }
}

class ClientFolderIntakeResult {
  ClientFolderIntakeResult({required this.objectId, required this.status});

  final String objectId;
  final String status;

  factory ClientFolderIntakeResult.fromJson(Map<String, dynamic> json) {
    return ClientFolderIntakeResult(
      objectId: json['object_id'] as String,
      status: json['status'] as String,
    );
  }
}

class IntakeLinkResult {
  IntakeLinkResult({
    required this.objectId,
    required this.provider,
    required this.kind,
    required this.status,
    required this.contentStatus,
    required this.contentJobsEnqueued,
  });

  final String objectId;
  final String provider;
  final String kind;
  final String status;
  final String contentStatus;
  final int contentJobsEnqueued;

  factory IntakeLinkResult.fromJson(Map<String, dynamic> json) {
    return IntakeLinkResult(
      objectId: json['object_id'] as String,
      provider: json['provider'] as String,
      kind: json['kind'] as String,
      status: json['status'] as String,
      contentStatus: json['content_status'] as String,
      contentJobsEnqueued: json['content_jobs_enqueued'] as int,
    );
  }
}

class LocalDeviceRegisterResult {
  LocalDeviceRegisterResult({
    required this.deviceId,
    required this.deviceKey,
    required this.displayName,
    required this.created,
  });

  final String deviceId;
  final String deviceKey;
  final String displayName;
  final bool created;

  factory LocalDeviceRegisterResult.fromJson(Map<String, dynamic> json) {
    return LocalDeviceRegisterResult(
      deviceId: json['device_id'] as String,
      deviceKey: json['device_key'] as String,
      displayName: json['display_name'] as String,
      created: json['created'] as bool? ?? false,
    );
  }
}

class TaskPatchRequest {
  String? title;
  bool titleSet = false;
  String? body;
  bool bodySet = false;
  String? dueAt;
  bool dueAtSet = false;

  bool get isEmpty => !titleSet && !bodySet && !dueAtSet;

  Map<String, dynamic> toJson() {
    final result = <String, dynamic>{};
    if (titleSet) {
      result['title'] = title;
    }
    if (bodySet) {
      result['body'] = body;
    }
    if (dueAtSet) {
      result['due_at'] = dueAt;
    }
    return result;
  }
}

class TaskMutationResponse {
  TaskMutationResponse({required this.object, required this.changed});

  final SecretaryObject object;
  final bool changed;

  factory TaskMutationResponse.fromJson(Map<String, dynamic> json) {
    return TaskMutationResponse(
      object: SecretaryObject.fromJson(json['object'] as Map<String, dynamic>),
      changed: json['changed'] as bool? ?? false,
    );
  }
}

class TaskStatusResponse {
  TaskStatusResponse({
    required this.object,
    required this.changed,
    this.previousStatus,
    required this.newStatus,
  });

  final SecretaryObject object;
  final bool changed;
  final String? previousStatus;
  final String newStatus;

  factory TaskStatusResponse.fromJson(Map<String, dynamic> json) {
    return TaskStatusResponse(
      object: SecretaryObject.fromJson(json['object'] as Map<String, dynamic>),
      changed: json['changed'] as bool? ?? false,
      previousStatus: json['previous_status'] as String?,
      newStatus: json['new_status'] as String,
    );
  }
}

class ObjectDeleteResponse {
  ObjectDeleteResponse({
    required this.objectId,
    required this.deletedAt,
    required this.alreadyDeleted,
  });

  final String objectId;
  final String deletedAt;
  final bool alreadyDeleted;

  factory ObjectDeleteResponse.fromJson(Map<String, dynamic> json) {
    return ObjectDeleteResponse(
      objectId: json['object_id'] as String,
      deletedAt: json['deleted_at'] as String,
      alreadyDeleted: json['already_deleted'] as bool? ?? false,
    );
  }
}

class RelationCreateResponse {
  RelationCreateResponse({required this.edge, required this.created});

  final SecretaryEdge edge;
  final bool created;

  factory RelationCreateResponse.fromJson(Map<String, dynamic> json) {
    return RelationCreateResponse(
      edge: SecretaryEdge.fromJson(json['edge'] as Map<String, dynamic>),
      created: json['created'] as bool? ?? false,
    );
  }
}

class RelationDecisionResponse {
  RelationDecisionResponse({required this.edge});

  final SecretaryEdge edge;

  factory RelationDecisionResponse.fromJson(Map<String, dynamic> json) {
    return RelationDecisionResponse(
      edge: SecretaryEdge.fromJson(json['edge'] as Map<String, dynamic>),
    );
  }
}

class SearchFacetValue {
  SearchFacetValue({required this.value, required this.count});

  final String value;
  final int count;

  factory SearchFacetValue.fromJson(Map<String, dynamic> json) {
    return SearchFacetValue(
      value: json['value'] as String,
      count: json['count'] as int,
    );
  }
}

class SearchFacetsOut {
  SearchFacetsOut({required this.kinds, required this.providers});

  final List<SearchFacetValue> kinds;
  final List<SearchFacetValue> providers;

  factory SearchFacetsOut.fromJson(Map<String, dynamic> json) {
    return SearchFacetsOut(
      kinds: (json['kinds'] as List<dynamic>)
          .map((row) => SearchFacetValue.fromJson(row as Map<String, dynamic>))
          .toList(),
      providers: (json['providers'] as List<dynamic>)
          .map((row) => SearchFacetValue.fromJson(row as Map<String, dynamic>))
          .toList(),
    );
  }
}

/// Recurring account sources with per-user sync preferences (PHASE 28C-A).
const List<String> supportedSourcePreferenceKeys = [
  'gmail',
  'google_calendar',
  'yandex_mail',
  'yandex_calendar',
  'mattermost',
  'teams',
];

class SourcePreference {
  SourcePreference({
    required this.source,
    required this.enabled,
    required this.syncIntervalSeconds,
    required this.defaultSyncIntervalSeconds,
    required this.minSyncIntervalSeconds,
    required this.maxSyncIntervalSeconds,
    required this.historyDays,
    required this.defaultHistoryDays,
    required this.minHistoryDays,
    required this.maxHistoryDays,
  });

  final String source;
  final bool enabled;
  final int syncIntervalSeconds;
  final int defaultSyncIntervalSeconds;
  final int minSyncIntervalSeconds;
  final int maxSyncIntervalSeconds;
  final int historyDays;
  final int defaultHistoryDays;
  final int minHistoryDays;
  final int maxHistoryDays;

  factory SourcePreference.fromJson(Map<String, dynamic> json) {
    return SourcePreference(
      source: json['source'] as String,
      enabled: json['enabled'] as bool,
      syncIntervalSeconds: json['sync_interval_seconds'] as int,
      defaultSyncIntervalSeconds: json['default_sync_interval_seconds'] as int,
      minSyncIntervalSeconds: json['min_sync_interval_seconds'] as int,
      maxSyncIntervalSeconds: json['max_sync_interval_seconds'] as int,
      historyDays: json['history_days'] as int,
      defaultHistoryDays: json['default_history_days'] as int,
      minHistoryDays: json['min_history_days'] as int,
      maxHistoryDays: json['max_history_days'] as int,
    );
  }
}

class SourcePreferenceList {
  SourcePreferenceList({required this.preferences});

  final List<SourcePreference> preferences;

  factory SourcePreferenceList.fromJson(Map<String, dynamic> json) {
    return SourcePreferenceList(
      preferences: (json['preferences'] as List<dynamic>)
          .map((e) => SourcePreference.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }
}

class LabelItem {
  LabelItem({
    required this.id,
    required this.title,
    this.description,
    this.objectCount = 0,
    this.createdAt,
    this.updatedAt,
  });

  final String id;
  final String title;
  final String? description;
  final int objectCount;
  final String? createdAt;
  final String? updatedAt;

  factory LabelItem.fromJson(Map<String, dynamic> json) {
    return LabelItem(
      id: json['id'] as String,
      title: json['title'] as String,
      description: json['description'] as String?,
      objectCount: (json['object_count'] as num?)?.toInt() ?? 0,
      createdAt: json['created_at'] as String?,
      updatedAt: json['updated_at'] as String?,
    );
  }
}

class LabelList {
  LabelList({required this.labels});

  final List<LabelItem> labels;

  factory LabelList.fromJson(Map<String, dynamic> json) {
    return LabelList(
      labels: (json['labels'] as List<dynamic>)
          .map((e) => LabelItem.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }
}

class LabelWriteResult {
  LabelWriteResult({required this.label, this.created, this.changed});

  final LabelItem label;
  final bool? created;
  final bool? changed;

  factory LabelWriteResult.fromJson(Map<String, dynamic> json) {
    return LabelWriteResult(
      label: LabelItem.fromJson(json['label'] as Map<String, dynamic>),
      created: json['created'] as bool?,
      changed: json['changed'] as bool?,
    );
  }
}

class ObjectLabels {
  ObjectLabels({required this.labels});

  final List<LabelItem> labels;

  factory ObjectLabels.fromJson(Map<String, dynamic> json) {
    return ObjectLabels(
      labels: (json['labels'] as List<dynamic>)
          .map((e) => LabelItem.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }
}

class AssignLabelResult {
  AssignLabelResult({
    required this.objectId,
    required this.labelId,
    required this.created,
  });

  final String objectId;
  final String labelId;
  final bool created;

  factory AssignLabelResult.fromJson(Map<String, dynamic> json) {
    return AssignLabelResult(
      objectId: json['object_id'] as String,
      labelId: json['label_id'] as String,
      created: json['created'] as bool,
    );
  }
}

class RemoveLabelResult {
  RemoveLabelResult({
    required this.objectId,
    required this.labelId,
    required this.changed,
  });

  final String objectId;
  final String labelId;
  final bool changed;

  factory RemoveLabelResult.fromJson(Map<String, dynamic> json) {
    return RemoveLabelResult(
      objectId: json['object_id'] as String,
      labelId: json['label_id'] as String,
      changed: json['changed'] as bool,
    );
  }
}
