import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';

void main() {
  test('SecretaryObject parses occurred_at', () {
    final object = SecretaryObject.fromJson({
      'id': 'e1',
      'kind': 'email',
      'title': 'Mail',
      'body': null,
      'provider': 'gmail',
      'external_id': null,
      'canonical_uri': null,
      'status': null,
      'start_at': null,
      'due_at': null,
      'occurred_at': '2026-08-30T15:43:00Z',
      'metadata': {},
      'origin': 'source',
      'state': 'observed',
      'confidence': null,
      'created_at': '2026-08-28T08:00:00Z',
      'updated_at': '2026-08-28T08:00:00Z',
    });
    expect(object.occurredAt, '2026-08-30T15:43:00Z');
  });

  test('legacy response without occurred_at remains safe', () {
    final object = SecretaryObject.fromJson({
      'id': 'e1',
      'kind': 'email',
      'title': 'Mail',
      'body': null,
      'provider': 'gmail',
      'external_id': null,
      'canonical_uri': null,
      'status': null,
      'start_at': null,
      'due_at': null,
      'metadata': {},
      'origin': 'source',
      'state': 'observed',
      'confidence': null,
      'created_at': '2026-08-28T08:00:00Z',
      'updated_at': '2026-08-28T08:00:00Z',
    });
    expect(object.occurredAt, isNull);
  });
}
