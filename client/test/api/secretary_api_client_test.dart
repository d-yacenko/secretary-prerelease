import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_error.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';

import '../test_secretary_api_client.dart';

void main() {
  const baseUrl = 'https://secretary.example';
  const token = 'opaque-test-token-abc123';

  group('SecretaryApiClient', () {
    test(
      'adds bearer Authorization header to authenticated requests',
      () async {
        String? capturedAuth;
        final client = SecretaryApiClient(
          httpClient: MockClient((request) async {
            capturedAuth = request.headers['Authorization'];
            return http.Response(
              jsonEncode({
                'id': 'user-1',
                'display_name': 'Alice',
                'created_at': '2026-01-01T00:00:00Z',
              }),
              200,
            );
          }),
        );
        client.configure(baseUrl: baseUrl, token: token);
        await client.getMe();
        expect(capturedAuth, 'Bearer $token');
      },
    );

    test('does not add user_id to capture payload', () async {
      Map<String, dynamic>? body;
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          body = jsonDecode(request.body) as Map<String, dynamic>;
          return http.Response(
            jsonEncode({
              'task_id': 'task-1',
              'context_edge_ids': [],
              'dependency_edge_ids': [],
            }),
            201,
          );
        }),
      );
      client.configure(baseUrl: baseUrl, token: token);
      await client.captureTask(CaptureTaskRequest(text: 'Do something'));
      expect(body!.containsKey('user_id'), isFalse);
      expect(body!['text'], 'Do something');
    });

    test('parses /me response', () async {
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          return http.Response(
            jsonEncode({
              'id': 'user-1',
              'display_name': 'Alice',
              'created_at': '2026-01-01T00:00:00Z',
            }),
            200,
          );
        }),
      );
      client.configure(baseUrl: baseUrl, token: token);
      final me = await client.getMe();
      expect(me.id, 'user-1');
      expect(me.displayName, 'Alice');
    });

    test('parses /connections response', () async {
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          return http.Response(
            jsonEncode({
              'google': {
                'connected': true,
                'email': 'alice@gmail.com',
                'gmail_available': true,
                'calendar_available': false,
                'drive_available': false,
              },
              'yandex_mail': {'connected': false, 'email': null},
              'yandex_calendar': {'connected': false, 'email': null},
              'mattermost': [],
            }),
            200,
          );
        }),
      );
      client.configure(baseUrl: baseUrl, token: token);
      final connections = await client.getConnections();
      expect(connections.google.connected, isTrue);
      expect(connections.google.gmailAvailable, isTrue);
      expect(connections.google.driveAvailable, isFalse);
      expect(connections.yandexMail.connected, isFalse);
      expect(connections.mattermost, isEmpty);
    });

    test('connectMattermost parses non-secret response', () async {
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          expect(request.url.path, endsWith('/connectors/mattermost/connect'));
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['server_url'], 'https://mm.example.com');
          expect(body['access_token'], 'pat-secret-value');
          return http.Response(
            jsonEncode({
              'status': 'connected',
              'account_id': 'mm-1',
              'server_url': 'https://mm.example.com',
              'remote_user_id': 'remote-1',
              'username': 'alice',
              'display_name': 'Alice',
              'email': null,
            }),
            200,
          );
        }),
      );
      client.configure(baseUrl: baseUrl, token: token);
      final result = await client.connectMattermost(
        serverUrl: 'https://mm.example.com',
        accessToken: 'pat-secret-value',
      );
      expect(result.status, 'connected');
      expect(result.username, 'alice');
      expect(result.accountId, 'mm-1');
    });

    test('capture serialization includes text and title', () async {
      final request = CaptureTaskRequest(
        text: '  keep spaces  ',
        title: 'My title',
      );
      final json = request.toJson();
      expect(json['text'], '  keep spaces  ');
      expect(json['title'], 'My title');
    });

    test('capture serialization supports context and dependency IDs', () async {
      final request = CaptureTaskRequest(
        text: 'task',
        contextObjectIds: ['ctx-1', 'ctx-2'],
        dependsOnIds: ['dep-1'],
      );
      final json = request.toJson();
      expect(json['context_object_ids'], ['ctx-1', 'ctx-2']);
      expect(json['depends_on_ids'], ['dep-1']);
    });

    test('401 maps to authentication error', () async {
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          return http.Response(jsonEncode({'detail': 'invalid token'}), 401);
        }),
      );
      client.configure(baseUrl: baseUrl, token: token);
      await expectLater(
        client.getMe(),
        throwsA(isA<AuthenticationException>()),
      );
    });

    test('422 maps to validation error', () async {
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          return http.Response(
            jsonEncode({'detail': 'text must not be empty'}),
            422,
          );
        }),
      );
      client.configure(baseUrl: baseUrl, token: token);
      await expectLater(
        client.captureTask(CaptureTaskRequest(text: 'x')),
        throwsA(isA<ValidationException>()),
      );
    });

    test('parses structured assistant error detail', () {
      final detail = parseApiErrorDetail(
        http.Response.bytes(
          utf8.encode(
            jsonEncode({
              'detail': {
                'code': 'assistant_round_limit',
                'message':
                    'Секретарю не хватило лимита шагов, чтобы завершить поиск. Попробуйте повторить или немного уточнить запрос.',
              },
            }),
          ),
          502,
          headers: {'content-type': 'application/json'},
        ),
      );
      expect(detail.code, 'assistant_round_limit');
      expect(detail.message, contains('лимита шагов'));
    });

    test('parses legacy string error detail', () {
      final detail = parseApiErrorDetail(
        http.Response(jsonEncode({'detail': 'some string error'}), 502),
      );
      expect(detail.code, isNull);
      expect(detail.message, 'some string error');
    });

    test(
      '502 maps structured assistant error to ServerException with code',
      () async {
        final client = SecretaryApiClient(
          httpClient: MockClient((request) async {
            return http.Response.bytes(
              utf8.encode(
                jsonEncode({
                  'detail': {
                    'code': 'assistant_round_limit',
                    'message':
                        'Секретарю не хватило лимита шагов, чтобы завершить поиск. Попробуйте повторить или немного уточнить запрос.',
                  },
                }),
              ),
              502,
              headers: {'content-type': 'application/json'},
            );
          }),
        );
        client.configure(baseUrl: baseUrl, token: token);
        try {
          await client.sendAssistantMessage(
            AssistantMessageRequest(message: 'hello'),
          );
          fail('expected exception');
        } on ServerException catch (e) {
          expect(e.code, 'assistant_round_limit');
          expect(e.message, contains('лимита шагов'));
        }
      },
    );

    test('client network failure uses secretary network message', () async {
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          throw http.ClientException('Connection refused');
        }),
      );
      client.configure(baseUrl: baseUrl, token: token);
      await expectLater(
        client.getMe(),
        throwsA(
          isA<NetworkException>().having(
            (e) => e.message,
            'message',
            secretaryNetworkErrorMessage,
          ),
        ),
      );
    });

    test('sanitize maps google drive scope error to user message', () {
      expect(
        SecretaryApiClient.sanitizeErrorMessage(
          'google drive scope not granted',
        ),
        'Для Google Drive нужно обновить разрешения Google',
      );
    });

    test('getGoogleAuthorizationUrl returns authorization_url only', () async {
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          expect(request.method, 'POST');
          expect(request.url.path, endsWith('/auth/google/authorization-url'));
          return http.Response(
            jsonEncode({
              'authorization_url':
                  'https://accounts.google.com/o/oauth2/v2/auth?state=abc',
            }),
            200,
          );
        }),
      );
      client.configure(baseUrl: baseUrl, token: token);
      final result = await client.getGoogleAuthorizationUrl();
      expect(result.authorizationUrl, contains('accounts.google.com'));
    });

    test('connectYandexMail sends email and app_password only', () async {
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          expect(request.url.path, endsWith('/connectors/yandex/mail/connect'));
          final body = jsonDecode(request.body!) as Map<String, dynamic>;
          expect(body['email'], 'user@yandex.ru');
          expect(body['app_password'], 'secret-password');
          expect(body.containsKey('imap_host'), isFalse);
          return http.Response(
            jsonEncode({
              'status': 'connected',
              'account_id': 'mail-1',
              'email': 'user@yandex.ru',
            }),
            200,
          );
        }),
      );
      client.configure(baseUrl: baseUrl, token: token);
      final result = await client.connectYandexMail(
        email: 'user@yandex.ru',
        appPassword: 'secret-password',
      );
      expect(result.email, 'user@yandex.ru');
    });

    test(
      'connectYandexCalendar maps connector 401 to ServerException',
      () async {
        final client = SecretaryApiClient(
          httpClient: MockClient((request) async {
            return http.Response(
              jsonEncode({'detail': 'yandex unauthorized'}),
              401,
            );
          }),
        );
        client.configure(baseUrl: baseUrl, token: token);
        await expectLater(
          client.connectYandexCalendar(
            email: 'user@yandex.ru',
            appPassword: 'secret-password',
          ),
          throwsA(isA<ServerException>()),
        );
      },
    );

    test('token never appears in sanitized error text', () async {
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          return http.Response(
            jsonEncode({'detail': 'Bearer $token rejected'}),
            401,
          );
        }),
      );
      client.configure(baseUrl: baseUrl, token: token);
      try {
        await client.getMe();
        fail('expected exception');
      } on AuthenticationException catch (e) {
        expect(e.message.contains(token), isFalse);
        expect(e.message, contains('[redacted]'));
      }
    });

    test('request URLs do not embed bearer token', () async {
      Uri? capturedUri;
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          capturedUri = request.url;
          return http.Response(
            jsonEncode({
              'id': 'user-1',
              'display_name': 'Alice',
              'created_at': '2026-01-01T00:00:00Z',
            }),
            200,
          );
        }),
      );
      client.configure(baseUrl: baseUrl, token: token);
      await client.getMe();
      expect(capturedUri!.toString().contains(token), isFalse);
      expect(capturedUri!.query.contains(token), isFalse);
    });

    test('transcribeAudio sends authenticated multipart audio field', () async {
      String? method;
      Uri? uri;
      String? authorization;
      String bodyText = '';
      final client = SecretaryApiClient(
        httpClient: MockClient((request) async {
          method = request.method;
          uri = request.url;
          authorization = request.headers['Authorization'];
          bodyText = utf8.decode(request.bodyBytes, allowMalformed: true);
          return http.Response(jsonEncode({'text': 'recognized speech'}), 200);
        }),
      );
      client.configure(baseUrl: baseUrl, token: token);
      final text = await client.transcribeAudio(
        audioBytes: [1, 2, 3, 4],
        filename: 'secretary_voice.wav',
        contentType: 'audio/wav',
      );
      expect(text, 'recognized speech');
      expect(method, 'POST');
      expect(uri?.path, '/assistant/transcribe');
      expect(authorization, 'Bearer $token');
      expect(bodyText, contains('name="audio"'));
      expect(bodyText, contains('secretary_voice.wav'));
      expect(bodyText.toLowerCase(), contains('content-type: audio/wav'));
    });

    test(
      'synthesizeSpeech posts authenticated JSON and returns audio bytes',
      () async {
        String? method;
        Uri? uri;
        String? authorization;
        String? contentType;
        String bodyText = '';
        final client = SecretaryApiClient(
          httpClient: MockClient((request) async {
            method = request.method;
            uri = request.url;
            authorization = request.headers['Authorization'];
            contentType = request.headers['content-type'];
            bodyText = utf8.decode(request.bodyBytes);
            return http.Response.bytes(
              [9, 8, 7],
              200,
              headers: {'content-type': 'audio/mpeg'},
            );
          }),
        );
        client.configure(baseUrl: baseUrl, token: token);
        final audio = await client.synthesizeSpeech('Подготовлено письмо.');
        expect(audio, [9, 8, 7]);
        expect(method, 'POST');
        expect(uri?.path, '/assistant/speech');
        expect(authorization, 'Bearer $token');
        expect(contentType, contains('application/json'));
        expect(bodyText, contains('Подготовлено письмо.'));
      },
    );

    test('parses /availability and sends UTC timezone parameters', () async {
      Uri? captured;
      final client = testSecretaryApiClient(
        MockClient((request) async {
          captured = request.url;
          return http.Response(
            jsonEncode({
              'timezone': 'Europe/Amsterdam',
              'window_start': '2026-09-10T07:00:00Z',
              'window_end': '2026-09-10T16:00:00Z',
              'min_duration_minutes': 30,
              'availability_complete': true,
              'busy_intervals': [
                {
                  'start_at': '2026-09-10T08:00:00Z',
                  'end_at': '2026-09-10T09:00:00Z',
                  'event_ids': ['evt-1'],
                },
              ],
              'free_intervals': [
                {
                  'start_at': '2026-09-10T07:00:00Z',
                  'end_at': '2026-09-10T08:00:00Z',
                  'duration_minutes': 60,
                },
              ],
              'unknown_end_event_ids': <String>[],
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }),
      );
      client.configure(baseUrl: baseUrl, token: token);
      final start = DateTime(2026, 9, 10, 9, 0);
      final end = DateTime(2026, 9, 10, 18, 0);
      final result = await client.getAvailability(
        startAt: start,
        endAt: end,
        minDurationMinutes: 30,
      );
      expect(captured!.path, '/availability');
      expect(
        captured!.queryParameters['client_timezone_id'],
        'Europe/Amsterdam',
      );
      expect(captured!.queryParameters['client_utc_offset_minutes'], '120');
      expect(captured!.queryParameters['min_duration_minutes'], '30');
      final sentStart = DateTime.parse(captured!.queryParameters['start_at']!);
      final sentEnd = DateTime.parse(captured!.queryParameters['end_at']!);
      expect(captured!.queryParameters['start_at']!.contains('Z'), isTrue);
      expect(captured!.queryParameters['end_at']!.contains('Z'), isTrue);
      expect(sentStart.isUtc, isTrue);
      expect(sentEnd.isUtc, isTrue);
      expect(sentStart.toLocal(), start);
      expect(sentEnd.toLocal(), end);
      expect(result.timezone, 'Europe/Amsterdam');
      expect(result.availabilityComplete, isTrue);
      expect(result.busyIntervals.single.eventIds, ['evt-1']);
      expect(result.freeIntervals.single.durationMinutes, 60);
      expect(result.unknownEndEventIds, isEmpty);
    });

    group('safe URL composition', () {
      Map<String, dynamic> connectionsJson() => {
        'google': {
          'connected': false,
          'gmail_available': false,
          'calendar_available': false,
        },
        'yandex_mail': {'connected': false},
        'yandex_calendar': {'connected': false},
        'mattermost': [],
      };

      Future<Uri> captureRequestUri(String base, String endpoint) async {
        Uri? capturedUri;
        final client = SecretaryApiClient(
          httpClient: MockClient((request) async {
            capturedUri = request.url;
            if (endpoint == '/capture/task') {
              return http.Response(
                jsonEncode({
                  'task_id': 'task-1',
                  'context_edge_ids': [],
                  'dependency_edge_ids': [],
                }),
                201,
              );
            }
            if (endpoint == '/connections') {
              return http.Response(jsonEncode(connectionsJson()), 200);
            }
            return http.Response(
              jsonEncode({
                'id': 'user-1',
                'display_name': 'Alice',
                'created_at': '2026-01-01T00:00:00Z',
              }),
              200,
            );
          }),
        );
        client.configure(baseUrl: base, token: token);
        switch (endpoint) {
          case '/me':
            await client.getMe();
          case '/connections':
            await client.getConnections();
          case '/capture/task':
            await client.captureTask(CaptureTaskRequest(text: 'x'));
        }
        return capturedUri!;
      }

      test('https://host/ resolves /me', () async {
        final uri = await captureRequestUri('https://host/', '/me');
        expect(uri.toString(), 'https://host/me');
        expect(uri.query.contains(token), isFalse);
      });

      test('https://host/// resolves /me', () async {
        final uri = await captureRequestUri('https://host///', '/me');
        expect(uri.toString(), 'https://host/me');
      });

      test('https://host/api resolves endpoints', () async {
        expect(
          (await captureRequestUri('https://host/api', '/me')).toString(),
          'https://host/api/me',
        );
        expect(
          (await captureRequestUri(
            'https://host/api/',
            '/connections',
          )).toString(),
          'https://host/api/connections',
        );
        expect(
          (await captureRequestUri(
            'https://host/api/',
            '/capture/task',
          )).toString(),
          'https://host/api/capture/task',
        );
      });

      test('rejects query and fragment base URLs', () {
        final client = SecretaryApiClient();
        expect(
          () => client.configure(baseUrl: 'https://host?x=1', token: token),
          throwsArgumentError,
        );
        expect(
          () => client.configure(baseUrl: 'https://host#frag', token: token),
          throwsArgumentError,
        );
      });
    });
  });
}
