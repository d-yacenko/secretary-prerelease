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
