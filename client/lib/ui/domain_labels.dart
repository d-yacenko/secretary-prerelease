import '../api/api_models.dart';
import 'object_presentation.dart' show objectKindLabel;

export 'object_presentation.dart' show objectKindLabel;

const Map<String, String> _taskStatusLabels = {
  'open': 'Открыта',
  'in_progress': 'В работе',
  'done': 'Выполнена',
  'completed': 'Выполнена',
  'cancelled': 'Отменена',
  'archived': 'В архиве',
  'deleted': 'Удалена',
  'proposed': 'Предложено',
};

const Map<String, String> _provenanceStateLabels = {
  'confirmed': 'Подтверждено',
  'proposed': 'Предложено',
  'rejected': 'Отклонено',
  'observed': 'Наблюдено',
};

const Map<String, String> _relationTypeLabels = {
  'related_to': 'Связано с',
  'references': 'Ссылается на',
  'depends_on': 'Зависит от',
  'requested_by': 'Запросил',
  'delegated_to': 'Поручено',
  'waiting_on': 'Ждём',
  'involves': 'Участвует',
  'contains': 'Содержит',
  'labeled_with': 'Метка',
  'temporal_evidence': 'Временное свидетельство',
  'temporal_confirmation': 'Подтверждено календарём',
};

const Map<String, String> _originLabels = {
  'user': 'Пользователь',
  'agent': 'Агент',
  'source': 'Источник',
  'system': 'Секретарь',
};

const Map<String, String> _neighborDirectionLabels = {
  'incoming': 'входящая',
  'outgoing': 'исходящая',
};

String _fallback(String value) => value;

String taskStatusLabel(String? status) {
  if (status == null || status.trim().isEmpty) {
    return 'Открыта';
  }
  return _taskStatusLabels[status] ?? _fallback(status);
}

String provenanceStateLabel(String state) =>
    _provenanceStateLabels[state] ?? _fallback(state);

String relationTypeLabel(String type) =>
    _relationTypeLabels[type] ?? _fallback(type);

const String dependentTasksLabel = 'От неё зависят';
const String taskEvidenceSectionLabel = 'Основание';

String operationalStateLabel(String state) {
  switch (state) {
    case 'blocked':
      return 'Заблокировано';
    case 'waiting':
      return 'Ждём';
    case 'delegated':
      return 'Поручено';
    case 'scheduled_later':
      return 'Запланировано позже';
    case 'actionable':
      return 'Можно действовать';
    default:
      return '';
  }
}

String taskRelationProposalLabel(String origin, String state) {
  if (state == 'proposed' && origin == 'agent') {
    return 'Предложено секретарём';
  }
  if (state == 'proposed') {
    return 'Предложено';
  }
  return '';
}

String originLabel(String origin) =>
    _originLabels[origin] ?? _fallback(origin);

String neighborDirectionLabel(String direction) =>
    _neighborDirectionLabels[direction] ?? _fallback(direction);

String objectLifecycleDisplayLabel(SecretaryObject object) {
  if (object.kind == 'task') {
    return taskStatusLabel(object.status);
  }
  return provenanceStateLabel(object.state);
}

String affectedObjectDisplayLabel(AssistantAffectedObject affected) {
  final kind = objectKindLabel(affected.kind);
  final lifecycle = affected.kind == 'task'
      ? taskStatusLabel(affected.status)
      : affected.status != null && affected.status!.trim().isNotEmpty
          ? taskStatusLabel(affected.status)
          : provenanceStateLabel(affected.state);
  return '$kind: ${affected.title} — $lifecycle';
}

String objectSummaryLabel(SecretaryObject object) {
  final kind = objectKindLabel(object.kind);
  final lifecycle = objectLifecycleDisplayLabel(object);
  return '$kind • $lifecycle • ${provenanceStateLabel(object.state)}';
}

String searchKindFilterLabel(String? kind) {
  if (kind == null) {
    return 'Все типы';
  }
  return objectKindLabel(kind);
}

String connectionStatusLabel(bool connected) =>
    connected ? 'подключено' : 'не подключено';
