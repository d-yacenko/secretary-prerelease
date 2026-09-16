import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/sources/source_refresh_service.dart';

SourceSyncStatusOut _statusRow({
  String status = 'pending',
  String? nextSyncAt,
}) {
  return SourceSyncStatusOut.fromJson({
    'source': 'gmail',
    'provider': 'gmail',
    'account_id': '550e8400-e29b-41d4-a716-446655440000',
    'account_label': 'user@example.com',
    'status': status,
    'last_success_at': null,
    'last_attempt_at': null,
    'next_sync_at': nextSyncAt,
    'last_error': null,
  });
}

void main() {
  test('isStatusSettled treats syncing as active', () {
    expect(
      SourceRefreshService.isStatusSettled(_statusRow(status: 'syncing')),
      isFalse,
    );
  });

  test('isStatusSettled treats error and scheduled as settled', () {
    expect(
      SourceRefreshService.isStatusSettled(_statusRow(status: 'error')),
      isTrue,
    );
    expect(
      SourceRefreshService.isStatusSettled(_statusRow(status: 'scheduled')),
      isTrue,
    );
  });

  test('pending with future next_sync_at is settled', () {
    final future =
        DateTime.now().add(const Duration(hours: 1)).toUtc().toIso8601String();
    expect(
      SourceRefreshService.isStatusSettled(
        _statusRow(status: 'pending', nextSyncAt: future),
      ),
      isTrue,
    );
  });

  test('pending without next_sync_at is settled idle state', () {
    expect(
      SourceRefreshService.isStatusSettled(_statusRow(status: 'pending')),
      isTrue,
    );
  });

  test('pending due now is not settled', () {
    final past = DateTime.now()
        .subtract(const Duration(minutes: 1))
        .toUtc()
        .toIso8601String();
    expect(
      SourceRefreshService.isStatusSettled(
        _statusRow(status: 'pending', nextSyncAt: past),
      ),
      isFalse,
    );
  });

  test('statusesSettled aggregates rows', () {
    expect(SourceRefreshService.statusesSettled([]), isTrue);
    expect(
      SourceRefreshService.statusesSettled([
        _statusRow(status: 'scheduled'),
        _statusRow(status: 'error'),
      ]),
      isTrue,
    );
    expect(
      SourceRefreshService.statusesSettled([
        _statusRow(status: 'scheduled'),
        _statusRow(status: 'syncing'),
      ]),
      isFalse,
    );
  });

  test('refreshSources times out when statuses stay syncing', () async {
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.method == 'POST' &&
            request.url.path.endsWith('/sources/sync')) {
          return http.Response(
            jsonEncode({
              'triggered': ['gmail:1'],
              'count': 1
            }),
            200,
          );
        }
        if (request.url.path.endsWith('/sources/status')) {
          return http.Response(
            jsonEncode({
              'sources': [
                {
                  'source': 'gmail',
                  'provider': 'gmail',
                  'account_id': '1',
                  'account_label': 'user@example.com',
                  'status': 'syncing',
                  'last_success_at': null,
                  'last_attempt_at': null,
                  'next_sync_at': null,
                  'last_error': null,
                },
              ],
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      }),
    );
    client.configure(baseUrl: 'https://secretary.example', token: 't');

    final service = SourceRefreshService(apiClient: client);
    final result = await service.refreshSources(
      timeout: const Duration(milliseconds: 50),
      pollInterval: const Duration(milliseconds: 10),
    );

    expect(result.timedOut, isTrue);
    expect(result.statuses.single.status, 'syncing');
  });

  test('clearSyncContinuesMessageIfSettled keeps message while syncing', () {
    final row = _statusRow(status: 'syncing');
    expect(
      SourceRefreshService.clearSyncContinuesMessageIfSettled(
        message: SourceRefreshService.syncContinuesMessage,
        statuses: [row],
      ),
      SourceRefreshService.syncContinuesMessage,
    );
  });

  test('clearSyncContinuesMessageIfSettled clears when all settled', () {
    expect(
      SourceRefreshService.clearSyncContinuesMessageIfSettled(
        message: SourceRefreshService.syncContinuesMessage,
        statuses: [_statusRow(status: 'scheduled')],
      ),
      isNull,
    );
  });

  test('clearSyncContinuesMessageIfSettled clears on error status', () {
    expect(
      SourceRefreshService.clearSyncContinuesMessageIfSettled(
        message: SourceRefreshService.syncContinuesMessage,
        statuses: [_statusRow(status: 'error')],
      ),
      isNull,
    );
  });

  test('clearSyncContinuesMessageIfSettled does not clear arbitrary errors',
      () {
    expect(
      SourceRefreshService.clearSyncContinuesMessageIfSettled(
        message: 'sync failed',
        statuses: [_statusRow(status: 'scheduled')],
      ),
      'sync failed',
    );
  });

  test('refreshSources triggers sync and polls until scheduled', () async {
    var statusCalls = 0;
    final pastDue = DateTime.now()
        .subtract(const Duration(minutes: 1))
        .toUtc()
        .toIso8601String();
    final client = SecretaryApiClient(
      httpClient: MockClient((request) async {
        if (request.method == 'POST' &&
            request.url.path.endsWith('/sources/sync')) {
          return http.Response(
              jsonEncode({
                'triggered': ['gmail:1'],
                'count': 1
              }),
              200);
        }
        if (request.url.path.endsWith('/sources/status')) {
          statusCalls += 1;
          final status = statusCalls < 2 ? 'pending' : 'scheduled';
          return http.Response(
            jsonEncode({
              'sources': [
                {
                  'source': 'gmail',
                  'provider': 'gmail',
                  'account_id': '1',
                  'account_label': 'user@example.com',
                  'status': status,
                  'last_success_at':
                      status == 'scheduled' ? '2026-08-31T12:00:00Z' : null,
                  'last_attempt_at': null,
                  'next_sync_at': status == 'scheduled'
                      ? '2026-08-31T12:05:00Z'
                      : pastDue,
                  'last_error': null,
                },
              ],
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      }),
    );
    client.configure(baseUrl: 'https://secretary.example', token: 't');

    final service = SourceRefreshService(apiClient: client);
    final result = await service.refreshSources(
      timeout: const Duration(seconds: 2),
    );

    expect(result.timedOut, isFalse);
    expect(statusCalls, greaterThanOrEqualTo(2));
  });

  testWidgets('Today refresh calls sources sync', (tester) async {
    String? syncMethod;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) {
              final client = SecretaryApiClient(
                httpClient: MockClient((request) async {
                  if (request.method == 'POST' &&
                      request.url.path.endsWith('/sources/sync')) {
                    syncMethod = request.method;
                    return http.Response(
                      jsonEncode({'triggered': [], 'count': 0}),
                      200,
                    );
                  }
                  if (request.url.path.endsWith('/sources/status')) {
                    return http.Response(jsonEncode({'sources': []}), 200);
                  }
                  if (request.url.path == '/today') {
                    return http.Response(
                      jsonEncode({
                        'date': '2026-08-31',
                        'timezone': 'Europe/Moscow',
                        'day_start': '2026-08-31T00:00:00+03:00',
                        'tasks': [],
                        'calendar_events': [],
                        'notifications': [],
                      }),
                      200,
                    );
                  }
                  return http.Response('{}', 404);
                }),
              );
              client.configure(
                  baseUrl: 'https://secretary.example', token: 't');
              final service = SourceRefreshService(apiClient: client);
              return IconButton(
                onPressed: () => service.refreshSources(
                  timeout: const Duration(milliseconds: 100),
                ),
                icon: const Icon(Icons.refresh),
              );
            },
          ),
        ),
      ),
    );

    await tester.tap(find.byIcon(Icons.refresh));
    await tester.pumpAndSettle();

    expect(syncMethod, 'POST');
  });
}
