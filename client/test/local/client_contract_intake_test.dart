import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/local/client_wire_metadata.dart';
import 'package:personal_secretary/local/extraction/extraction_constants.dart';
import 'package:personal_secretary/local/local_file_intake_service.dart';
import 'package:personal_secretary/local/local_resource_extractor.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../test_secretary_api_client.dart';

void main() {
  test('sanitizer omits truncated false and internal columns metadata', () {
    final sanitized = sanitizeClientRepresentations([
      {
        'kind': 'full',
        'text': 'ok',
        'metadata': {
          'truncated': false,
          'columns': [{'name': 'a'}],
          'page_count': 1,
        },
      },
    ]);
    final metadata = sanitized.single['metadata'] as Map<String, dynamic>;
    expect(metadata.containsKey('truncated'), isFalse);
    expect(metadata.containsKey('columns'), isFalse);
    expect(metadata['page_count'], 1);
  });

  test('russian txt contract serialization has no forbidden raw payload keys', () async {
    SharedPreferences.setMockInitialValues({
      'secretary_device_key': 'device-key-1',
      'secretary_device_display_name': 'Test device',
    });
    final tempDir = Directory.systemTemp.createTempSync('contract-txt-');
    try {
      final text = 'Обычный русский UTF-8 текст для smoke. ' * 40;
      expect(text.length, greaterThan(1000));
      expect(text.length, lessThan(3000));
      final file = File('${tempDir.path}/notes.txt');
      file.writeAsStringSync(text);

      Map<String, dynamic>? capturedBody;
      final mock = MockClient((request) async {
        if (request.url.path == '/local/devices/register') {
          return http.Response(
            jsonEncode({
              'device_id': 'device-1',
              'device_key': 'device-key-1',
              'display_name': 'Test device',
              'created': true,
            }),
            201,
            headers: {'content-type': 'application/json'},
          );
        }
        if (request.url.path == '/local/files/client-intake') {
          capturedBody = jsonDecode(request.body!) as Map<String, dynamic>;
          return http.Response(
            jsonEncode({
              'object_id': '00000000-0000-0000-0000-000000000001',
              'status': 'created',
              'jobs_enqueued': 1,
              'representations_created': 1,
              'metadata_only': false,
            }),
            201,
            headers: {'content-type': 'application/json'},
          );
        }
        return http.Response('{}', 404);
      });

      final api = testSecretaryApiClient(mock);
      api.configure(baseUrl: 'https://example.com', token: 'token');
      final service = LocalFileIntakeService(apiClient: api);
      await service.registerFile(file);

      expect(capturedBody, isNotNull);
      expect(capturedBody!['metadata_only'], isFalse);
      final reps = capturedBody!['representations'] as List<dynamic>;
      expect(reps, isNotEmpty);
      final payload = jsonEncode(capturedBody);
      expect(payload, contains('русский'));
      expect(payload, isNot(contains('raw_bytes')));
      expect(payload, isNot(contains('file_bytes')));
      for (final rep in reps) {
        final metadata = (rep as Map<String, dynamic>)['metadata'];
        if (metadata is Map) {
          expect(metadata.containsKey('truncated'), isFalse);
        }
      }
    } finally {
      if (tempDir.existsSync()) {
        tempDir.deleteSync(recursive: true);
      }
    }
  });

  test('large txt serialization marks truncated true when payload budget exceeded', () async {
    final extractor = LocalResourceExtractor();
    final tempDir = Directory.systemTemp.createTempSync('contract-large-txt-');
    try {
      final file = File('${tempDir.path}/large.txt');
      file.writeAsStringSync('x' * (kMaxExtractorTotalBytes + 32 * 1024));
      final result = await extractor.extractFile(file);
      final sanitized = sanitizeClientRepresentations(result.representations);
      final hasTruncated = sanitized.any((rep) {
        final metadata = rep['metadata'];
        return metadata is Map && metadata['truncated'] == true;
      });
      expect(hasTruncated, isTrue);
    } finally {
      if (tempDir.existsSync()) {
        tempDir.deleteSync(recursive: true);
      }
    }
  });
}
