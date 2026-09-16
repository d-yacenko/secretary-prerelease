import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';

void main() {
  test('TaskPatchRequest omits unset fields and preserves explicit null', () {
    final clearBody = TaskPatchRequest();
    clearBody.bodySet = true;
    clearBody.body = null;
    expect(clearBody.toJson(), {'body': null});
    expect(clearBody.toJson().containsKey('title'), isFalse);

    final titleOnly = TaskPatchRequest();
    titleOnly.title = 'Renamed';
    titleOnly.titleSet = true;
    expect(titleOnly.toJson(), {'title': 'Renamed'});
  });

  test('getGraphWorkspace parses workspace response', () async {
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        expect(request.url.path, '/graph/workspace');
        return http.Response(
          jsonEncode({
            'root_id': 'root-1',
            'seed_ids': ['seed-1'],
            'nodes': [
              {
                'id': 'root-1',
                'kind': 'task',
                'title': 'Root',
                'body': null,
                'provider': null,
                'external_id': null,
                'canonical_uri': null,
                'status': 'open',
                'start_at': null,
                'due_at': null,
                'metadata': {},
                'origin': 'user',
                'state': 'confirmed',
                'confidence': null,
                'created_at': '2026-01-01T00:00:00Z',
                'updated_at': '2026-01-01T00:00:00Z',
              },
            ],
            'edges': [],
            'truncated': false,
          }),
          200,
        );
      }),
    );
    client.configure(baseUrl: 'https://example.com', token: 'token');
    final workspace = await client.getGraphWorkspace(rootId: 'root-1');
    expect(workspace.rootId, 'root-1');
    expect(workspace.nodes.single.title, 'Root');
  });

  test('softDeleteTask uses DELETE /tasks path', () async {
  String? path;
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        path = request.url.path;
        return http.Response(
          jsonEncode({
            'object': {
              'id': 'task-1',
              'kind': 'task',
              'title': 'Deleted',
              'body': null,
              'provider': null,
              'external_id': null,
              'canonical_uri': null,
              'status': 'deleted',
              'start_at': null,
              'due_at': null,
              'metadata': {},
              'origin': 'user',
              'state': 'confirmed',
              'confidence': null,
              'created_at': '2026-01-01T00:00:00Z',
              'updated_at': '2026-01-01T00:00:00Z',
            },
            'changed': true,
            'previous_status': 'open',
            'new_status': 'deleted',
          }),
          200,
        );
      }),
    );
    client.configure(baseUrl: 'https://example.com', token: 'token');
    await client.softDeleteTask('task-1');
    expect(path, '/tasks/task-1');
  });
}
