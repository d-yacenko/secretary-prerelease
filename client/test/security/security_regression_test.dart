import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';

void main() {
  const token = 'secret-bearer-token-xyz';

  test('capture request payload has no user_id field', () async {
    Map<String, dynamic>? body;
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        body = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(
          jsonEncode({
            'task_id': 't1',
            'context_edge_ids': [],
            'dependency_edge_ids': [],
          }),
          201,
        );
      }),
    );
    client.configure(baseUrl: 'https://api.example', token: token);
    await client.captureTask(CaptureTaskRequest(text: 'hello'));
    expect(body!.containsKey('user_id'), isFalse);
  });

  test('authenticated requests keep token in Authorization header only', () async {
    Uri? uri;
    String? authHeader;
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        uri = request.url;
        authHeader = request.headers['Authorization'];
        return http.Response(
          jsonEncode({
            'id': 'u1',
            'display_name': 'A',
            'created_at': '2026-01-01T00:00:00Z',
          }),
          200,
        );
      }),
    );
    client.configure(baseUrl: 'https://api.example', token: token);
    await client.getMe();
    expect(authHeader, 'Bearer $token');
    expect(uri!.toString().contains(token), isFalse);
    expect(uri!.queryParameters.containsValue(token), isFalse);
  });

  test('client source has no user selector or user_id form fields', () {
    final libDir = Directory('lib');
    final violations = <String>[];
    for (final entity in libDir.listSync(recursive: true)) {
      if (entity is! File || !entity.path.endsWith('.dart')) continue;
      final content = entity.readAsStringSync();
      final scrubbed = content
          .replaceAll('remote_user_id', '')
          .replaceAll('remoteUserId', '');
      if (scrubbed.contains('user_id') || scrubbed.contains('userId')) {
        violations.add(entity.path);
      }
      if (RegExp(r'user\s*selector', caseSensitive: false).hasMatch(content)) {
        violations.add(entity.path);
      }
    }
    expect(violations, isEmpty);
  });
}
