import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_error.dart';
import 'package:personal_secretary/api/role_import_models.dart';

import '../test_secretary_api_client.dart';

void main() {
  test('prepare posts exact selections and parses presentation', () async {
    late Map<String, dynamic> body;
    final client = testSecretaryApiClient(
      MockClient((request) async {
        body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(request.url.path, '/people/role-import/action-plan');
        return http.Response(
          jsonEncode({
            'id': 'plan-1',
            'status': 'pending',
            'expires_at': '2099-01-01T00:00:00Z',
            'actions': [
              {
                'tool_name': 'apply_role_import_batch',
                'arguments': {'operation_id': 'hidden'},
                'presentation': {
                  'source_title': 'Договор',
                  'selected_count': 1,
                  'total_extracted_rows': 2,
                },
              },
            ],
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      }),
    );
    client.configure(baseUrl: 'https://example.com', token: 'secret-token');

    final response = await client.prepareRoleImportActionPlan(
      preview: RoleImportPreview(
        sourceObjectId: 'obj-1',
        sourceRevision: 'rev-1',
        sourceKind: 'text',
        sourceTruncated: false,
        itemsTruncated: false,
        items: [
          RoleImportPreviewItem(
            personName: 'Ольга',
            role: 'директор',
            evidenceText: 'Ольга — директор',
          ),
        ],
      ),
      groundingRevision: 'ground-1',
      selections: [
        RoleImportBatchSelection(rowIndex: 0, personId: 'p1'),
      ],
    );

    expect(body.keys.toSet(), {
      'source_object_id',
      'source_revision',
      'grounding_revision',
      'items_truncated',
      'items',
      'selections',
    });
    expect(body['selections'], [
      {'row_index': 0, 'person_id': 'p1'},
    ]);
    expect(response.actions.single.presentation?['source_title'], 'Договор');
    expect(response.status, 'pending');
  });

  test('approve and reject reuse action-plan routes', () async {
    final paths = <String>[];
    final client = testSecretaryApiClient(
      MockClient((request) async {
        paths.add(request.url.path);
        return http.Response(
          jsonEncode({
            'id': 'plan-1',
            'status': request.url.path.endsWith('reject')
                ? 'rejected'
                : 'executed',
            'expires_at': '2099-01-01T00:00:00Z',
            'actions': const [],
            'result': request.url.path.endsWith('approve')
                ? {
                    'actions': [
                      {
                        'output': {'changed': true},
                      },
                    ],
                  }
                : null,
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      }),
    );
    client.configure(baseUrl: 'https://example.com', token: 'secret-token');

    final approved = await client.approveActionPlan('plan-1');
    final rejected = await client.rejectActionPlan('plan-1');

    expect(paths, [
      '/assistant/action-plans/plan-1/approve',
      '/assistant/action-plans/plan-1/reject',
    ]);
    expect(approved.status, 'executed');
    expect(rejected.status, 'rejected');
  });

  test('prepare maps stale detail to a validation message', () async {
    final client = testSecretaryApiClient(
      MockClient(
        (request) async => http.Response(
          jsonEncode({'detail': 'role_import_source_changed'}),
          422,
          headers: {'content-type': 'application/json'},
        ),
      ),
    );
    client.configure(baseUrl: 'https://example.com', token: 'secret-token');

    expect(
      () => client.prepareRoleImportActionPlan(
        preview: RoleImportPreview(
          sourceObjectId: 'obj-1',
          sourceRevision: 'rev-1',
          sourceKind: 'text',
          sourceTruncated: false,
          itemsTruncated: false,
          items: <RoleImportPreviewItem>[],
        ),
        groundingRevision: 'ground-1',
        selections: <RoleImportBatchSelection>[],
      ),
      throwsA(
        isA<ValidationException>().having(
          (error) => error.message,
          'message',
          'role_import_source_changed',
        ),
      ),
    );
  });
}
