import '../api/api_models.dart';
import 'date_format.dart';

String? objectPrimaryDateIso(SecretaryObject object) {
  switch (object.kind) {
    case 'task':
      return object.dueAt;
    case 'event':
    case 'calendar_event':
    case 'temporal_hint':
      return object.startAt;
    case 'email':
    case 'message':
    case 'chat':
      return object.occurredAt ?? object.updatedAt;
    case 'file':
    case 'document':
    case 'dataset':
      final modified = object.metadata['modified_at'];
      if (modified is String && modified.trim().isNotEmpty) {
        return modified;
      }
      return object.occurredAt ?? object.updatedAt;
    default:
      return object.occurredAt ?? object.updatedAt;
  }
}

String objectPrimaryDateLabel(SecretaryObject object) {
  final iso = objectPrimaryDateIso(object);
  if (iso == null || iso.trim().isEmpty) {
    return '';
  }
  final formatted = formatUserDateTime(iso);
  if (object.kind == 'task') {
    return 'Срок: $formatted';
  }
  return formatted;
}

String objectPrimaryDateFieldLabel(SecretaryObject object) {
  switch (object.kind) {
    case 'task':
      return 'Срок';
    case 'event':
    case 'calendar_event':
    case 'temporal_hint':
      return 'Начало';
    case 'email':
    case 'message':
    case 'chat':
      return 'Дата';
    case 'file':
    case 'document':
    case 'dataset':
      return 'Изменено';
    default:
      return 'Дата';
  }
}

String objectPrimaryDateDisplayValue(SecretaryObject object) {
  final iso = objectPrimaryDateIso(object);
  if (iso == null || iso.trim().isEmpty) {
    return '';
  }
  return formatUserDateTime(iso);
}

String? objectPlannedIntervalDisplayValue(SecretaryObject object) {
  if (object.kind != 'task') {
    return null;
  }
  final startIso = object.plannedStartAt;
  final endIso = object.plannedEndAt;
  if (startIso == null ||
      startIso.trim().isEmpty ||
      endIso == null ||
      endIso.trim().isEmpty) {
    return null;
  }
  final start = DateTime.tryParse(startIso);
  final end = DateTime.tryParse(endIso);
  if (start == null || end == null) {
    return null;
  }
  return formatPlannedExecutionInterval(start: start, end: end);
}
