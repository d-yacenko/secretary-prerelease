import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_error.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/timezone/client_timezone_context.dart';

void main() {
  test('task-layout models parse and serialize replacement and topology', () {
    final snapshot = TaskLayoutSnapshot.tryParse({
      'topology_revision': 4,
      'snapshot_revision': 4,
      'algorithm_version': kTaskLayoutAlgorithmVersion,
      'usable': true,
      'centers': [
        {'task_id': 'task-a', 'world_x': 10, 'world_y': 20},
        {'task_id': 'task-b', 'world_x': 30.5, 'world_y': 40},
      ],
    });
    expect(snapshot, isNotNull);
    expect(snapshot!.matchesCurrentAlgorithm, isTrue);
    expect(snapshot.centers, hasLength(2));

    final replacement = TaskLayoutReplacement(
      expectedTopologyRevision: 4,
      algorithmVersion: kTaskLayoutAlgorithmVersion,
      centers: snapshot.centers,
    );
    expect(replacement.toJson(), {
      'expected_topology_revision': 4,
      'algorithm_version': 'task-map-v2.2',
      'centers': [
        {'task_id': 'task-a', 'world_x': 10, 'world_y': 20},
        {'task_id': 'task-b', 'world_x': 30.5, 'world_y': 40},
      ],
    });

    final topology = TaskLayoutTopology.tryParse({
      'topology_revision': 4,
      'tasks': [_taskJson('task-a')],
      'edges': [_edgeJson()],
    });
    expect(topology, isNotNull);
    expect(topology!.tasks.single.id, 'task-a');
    expect(topology.edges.single.type, 'related_to');

    expect(
      TaskLayoutSnapshot.tryParse({
        'topology_revision': 1,
        'snapshot_revision': null,
        'algorithm_version': null,
        'usable': false,
        'centers': [
          {'task_id': 'task-a', 'world_x': double.nan, 'world_y': 1},
        ],
      }),
      isNull,
    );
    expect(
      TaskLayoutSnapshot.tryParse({
        'topology_revision': 1,
        'usable': true,
        'centers': [
          {'task_id': 'task-a', 'world_x': 1, 'world_y': 1},
          {'task_id': 'task-a', 'world_x': 2, 'world_y': 2},
        ],
      }),
      isNull,
    );
    expect(
      TaskLayoutTopology.tryParse({
        'topology_revision': 1,
        'tasks': [_taskJson('task-a', kind: 'flow')],
        'edges': [],
      }),
      isNull,
    );
  });

  test('client reads and writes task-layout endpoints', () async {
    final calls = <String>[];
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        calls.add('${request.method} ${request.url.path}');
        if (request.method == 'GET' && request.url.path == '/graph/task-layout') {
          return _json({
            'topology_revision': 2,
            'snapshot_revision': 2,
            'algorithm_version': kTaskLayoutAlgorithmVersion,
            'usable': true,
            'centers': [
              {'task_id': 'task-a', 'world_x': 1, 'world_y': 2},
            ],
          });
        }
        if (request.method == 'PUT' && request.url.path == '/graph/task-layout') {
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['expected_topology_revision'], 3);
          expect(body['algorithm_version'], kTaskLayoutAlgorithmVersion);
          return _json({
            'topology_revision': 3,
            'snapshot_revision': 3,
            'algorithm_version': kTaskLayoutAlgorithmVersion,
            'usable': true,
            'centers': body['centers'],
          });
        }
        if (request.url.path == '/graph/task-layout/topology') {
          return _json({
            'topology_revision': 3,
            'tasks': [_taskJson('task-a')],
            'edges': [],
          });
        }
        return http.Response('missing', 404);
      }),
      timezoneProvider: const FixedClientTimezoneProvider(
        ClientTimezoneContext(zoneId: 'Europe/Amsterdam', utcOffsetMinutes: 120),
      ),
    );
    client.configure(baseUrl: 'https://example.com', token: 'token');

    final read = await client.getTaskLayout();
    expect(read!.centers.single.worldX, 1);
    final topology = await client.getTaskLayoutTopology();
    expect(topology!.topologyRevision, 3);
    final saved = await client.putTaskLayout(
      TaskLayoutReplacement(
        expectedTopologyRevision: 3,
        algorithmVersion: kTaskLayoutAlgorithmVersion,
        centers: [
          TaskLayoutCenter(taskId: 'task-a', worldX: 8, worldY: 9),
        ],
      ),
    );
    expect(saved!.centers.single.worldX, 8);
    expect(calls, [
      'GET /graph/task-layout',
      'GET /graph/task-layout/topology',
      'PUT /graph/task-layout',
    ]);
  });

  test('stale task-layout replace is a conflict', () async {
    final client = SecretaryApiClient(
      httpClient: MockClient(
        (_) async => http.Response('{"detail":"stale"}', 409),
      ),
      timezoneProvider: const FixedClientTimezoneProvider(
        ClientTimezoneContext(zoneId: 'Europe/Amsterdam', utcOffsetMinutes: 120),
      ),
    );
    client.configure(baseUrl: 'https://example.com', token: 'token');
    expect(
      client.putTaskLayout(
        TaskLayoutReplacement(
          expectedTopologyRevision: 1,
          algorithmVersion: kTaskLayoutAlgorithmVersion,
          centers: const [],
        ),
      ),
      throwsA(isA<ConflictException>()),
    );
  });
}

http.Response _json(Object body) {
  return http.Response(jsonEncode(body), 200, headers: {'content-type': 'application/json'});
}

Map<String, dynamic> _taskJson(String id, {String kind = 'task'}) {
  return {
    'id': id,
    'kind': kind,
    'title': id,
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
  };
}

Map<String, dynamic> _edgeJson() {
  return {
    'id': 'edge-1',
    'source_id': 'task-a',
    'target_id': 'task-b',
    'type': 'related_to',
    'origin': 'user',
    'confidence': null,
    'state': 'confirmed',
    'metadata': {},
    'created_at': '2026-01-01T00:00:00Z',
    'updated_at': '2026-01-01T00:00:00Z',
  };
}
