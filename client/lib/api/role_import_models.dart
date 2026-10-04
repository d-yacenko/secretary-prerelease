enum RoleImportFlowPhase {
  editing,
  preparing,
  pending,
  approving,
  rejecting,
  executed,
  rejected,
  expired,
  failed,
}

class RoleImportRowChoice {
  bool selected = false;
  String? personId;
  String? promotionCandidateKey;
}

class RoleImportBatchSelection {
  RoleImportBatchSelection({
    required this.rowIndex,
    this.personId,
    this.promotionCandidateKey,
  });

  final int rowIndex;
  final String? personId;
  final String? promotionCandidateKey;

  Map<String, dynamic> toJson() {
    return {
      'row_index': rowIndex,
      if (personId != null) 'person_id': personId,
      if (promotionCandidateKey != null)
        'promotion_candidate_key': promotionCandidateKey,
    };
  }
}

class RoleImportPreviewItem {
  RoleImportPreviewItem({
    required this.personName,
    required this.role,
    this.contextText,
    required this.evidenceText,
    this.sourceLocator,
  });

  final String personName;
  final String role;
  final String? contextText;
  final String evidenceText;
  final String? sourceLocator;

  factory RoleImportPreviewItem.fromJson(Map<String, dynamic> json) {
    return RoleImportPreviewItem(
      personName: json['person_name'] as String,
      role: json['role'] as String,
      contextText: json['context'] as String?,
      evidenceText: json['evidence_text'] as String,
      sourceLocator: json['source_locator'] as String?,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'person_name': personName,
      'role': role,
      'context': contextText,
      'evidence_text': evidenceText,
      'source_locator': sourceLocator,
    };
  }
}

class RoleImportPreview {
  RoleImportPreview({
    required this.sourceObjectId,
    required this.sourceRevision,
    required this.sourceKind,
    required this.sourceTruncated,
    required this.itemsTruncated,
    required this.items,
  });

  final String sourceObjectId;
  final String sourceRevision;
  final String sourceKind;
  final bool sourceTruncated;
  final bool itemsTruncated;
  final List<RoleImportPreviewItem> items;

  factory RoleImportPreview.fromJson(Map<String, dynamic> json) {
    final rawItems = json['items'];
    return RoleImportPreview(
      sourceObjectId: json['source_object_id'] as String,
      sourceRevision: json['source_revision'] as String,
      sourceKind: json['source_kind'] as String,
      sourceTruncated: json['source_truncated'] as bool,
      itemsTruncated: json['items_truncated'] as bool,
      items: rawItems is List
          ? rawItems
              .map(
                (item) => RoleImportPreviewItem.fromJson(
                  item as Map<String, dynamic>,
                ),
              )
              .toList()
          : const [],
    );
  }
}

class RoleImportPersonCandidate {
  RoleImportPersonCandidate({
    required this.personId,
    required this.title,
    required this.reasons,
  });

  final String personId;
  final String title;
  final List<String> reasons;

  factory RoleImportPersonCandidate.fromJson(Map<String, dynamic> json) {
    return RoleImportPersonCandidate(
      personId: json['person_id'] as String,
      title: json['title'] as String? ?? '',
      reasons: _strings(json['reasons']),
    );
  }
}

class RoleImportPromotionCandidate {
  RoleImportPromotionCandidate({
    required this.candidateKey,
    required this.displayName,
    required this.provider,
    required this.directHitCount,
    this.evidenceKind = 'identity_participant',
    this.communicationObjectCount,
  });

  final String candidateKey;
  final String displayName;
  final String provider;
  final int directHitCount;
  final String evidenceKind;
  final int? communicationObjectCount;

  int get communicationCount => communicationObjectCount ?? directHitCount;

  factory RoleImportPromotionCandidate.fromJson(Map<String, dynamic> json) {
    return RoleImportPromotionCandidate(
      candidateKey: json['candidate_key'] as String,
      displayName: json['display_name'] as String? ?? '',
      provider: json['provider'] as String? ?? '',
      directHitCount: json['direct_hit_count'] as int? ?? 0,
      evidenceKind: json['evidence_kind'] as String? ?? 'identity_participant',
      communicationObjectCount: json['communication_object_count'] as int?,
    );
  }
}

class RoleImportPersonResolution {
  RoleImportPersonResolution({
    required this.state,
    this.personId,
    this.title,
    this.candidates = const [],
    this.promotionCandidates = const [],
  });

  final String state;
  final String? personId;
  final String? title;
  final List<RoleImportPersonCandidate> candidates;
  final List<RoleImportPromotionCandidate> promotionCandidates;

  factory RoleImportPersonResolution.fromJson(Map<String, dynamic> json) {
    return RoleImportPersonResolution(
      state: json['state'] as String? ?? '',
      personId: json['person_id'] as String?,
      title: json['title'] as String?,
      candidates: _maps(json['candidates'])
          .map(RoleImportPersonCandidate.fromJson)
          .toList(),
      promotionCandidates: _maps(json['promotion_candidates'])
          .map(RoleImportPromotionCandidate.fromJson)
          .toList(),
    );
  }
}

class RoleImportRoleResolution {
  RoleImportRoleResolution({
    required this.state,
    required this.displayText,
    this.roleTermId,
    this.suggestions = const [],
  });

  final String state;
  final String displayText;
  final String? roleTermId;
  final List<String> suggestions;

  factory RoleImportRoleResolution.fromJson(Map<String, dynamic> json) {
    return RoleImportRoleResolution(
      state: json['state'] as String? ?? '',
      displayText: json['display_text'] as String? ?? '',
      roleTermId: json['role_term_id'] as String?,
      suggestions: _strings(json['suggestions']),
    );
  }
}

class RoleImportGroundedItem {
  RoleImportGroundedItem({
    required this.rowIndex,
    required this.personName,
    required this.role,
    required this.evidenceText,
    required this.personResolution,
    required this.roleResolution,
    this.contextText,
    this.sourceLocator,
  });

  final int rowIndex;
  final String personName;
  final String role;
  final String? contextText;
  final String evidenceText;
  final String? sourceLocator;
  final RoleImportPersonResolution personResolution;
  final RoleImportRoleResolution roleResolution;

  factory RoleImportGroundedItem.fromJson(Map<String, dynamic> json) {
    return RoleImportGroundedItem(
      rowIndex: json['row_index'] as int? ?? 0,
      personName: json['person_name'] as String? ?? '',
      role: json['role'] as String? ?? '',
      contextText: json['context'] as String?,
      evidenceText: json['evidence_text'] as String? ?? '',
      sourceLocator: json['source_locator'] as String?,
      personResolution: RoleImportPersonResolution.fromJson(
        json['person_resolution'] as Map<String, dynamic>? ?? const {},
      ),
      roleResolution: RoleImportRoleResolution.fromJson(
        json['role_resolution'] as Map<String, dynamic>? ?? const {},
      ),
    );
  }
}

class RoleImportGroundedPreview {
  RoleImportGroundedPreview({
    required this.sourceObjectId,
    required this.sourceRevision,
    required this.sourceKind,
    required this.sourceTruncated,
    required this.itemsTruncated,
    required this.groundingRevision,
    required this.items,
  });

  final String sourceObjectId;
  final String sourceRevision;
  final String sourceKind;
  final bool sourceTruncated;
  final bool itemsTruncated;
  final String groundingRevision;
  final List<RoleImportGroundedItem> items;

  factory RoleImportGroundedPreview.fromJson(Map<String, dynamic> json) {
    return RoleImportGroundedPreview(
      sourceObjectId: json['source_object_id'] as String,
      sourceRevision: json['source_revision'] as String,
      sourceKind: json['source_kind'] as String,
      sourceTruncated: json['source_truncated'] as bool,
      itemsTruncated: json['items_truncated'] as bool,
      groundingRevision: json['grounding_revision'] as String,
      items: _maps(json['items']).map(RoleImportGroundedItem.fromJson).toList(),
    );
  }
}

List<Map<String, dynamic>> _maps(Object? raw) {
  if (raw is! List) {
    return const [];
  }
  return raw.whereType<Map<String, dynamic>>().toList();
}

List<String> _strings(Object? raw) {
  if (raw is! List) {
    return const [];
  }
  return raw.whereType<String>().toList();
}
