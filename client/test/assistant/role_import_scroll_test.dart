import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/assistant/assistant_controller.dart';
import 'package:personal_secretary/assistant/assistant_screen.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/capture/capture_controller.dart';

import '../test_secretary_api_client.dart';

const _rowCount = 24;

Map<String, dynamic> _previewBody() {
  return {
    'source_object_id': 'obj-1',
    'source_revision': 'rev-1',
    'source_kind': 'text',
    'source_truncated': false,
    'items_truncated': false,
    'items': [
      for (var i = 0; i < _rowCount; i++)
        {
          'row_index': i,
          'person_name': 'Человек $i',
          'role': 'роль $i',
          'context_text': 'контекст $i',
          'evidence_text': 'Длинная строка извлечения $i ' * 8,
          'source_locator': null,
        },
    ],
  };
}

Map<String, dynamic> _groundBody() {
  return {
    'source_object_id': 'obj-1',
    'source_revision': 'rev-1',
    'source_kind': 'text',
    'source_truncated': false,
    'grounding_revision': 'ground-1',
    'items_truncated': false,
    'items': [
      for (var i = 0; i < _rowCount; i++)
        {
          'row_index': i,
          'person_resolution': {
            'state': 'resolved',
            'person_id': 'p$i',
            'title': 'Человек $i',
            'candidates': [],
            'promotion_candidates': [],
          },
          'role_resolution': {
            'state': 'reuse_existing',
            'display_text': 'роль $i',
            'suggestions': [],
          },
        },
    ],
  };
}

Map<String, dynamic> _pendingPlan() {
  return {
    'id': 'plan-1',
    'status': 'pending',
    'expires_at': '2099-01-01T00:00:00Z',
    'summary': 'Подтвердите изменения ролей',
    'actions': [
      {
        'tool_name': 'apply_role_import_batch',
        'arguments': const <String, dynamic>{},
        'presentation': {
          'operation': 'apply_role_import_batch',
          'source_object_id': 'obj-1',
          'source_title': 'Договор',
          'selected_count': 1,
          'total_extracted_rows': _rowCount,
          'source_truncated': false,
          'items_truncated': false,
          'rows': [
            for (var i = 0; i < _rowCount; i++)
              {
                'row_index': i,
                'target_display': 'Человек $i',
                'target_mode': 'existing_person',
                'role': 'роль $i',
                'context': 'контекст $i',
                'vocabulary_mode': 'reuse_existing',
              },
          ],
        },
      },
    ],
  };
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const surface = Size(1100, 480);

  testWidgets(
    'role import scrolls inside Assistant and keeps the composer visible',
    (tester) async {
      tester.view.physicalSize = surface;
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final overflows = <String>[];
      final previousOnError = FlutterError.onError;
      FlutterError.onError = (details) {
        final text = details.exceptionAsString();
        if (text.contains('overflowed')) {
          overflows.add(text);
          return;
        }
        previousOnError?.call(details);
      };
      addTearDown(() => FlutterError.onError = previousOnError);

      final mock = MockClient((request) async {
        final path = request.url.path;
        if (path == '/people/role-import/extract') {
          return http.Response(
            jsonEncode(_previewBody()),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        if (path == '/people/role-import/ground') {
          return http.Response(
            jsonEncode(_groundBody()),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        if (path == '/people/role-import/action-plan') {
          return http.Response(
            jsonEncode(_pendingPlan()),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        return http.Response('{}', 404);
      });
      final apiClient = testSecretaryApiClient(mock);
      apiClient.configure(baseUrl: 'https://secretary.example', token: 'token');
      final auth = AuthController(
        apiClient: apiClient,
        tokenStore: FakeTokenStore(),
        serverUrlStore: FakeServerUrlStore(),
      );
      auth.status = AuthStatus.authenticated;
      final assistant = AssistantController(
        apiClient: apiClient,
        authController: auth,
      );
      addTearDown(assistant.dispose);
      assistant.setObjectContext(
        SecretaryObject.fromJson({
          'id': 'obj-1',
          'kind': 'file',
          'title': 'Договор',
          'body': null,
          'provider': 'upload',
          'external_id': null,
          'canonical_uri': null,
          'status': null,
          'start_at': null,
          'due_at': null,
          'metadata': {},
          'origin': 'user',
          'state': 'confirmed',
          'confidence': null,
          'created_at': '2026-01-01T00:00:00Z',
          'updated_at': '2026-01-01T00:00:00Z',
        }),
      );

      await tester.pumpWidget(
        MaterialApp(
          home: AssistantScreen(
            controller: assistant,
            apiClient: apiClient,
            authController: auth,
            captureController: CaptureController(
              apiClient: apiClient,
              authController: auth,
            ),
          ),
        ),
      );
      await tester.pump();

      final scrollable = find.descendant(
        of: find.byKey(const Key('role_import_scroll')),
        matching: find.byType(Scrollable),
      );

      await tester.tap(find.byKey(const Key('extract_roles_button')));
      await _settleRoleImport(tester);
      expect(overflows, isEmpty);
      expect(find.text('Контекст: Файл — Договор'), findsOneWidget);
      expect(find.byKey(const Key('assistant_input')), findsOneWidget);
      expect(find.byKey(const Key('assistant_message_list')), findsOneWidget);
      final input = tester.getRect(find.byKey(const Key('assistant_input')));
      _expectWithinSurface(input, surface);
      final viewport = tester.getRect(find.byKey(const Key('role_import_scroll')));
      expect(input.top - viewport.bottom, inInclusiveRange(0, 12));
      expect(scrollable, findsOneWidget);
      final view = tester.widget<SingleChildScrollView>(
        find.byKey(const Key('role_import_scroll')),
      );
      final bar = find.ancestor(
        of: find.byKey(const Key('role_import_scroll')),
        matching: find.byType(Scrollbar),
      );
      expect(bar, findsOneWidget);
      expect(
        tester.widget<Scrollbar>(bar).controller,
        same(view.controller),
      );
      final messageList = tester.widget<ListView>(
        find.byKey(const Key('assistant_message_list')),
      );
      expect(messageList.controller, isNot(same(view.controller)));
      _expectInsideViewport(
        tester,
        find.byKey(const Key('ground_roles_button')),
      );

      await tester.tap(find.byKey(const Key('ground_roles_button')));
      await _settleRoleImport(tester);
      expect(overflows, isEmpty);
      _expectInsideViewport(
        tester,
        find.byKey(const Key('prepare_role_import_button')),
      );
      _expectWithinSurface(input, surface);

      assistant.setRoleImportRowSelected(0, true);
      await tester.pump();
      await tester.tap(find.byKey(const Key('prepare_role_import_button')));
      await _settleRoleImport(tester);
      expect(overflows, isEmpty);
      _expectInsideViewport(tester, find.byKey(const Key('role_import_confirm')));
      _expectInsideViewport(tester, find.byKey(const Key('role_import_reject')));
      _expectWithinSurface(
        tester.getRect(find.byKey(const Key('assistant_input'))),
        surface,
      );

      view.controller!.jumpTo(0);
      await tester.pump();
      final parked = view.controller!.offset;
      expect(parked, 0);
      assistant.setDrivingSession(authorized: true, sessionId: 'drive-1');
      await tester.pump();
      expect(view.controller!.offset, parked);
      expect(overflows, isEmpty);
    },
  );

  testWidgets(
    'role import keeps message history visible and independently scrollable',
    (tester) async {
      tester.view.physicalSize = surface;
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final mock = MockClient((request) async {
        final path = request.url.path;
        if (path == '/assistant/conversations/current') {
          return http.Response(
            jsonEncode({
              'id': 'c-old',
              'title': 'Диалог',
              'is_current': true,
              'created_at': '2026-09-24T10:00:00Z',
              'updated_at': '2026-09-24T10:00:00Z',
              'last_message_at': null,
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        if (path == '/assistant/conversations') {
          return http.Response(
            jsonEncode({'conversations': []}),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        if (path == '/assistant/conversations/c-old/messages') {
          return http.Response(
            jsonEncode({
              'messages': [
                for (var i = 0; i < 8; i++)
                  {
                    'id': 'm$i',
                    'role': i.isEven ? 'user' : 'assistant',
                    'content': 'Сообщение $i ${'текст ' * 40}',
                    'created_at': '2026-09-24T10:00:00Z',
                    'client_turn_id': null,
                    'references': [],
                    'affected_objects': [],
                    'pending_action_plan': null,
                    'inbox_review_receipt': null,
                  },
              ],
              'has_more': false,
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        if (path == '/people/role-import/extract') {
          return http.Response(
            jsonEncode(_previewBody()),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        return http.Response('{}', 404);
      });
      final apiClient = testSecretaryApiClient(mock);
      apiClient.configure(baseUrl: 'https://secretary.example', token: 'token');
      final auth = AuthController(
        apiClient: apiClient,
        tokenStore: FakeTokenStore(),
        serverUrlStore: FakeServerUrlStore(),
      );
      auth.status = AuthStatus.authenticated;
      final assistant = AssistantController(
        apiClient: apiClient,
        authController: auth,
      );
      addTearDown(assistant.dispose);
      assistant.setObjectContext(
        SecretaryObject.fromJson({
          'id': 'obj-1',
          'kind': 'file',
          'title': 'Договор',
          'body': null,
          'provider': 'upload',
          'external_id': null,
          'canonical_uri': null,
          'status': null,
          'start_at': null,
          'due_at': null,
          'metadata': {},
          'origin': 'user',
          'state': 'confirmed',
          'confidence': null,
          'created_at': '2026-01-01T00:00:00Z',
          'updated_at': '2026-01-01T00:00:00Z',
        }),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: AssistantScreen(
            controller: assistant,
            apiClient: apiClient,
            authController: auth,
            captureController: CaptureController(
              apiClient: apiClient,
              authController: auth,
            ),
          ),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      expect(assistant.messages, isNotEmpty);

      await tester.tap(find.byKey(const Key('extract_roles_button')));
      await _settleRoleImport(tester);

      final messages = tester.getRect(
        find.byKey(const Key('assistant_message_list')),
      );
      final viewport = tester.getRect(find.byKey(const Key('role_import_scroll')));
      expect(messages.height, greaterThanOrEqualTo(96));
      expect(viewport.bottom, lessThanOrEqualTo(messages.top + 1));
      expect(find.textContaining('Сообщение 0'), findsOneWidget);
      final roleScroll = tester.widget<SingleChildScrollView>(
        find.byKey(const Key('role_import_scroll')),
      );
      final messageScroll = tester.widget<ListView>(
        find.byKey(const Key('assistant_message_list')),
      );
      expect(messageScroll.controller, isNot(same(roleScroll.controller)));
      final roleOffset = roleScroll.controller!.offset;
      await tester.drag(
        find.byKey(const Key('assistant_message_list')),
        const Offset(0, -80),
      );
      await tester.pump();
      expect(roleScroll.controller!.offset, roleOffset);
      final messageOffset = messageScroll.controller!.offset;
      await tester.drag(
        find.byKey(const Key('role_import_scroll')),
        const Offset(0, -80),
      );
      await tester.pump();
      expect(messageScroll.controller!.offset, messageOffset);
      _expectWithinSurface(
        tester.getRect(find.byKey(const Key('assistant_input'))),
        surface,
      );
    },
  );

  testWidgets(
    'grounding empty state follows the role-import viewport',
    (tester) async {
      tester.view.physicalSize = surface;
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final mock = MockClient((request) async {
        final path = request.url.path;
        if (path == '/people/role-import/extract') {
          return http.Response(
            jsonEncode(_previewBody()),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        if (path == '/people/role-import/ground') {
          return http.Response(
            jsonEncode({
              ..._groundBody(),
              'items': <Map<String, dynamic>>[],
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        return http.Response('{}', 404);
      });
      final apiClient = testSecretaryApiClient(mock);
      apiClient.configure(baseUrl: 'https://secretary.example', token: 'token');
      final auth = AuthController(
        apiClient: apiClient,
        tokenStore: FakeTokenStore(),
        serverUrlStore: FakeServerUrlStore(),
      );
      auth.status = AuthStatus.authenticated;
      final assistant = AssistantController(
        apiClient: apiClient,
        authController: auth,
      );
      addTearDown(assistant.dispose);
      assistant.setObjectContext(
        SecretaryObject.fromJson({
          'id': 'obj-1',
          'kind': 'file',
          'title': 'Договор',
          'body': null,
          'provider': 'upload',
          'external_id': null,
          'canonical_uri': null,
          'status': null,
          'start_at': null,
          'due_at': null,
          'metadata': {},
          'origin': 'user',
          'state': 'confirmed',
          'confidence': null,
          'created_at': '2026-01-01T00:00:00Z',
          'updated_at': '2026-01-01T00:00:00Z',
        }),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: AssistantScreen(
            controller: assistant,
            apiClient: apiClient,
            authController: auth,
            captureController: CaptureController(
              apiClient: apiClient,
              authController: auth,
            ),
          ),
        ),
      );
      await tester.pump();
      await tester.tap(find.byKey(const Key('extract_roles_button')));
      await _settleRoleImport(tester);
      await tester.tap(find.byKey(const Key('ground_roles_button')));
      await _settleRoleImport(tester);
      _expectInsideViewport(
        tester,
        find.byKey(const Key('role_import_no_communication')),
      );
      expect(find.byKey(const Key('prepare_role_import_button')), findsNothing);
    },
  );
}

Future<void> _settleRoleImport(WidgetTester tester) async {
  await tester.pump();
  await tester.pump();
}

void _expectInsideViewport(WidgetTester tester, Finder finder) {
  final viewport = tester.getRect(find.byKey(const Key('role_import_scroll')));
  final rect = tester.getRect(finder);
  expect(rect.top, greaterThanOrEqualTo(viewport.top - 1));
  expect(rect.bottom, lessThanOrEqualTo(viewport.bottom + 1));
}

void _expectWithinSurface(Rect rect, Size surface) {
  expect(rect.top, greaterThanOrEqualTo(0));
  expect(rect.bottom, lessThanOrEqualTo(surface.height));
}
