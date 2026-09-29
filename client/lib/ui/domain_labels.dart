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
  'part_of': 'входит в',
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

String personCandidateExplanation(List<String> reasons) {
  if (reasons.contains('identity_conflict')) {
    return 'Этот контакт уже связан с другим человеком';
  }
  if (reasons.contains('name_similarity')) {
    return 'Имя в источнике похоже на имя этого человека';
  }
  if (reasons.contains('exact_identifier')) {
    return 'Точный идентификатор уже известен';
  }
  return 'Найдено в сохранённых сообщениях';
}

String personActorRoleLabel(String role) {
  switch (role) {
    case 'requested_by':
      return 'Просит выполнить';
    case 'delegated_to':
      return 'Поручена этому человеку';
    case 'waiting_on':
      return 'Ждём от этого человека';
    case 'involves':
      return 'Участвует';
    default:
      return role;
  }
}

String personTaskLinkChoiceLabel(String role) {
  switch (role) {
    case 'requested_by':
      return 'Этот человек попросил выполнить';
    case 'delegated_to':
      return 'Задача поручена этому человеку';
    case 'waiting_on':
      return 'Ждём от этого человека';
    case 'involves':
      return 'Этот человек участвует';
    default:
      return personActorRoleLabel(role);
  }
}

String personTaskLinkFact({
  required String role,
  required String personTitle,
  required String taskTitle,
}) {
  switch (role) {
    case 'requested_by':
      return '$personTitle просит выполнить задачу «$taskTitle»';
    case 'delegated_to':
      return 'Задача «$taskTitle» поручена человеку $personTitle';
    case 'waiting_on':
      return 'Ждём задачу «$taskTitle» от человека $personTitle';
    case 'involves':
      return '$personTitle участвует в задаче «$taskTitle»';
    default:
      return '$personTitle · $taskTitle';
  }
}

String personSalienceTierLabel(String tier) {
  switch (tier) {
    case 'focus':
      return 'В фокусе';
    case 'known':
      return 'Известен';
    case 'incidental':
      return 'Редко';
    default:
      return tier;
  }
}

String personSalienceComponentLabel(String name) {
  switch (name) {
    case 'directness':
      return 'Прямые диалоги';
    case 'reciprocity':
      return 'В обе стороны';
    case 'frequency':
      return 'Частота';
    case 'recency':
      return 'Недавность';
    case 'public_exposure':
      return 'Общие каналы';
    case 'user_attention':
      return 'Подтверждение';
    case 'task_calendar':
      return 'Задачи и календарь';
    default:
      return name;
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

String originLabel(String origin) => _originLabels[origin] ?? _fallback(origin);

String neighborDirectionLabel(String direction) =>
    _neighborDirectionLabels[direction] ?? _fallback(direction);

String objectLifecycleDisplayLabel(SecretaryObject object) {
  if (object.kind == 'task') {
    return taskStatusLabel(object.status);
  }
  return provenanceStateLabel(object.state);
}

/// Human Task/Direction label. Technical `kind` stays `task`.
String humanTaskModeLabel(SecretaryObject object) {
  if (object.kind != 'task') {
    return objectKindLabel(object.kind);
  }
  return object.isOngoingTask ? 'Направление' : 'Задача';
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
  final kind = humanTaskModeLabel(object);
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
