import '../api/api_models.dart';

/// In-memory capture draft for manual task creation and context wiring.
class CaptureDraft {
  const CaptureDraft({
    this.text = '',
    this.title,
    this.contextObjectIds = const [],
    this.contextRefs = const [],
    this.dependsOnIds = const [],
    this.completionMode = 'finite',
    this.dueAt,
    this.plannedStartAt,
    this.plannedEndAt,
  });

  static const maxTextLength = 16000;
  static const maxTitleLength = 200;

  final String text;
  final String? title;
  final List<String> contextObjectIds;
  final List<CaptureContextRef> contextRefs;
  final List<String> dependsOnIds;
  final String completionMode;
  final DateTime? dueAt;
  final DateTime? plannedStartAt;
  final DateTime? plannedEndAt;

  bool get isBlank => text.trim().isEmpty;

  bool get isTextTooLong => text.length > maxTextLength;

  bool get isTitleTooLong => title != null && title!.length > maxTitleLength;

  bool get canSubmit => !isBlank && !isTextTooLong && !isTitleTooLong;

  bool get hasTaskIntent =>
      contextObjectIds.isNotEmpty || dependsOnIds.isNotEmpty;

  CaptureDraft copyWith({
    String? text,
    String? title,
    bool clearTitle = false,
    List<String>? contextObjectIds,
    List<CaptureContextRef>? contextRefs,
    List<String>? dependsOnIds,
    String? completionMode,
    DateTime? dueAt,
    bool clearDue = false,
    DateTime? plannedStartAt,
    DateTime? plannedEndAt,
    bool clearPlanned = false,
  }) {
    return CaptureDraft(
      text: text ?? this.text,
      title: clearTitle ? null : (title ?? this.title),
      contextObjectIds: contextObjectIds ?? this.contextObjectIds,
      contextRefs: contextRefs ?? this.contextRefs,
      dependsOnIds: dependsOnIds ?? this.dependsOnIds,
      completionMode: completionMode ?? this.completionMode,
      dueAt: clearDue ? null : (dueAt ?? this.dueAt),
      plannedStartAt: clearPlanned
          ? null
          : (plannedStartAt ?? this.plannedStartAt),
      plannedEndAt: clearPlanned ? null : (plannedEndAt ?? this.plannedEndAt),
    );
  }

  CaptureTaskRequest toRequest() {
    return CaptureTaskRequest(
      text: text,
      title: title,
      contextObjectIds: contextObjectIds,
      dependsOnIds: dependsOnIds,
      completionMode: completionMode,
      dueAt: _iso(dueAt),
      plannedStartAt: _iso(plannedStartAt),
      plannedEndAt: _iso(plannedEndAt),
    );
  }

  static String? _iso(DateTime? value) => value?.toUtc().toIso8601String();

  CaptureNoteRequest toNoteRequest() {
    return CaptureNoteRequest(text: text, title: title);
  }

  static const empty = CaptureDraft();
}
