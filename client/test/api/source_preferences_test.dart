import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';

const _baseUrl = 'https://secretary.example';
const _token = 'opaque-test-token';

Map<String, dynamic> _preferenceJson({
  String source = 'gmail',
  bool enabled = true,
  int syncIntervalSeconds = 300,
  int defaultSyncIntervalSeconds = 300,
  int minSyncIntervalSeconds = 60,
  int maxSyncIntervalSeconds = 86400,
  int historyDays = 30,
  int defaultHistoryDays = 30,
  int minHistoryDays = 1,
  int maxHistoryDays = 90,
}) {
  return {
    'source': source,
    'enabled': enabled,
    'sync_interval_seconds': syncIntervalSeconds,
    'default_sync_interval_seconds': defaultSyncIntervalSeconds,
    'min_sync_interval_seconds': minSyncIntervalSeconds,
    'max_sync_interval_seconds': maxSyncIntervalSeconds,
    'history_days': historyDays,
    'default_history_days': defaultHistoryDays,
    'min_history_days': minHistoryDays,
    'max_history_days': maxHistoryDays,
  };
}

Map<String, dynamic> _preferencesListJson() {
  return {
    'preferences': [
      _preferenceJson(source: 'gmail', syncIntervalSeconds: 300),
      _preferenceJson(source: 'google_calendar', syncIntervalSeconds: 300),
      _preferenceJson(source: 'yandex_mail', syncIntervalSeconds: 300),
      _preferenceJson(source: 'yandex_calendar', syncIntervalSeconds: 300),
      _preferenceJson(
          source: 'mattermost',
          syncIntervalSeconds: 120,
          historyDays: 14,
          defaultHistoryDays: 14),
      _preferenceJson(
          source: 'teams',
          syncIntervalSeconds: 60,
          historyDays: 1,
          defaultHistoryDays: 1),
    ],
  };
}

SecretaryApiClient _client(MockClient mock) {
  final apiClient = SecretaryApiClient(httpClient: mock);
  apiClient.configure(baseUrl: _baseUrl, token: _token);
  return apiClient;
}

void main() {
  group('SourcePreference models', () {
    test('parses supported sources and history fields from list response',
        () {
      final list = SourcePreferenceList.fromJson(_preferencesListJson());
      expect(list.preferences.length, 6);
      expect(
        list.preferences.map((p) => p.source).toList(),
        supportedSourcePreferenceKeys,
      );
      final gmail = list.preferences.first;
      expect(gmail.enabled, isTrue);
      expect(gmail.syncIntervalSeconds, 300);
      expect(gmail.minSyncIntervalSeconds, 60);
      expect(gmail.maxSyncIntervalSeconds, 86400);
      expect(gmail.historyDays, 30);
      expect(gmail.defaultHistoryDays, 30);
      expect(gmail.minHistoryDays, 1);
      expect(gmail.maxHistoryDays, 90);
    });
  });

  group('SecretaryApiClient source preferences', () {
    test('patchSourceEnabled sends enabled false exactly', () async {
      Map<String, dynamic>? capturedBody;
      final client = _client(MockClient((request) async {
        if (request.method == 'PATCH' &&
            request.url.path.endsWith('/me/source-preferences/gmail')) {
          capturedBody =
              jsonDecode(request.body as String) as Map<String, dynamic>;
          return http.Response(
              jsonEncode(_preferenceJson(enabled: false)), 200);
        }
        return http.Response('{}', 404);
      }));

      final updated = await client.patchSourceEnabled('gmail', false);
      expect(capturedBody, {'enabled': false});
      expect(updated.enabled, isFalse);
    });

    test('patchSourceSyncInterval sends only sync_interval_seconds', () async {
      Map<String, dynamic>? capturedBody;
      final client = _client(MockClient((request) async {
        if (request.method == 'PATCH' &&
            request.url.path.endsWith('/me/source-preferences/gmail')) {
          capturedBody =
              jsonDecode(request.body as String) as Map<String, dynamic>;
          return http.Response(
            jsonEncode(_preferenceJson(syncIntervalSeconds: 120)),
            200,
          );
        }
        return http.Response('{}', 404);
      }));

      await client.patchSourceSyncInterval('gmail', 120);
      expect(capturedBody, {'sync_interval_seconds': 120});
      expect(capturedBody!.containsKey('enabled'), isFalse);
    });

    test('patchSourceHistoryDays sends only history_days', () async {
      Map<String, dynamic>? capturedBody;
      final client = _client(MockClient((request) async {
        if (request.method == 'PATCH' &&
            request.url.path.endsWith('/me/source-preferences/gmail')) {
          capturedBody =
              jsonDecode(request.body as String) as Map<String, dynamic>;
          return http.Response(
            jsonEncode(_preferenceJson(historyDays: 30)),
            200,
          );
        }
        return http.Response('{}', 404);
      }));

      await client.patchSourceHistoryDays('gmail', 30);
      expect(capturedBody, {'history_days': 30});
      expect(capturedBody!.containsKey('enabled'), isFalse);
      expect(capturedBody!.containsKey('sync_interval_seconds'), isFalse);
    });

    test('patchSourceHistoryDays null sends explicit history_days null',
        () async {
      Map<String, dynamic>? capturedBody;
      final client = _client(MockClient((request) async {
        if (request.method == 'PATCH' &&
            request.url.path.endsWith('/me/source-preferences/gmail')) {
          capturedBody =
              jsonDecode(request.body as String) as Map<String, dynamic>;
          return http.Response(jsonEncode(_preferenceJson()), 200);
        }
        return http.Response('{}', 404);
      }));

      await client.patchSourceHistoryDays('gmail', null);
      expect(capturedBody, {'history_days': null});
    });

    test('resetSourcePreference sends explicit nulls including history_days',
        () async {
      Map<String, dynamic>? capturedBody;
      final client = _client(MockClient((request) async {
        if (request.method == 'PATCH' &&
            request.url.path.endsWith('/me/source-preferences/gmail')) {
          capturedBody =
              jsonDecode(request.body as String) as Map<String, dynamic>;
          return http.Response(jsonEncode(_preferenceJson()), 200);
        }
        return http.Response('{}', 404);
      }));

      await client.resetSourcePreference('gmail');
      expect(capturedBody, {
        'enabled': null,
        'sync_interval_seconds': null,
        'history_days': null,
      });
    });
  });
}
