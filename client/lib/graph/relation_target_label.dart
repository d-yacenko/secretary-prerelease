import '../api/api_models.dart';

/// Presentation label for one Add-relation search row.
///
/// A Task title that is unique in [results] is returned unchanged.
/// A duplicated Task title is suffixed with the confirmed `part_of` parent
/// title from [confirmedParentTitleByTaskId], or `без родителя` when that
/// parent is absent. The suffix is display-only.
String relationTargetLabel({
  required SecretaryObject object,
  required List<SecretaryObject> results,
  required Map<String, String?> confirmedParentTitleByTaskId,
}) {
  if (!taskTitleIsDuplicated(object, results)) {
    return object.title;
  }
  final parent = confirmedParentTitleByTaskId[object.id]?.trim();
  if (parent == null || parent.isEmpty) {
    return '${object.title} (без родителя)';
  }
  return '${object.title} ($parent)';
}

/// Display key for duplicate detection. Stored titles are not rewritten.
String relationTargetDisplayKey(String title) {
  return title.trim().replaceAll(RegExp(r'\s+'), ' ').toLowerCase();
}

/// True when [object] is a Task whose display title matches another Task
/// in [results]. Comparison ignores case and repeated whitespace.
/// Non-tasks never count as duplicates.
bool taskTitleIsDuplicated(
  SecretaryObject object,
  List<SecretaryObject> results,
) {
  if (object.kind != 'task') {
    return false;
  }
  final key = relationTargetDisplayKey(object.title);
  var copies = 0;
  for (final item in results) {
    if (item.kind == 'task' && relationTargetDisplayKey(item.title) == key) {
      copies += 1;
      if (copies > 1) {
        return true;
      }
    }
  }
  return false;
}

/// Tasks in [results] whose titles are shared with another Task in that list.
List<SecretaryObject> tasksWithDuplicatedTitles(List<SecretaryObject> results) {
  return [
    for (final item in results)
      if (taskTitleIsDuplicated(item, results)) item,
  ];
}

/// Confirmed current `part_of` parent title. Proposed, rejected, and blank
/// parents are not established context.
String? confirmedPartOfParentTitle(TaskLinkItem? parent) {
  if (parent == null || parent.edgeState != 'confirmed') {
    return null;
  }
  final title = parent.title.trim();
  if (title.isEmpty) {
    return null;
  }
  return title;
}
