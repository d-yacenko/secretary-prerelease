import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';

void main() {
  const baseUrl = 'https://secretary.example';
  const token = 'opaque-test-token-abc123';

  Map<String, dynamic> labelJson({
    String id = '11111111-1111-1111-1111-111111111111',
    String title = 'Work',
    int objectCount = 2,
  }) {
    return {
      'id': id,
      'title': title,
      'object_count': objectCount,
      'created_at': '2026-09-07T00:00:00Z',
      'updated_at': '2026-09-07T00:00:00Z',
    };
  }

  test('list/create/rename/delete labels parse and send auth', () async {
    final seen = <http.Request>[];
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        seen.add(request);
        expect(request.headers['Authorization'], 'Bearer $token');
        if (request.method == 'GET' && request.url.path == '/labels') {
          expect(request.url.queryParameters['limit'], '100');
          return http.Response(jsonEncode({'labels': [labelJson()]}), 200);
        }
        if (request.method == 'POST' && request.url.path == '/labels') {
          expect(jsonDecode(request.body)['name'], 'Work');
          return http.Response(
            jsonEncode({'label': labelJson(), 'created': true}),
            200,
          );
        }
        if (request.method == 'PATCH') {
          expect(request.url.path, endsWith('/labels/11111111-1111-1111-1111-111111111111'));
          expect(jsonDecode(request.body)['name'], 'Office');
          return http.Response(
            jsonEncode({
              'label': labelJson(title: 'Office'),
              'changed': true,
            }),
            200,
          );
        }
        if (request.method == 'DELETE') {
          return http.Response(
            jsonEncode({'label': labelJson(), 'changed': true}),
            200,
          );
        }
        return http.Response('{}', 404);
      }),
    );
    client.configure(baseUrl: baseUrl, token: token);

    final listed = await client.listLabels();
      expect(listed.labels.single.title, 'Work');
    expect(listed.labels.single.objectCount, 2);
    expect(listed.labels.single.description, isNull);

    final created = await client.createLabel('Work');
    expect(created.created, isTrue);
    expect(created.label.id, '11111111-1111-1111-1111-111111111111');

    final renamed = await client.renameLabel(
      labelId: '11111111-1111-1111-1111-111111111111',
      name: 'Office',
    );
    expect(renamed.label.title, 'Office');

    final deleted = await client.deleteLabel(
      '11111111-1111-1111-1111-111111111111',
    );
    expect(deleted.changed, isTrue);
    expect(seen.length, 4);
  });

  test('parses optional description and sends description on create/update', () async {
    final seen = <http.Request>[];
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        seen.add(request);
        if (request.method == 'GET') {
          return http.Response(
            jsonEncode({
              'labels': [
                {
                  'id': '11111111-1111-1111-1111-111111111111',
                  'title': 'Work',
                  'description': 'office work',
                  'object_count': 1,
                },
              ],
            }),
            200,
          );
        }
        if (request.method == 'POST') {
          expect(jsonDecode(request.body)['description'], 'commercial');
          return http.Response(
            jsonEncode({
              'label': {
                'id': '11111111-1111-1111-1111-111111111111',
                'title': 'Work',
                'description': 'commercial',
                'object_count': 0,
              },
              'created': true,
            }),
            200,
          );
        }
        expect(jsonDecode(request.body)['description'], isNull);
        return http.Response(
          jsonEncode({
            'label': {
              'id': '11111111-1111-1111-1111-111111111111',
              'title': 'Work',
              'description': null,
              'object_count': 0,
            },
            'changed': true,
          }),
          200,
        );
      }),
    );
    client.configure(baseUrl: baseUrl, token: token);
    final listed = await client.listLabels();
    expect(listed.labels.single.description, 'office work');
    final created = await client.createLabel('Work', description: 'commercial');
    expect(created.label.description, 'commercial');
    final updated = await client.updateLabel(
      labelId: '11111111-1111-1111-1111-111111111111',
      descriptionSet: true,
    );
    expect(updated.label.description, isNull);
    expect(seen.length, 3);
  });

  test('get/assign/remove object labels', () async {
    const objectId = '22222222-2222-2222-2222-222222222222';
    const labelId = '11111111-1111-1111-1111-111111111111';
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        expect(request.headers['Authorization'], 'Bearer $token');
        if (request.method == 'GET') {
          expect(request.url.path, '/objects/$objectId/labels');
          return http.Response(jsonEncode({'labels': [labelJson()]}), 200);
        }
        if (request.method == 'POST') {
          expect(request.url.path, '/objects/$objectId/labels/$labelId');
          return http.Response(
            jsonEncode({
              'object_id': objectId,
              'label_id': labelId,
              'created': true,
            }),
            200,
          );
        }
        expect(request.method, 'DELETE');
        expect(request.url.path, '/objects/$objectId/labels/$labelId');
        return http.Response(
          jsonEncode({
            'object_id': objectId,
            'label_id': labelId,
            'changed': true,
          }),
          200,
        );
      }),
    );
    client.configure(baseUrl: baseUrl, token: token);
    final labels = await client.getObjectLabels(objectId);
    expect(labels.labels.single.title, 'Work');
    final assigned = await client.assignLabel(objectId: objectId, labelId: labelId);
    expect(assigned.created, isTrue);
    final removed = await client.removeObjectLabel(
      objectId: objectId,
      labelId: labelId,
    );
    expect(removed.changed, isTrue);
  });

  test('search sends encoded label_id', () async {
    const labelId = '11111111-1111-1111-1111-111111111111';
    late Uri captured;
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        captured = request.url;
        expect(request.headers['Authorization'], 'Bearer $token');
        return http.Response('[]', 200);
      }),
    );
    client.configure(baseUrl: baseUrl, token: token);
    await client.searchObjects(query: 'adh', labelId: labelId);
    expect(captured.path, '/search');
    expect(captured.queryParameters['q'], 'adh');
    expect(captured.queryParameters['label_id'], labelId);
  });
}
