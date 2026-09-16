import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/inbox/notification_labels.dart';

NotificationOut _notification({
  String priority = 'high',
  Map<String, dynamic>? proposal,
}) {
  return NotificationOut.fromJson({
    'id': 'n1',
    'title': 'Test',
    'body': null,
    'priority': priority,
    'status': 'new',
    'source_object_id': null,
    'related_object_id': null,
    'result_object_id': null,
    'proposal': proposal ?? const {'type': 'task'},
    'read_at': null,
    'created_at': '2026-01-01T00:00:00Z',
    'updated_at': '2026-01-01T00:00:00Z',
  });
}

void main() {
  test('notification priority labels', () {
    expect(notificationPriorityLabel('urgent'), 'Срочный');
    expect(notificationPriorityLabel('normal'), 'Обычный');
    expect(notificationPriorityLabel('custom'), 'custom');
  });

  test('notification evidence uses object kind label', () {
    final label = notificationEvidenceLabel(
      _notification(
        proposal: {
          'type': 'task',
          'evidence': [
            {
              'kind': 'email',
              'title': 'Inbound',
            },
          ],
        },
      ),
    );
    expect(label, 'Письмо / Inbound');
  });

  test('notification evidence fallback', () {
    expect(notificationEvidenceLabel(_notification()), 'Задача');
    expect(
      notificationEvidenceLabel(
        _notification(proposal: {'type': 'unknown_kind'}),
      ),
      'unknown_kind',
    );
    expect(
      notificationEvidenceLabel(
        _notification(proposal: const {}),
      ),
      'Уведомление',
    );
  });

  test('notification proposed action label', () {
    expect(notificationProposedActionLabel('create_task'), 'Создать задачу');
    expect(notificationProposedActionLabel('custom_action'), 'custom_action');
  });
}
