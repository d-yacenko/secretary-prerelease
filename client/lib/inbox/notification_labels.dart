import '../api/api_models.dart';
import '../ui/domain_labels.dart';

const Map<String, String> _notificationPriorityLabels = {
  'low': 'Низкий',
  'normal': 'Обычный',
  'high': 'Высокий',
  'urgent': 'Срочный',
};

const Map<String, String> _notificationProposalTypeLabels = {
  'task': 'Задача',
  'deadline': 'Срок',
  'meeting': 'Встреча',
  'relation': 'Связь',
  'note': 'Заметка',
};

const Map<String, String> _notificationProposedActionLabels = {
  'create_task': 'Создать задачу',
};

String _fallback(String value) => value;

String notificationPriorityLabel(String priority) =>
    _notificationPriorityLabels[priority] ?? _fallback(priority);

String notificationProposalTypeLabel(String type) =>
    _notificationProposalTypeLabels[type] ?? _fallback(type);

String notificationProposedActionLabel(String action) =>
    _notificationProposedActionLabels[action] ?? _fallback(action);

String notificationEvidenceLabel(NotificationOut notification) {
  final evidence = notification.proposal['evidence'];
  if (evidence is List && evidence.isNotEmpty) {
    final first = evidence.first;
    if (first is Map<String, dynamic>) {
      final parts = <String>[];
      final kind = first['kind'] as String?;
      final title = first['title'] as String?;
      final why = first['why_included'] as String?;
      if (kind != null && kind.isNotEmpty) {
        parts.add(objectKindLabel(kind));
      }
      if (title != null && title.isNotEmpty) {
        parts.add(title);
      }
      if (parts.isNotEmpty) {
        return parts.join(' / ');
      }
      if (why != null && why.isNotEmpty) {
        return why;
      }
    }
  }

  final proposalType = notification.proposalType;
  if (proposalType != null && proposalType.isNotEmpty) {
    return notificationProposalTypeLabel(proposalType);
  }
  return 'Уведомление';
}

bool notificationIsUrgent(NotificationOut notification) {
  return notification.priority == 'urgent' || notification.priority == 'high';
}
