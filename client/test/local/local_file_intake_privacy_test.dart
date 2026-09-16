import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/local/local_file_intake_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../test_secretary_api_client.dart';
import 'format_parity_fixtures.dart';

void main() {
  Future<void> runPrivacyCase({
    required String filename,
    required Future<void> Function(File file) writeFixture,
    required String marker,
    required String forbiddenToken,
  }) async {
    SharedPreferences.setMockInitialValues({
      'secretary_device_key': 'device-key-1',
      'secretary_device_display_name': 'Test device',
    });
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
      capturedBody = jsonDecode(request.body!) as Map<String, dynamic>;
      return http.Response(
        jsonEncode({
          'object_id': '00000000-0000-0000-0000-000000000001',
          'status': 'created',
          'jobs_enqueued': 0,
          'representations_created': 1,
          'metadata_only': false,
        }),
        201,
        headers: {'content-type': 'application/json'},
      );
    });

    final tempDir = Directory.systemTemp.createTempSync('intake-privacy-');
    try {
      final api = testSecretaryApiClient(mock);
      api.configure(baseUrl: 'https://example.com', token: 'token');
      final service = LocalFileIntakeService(apiClient: api);
      final file = File('${tempDir.path}/$filename');
      await writeFixture(file);

      await service.registerFile(file);

      expect(capturedBody, isNotNull);
      final representations =
          capturedBody!['representations'] as List<dynamic>;
      expect(representations, isNotEmpty);
      final payload = jsonEncode(capturedBody);
      expect(payload, contains(marker));
      expect(payload, isNot(contains(forbiddenToken)));
      expect(capturedBody!.containsKey('raw_bytes'), isFalse);
      expect(capturedBody!.containsKey('file_bytes'), isFalse);
      expect(payload, isNot(contains('base64')));
    } finally {
      if (tempDir.existsSync()) {
        tempDir.deleteSync(recursive: true);
      }
    }
  }

  test('text local file privacy boundary', () async {
    await runPrivacyCase(
      filename: 'sample.txt',
      writeFixture: (file) async => file.writeAsString('privacy_marker_text'),
      marker: 'privacy_marker_text',
      forbiddenToken: '%PDF',
    );
  });

  test('binary docx local file privacy boundary', () async {
    await runPrivacyCase(
      filename: 'sample.docx',
      writeFixture: writeMinimalDocx,
      marker: 'docx paragraph beta',
      forbiddenToken: 'UEsDB',
    );
  });
}
