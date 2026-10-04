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

      await tester.runAsync(() => assistant.extractRoles());
      await tester.pump();
      expect(overflows, isEmpty);
      expect(find.text('Контекст: Файл — Договор'), findsOneWidget);
      expect(find.byKey(const Key('assistant_input')), findsOneWidget);
      expect(find.byKey(const Key('assistant_message_list')), findsOneWidget);
      _expectWithinSurface(
        tester.getRect(find.byKey(const Key('assistant_input'))),
        surface,
      );
      expect(
        tester.getRect(find.byKey(const Key('ground_roles_button'))).top,
        greaterThan(surface.height),
      );

      await tester.scrollUntilVisible(
        find.byKey(const Key('ground_roles_button')),
        240,
        scrollable: scrollable,
      );
      await tester.pump();
      expect(overflows, isEmpty);
      _expectWithinSurface(
        tester.getRect(find.byKey(const Key('ground_roles_button'))),
        surface,
      );
      _expectWithinSurface(
        tester.getRect(find.byKey(const Key('assistant_input'))),
        surface,
      );

      await tester.runAsync(() => assistant.groundRoles());
      await tester.pump();
      expect(overflows, isEmpty);
      expect(
        tester.getRect(find.byKey(const Key('prepare_role_import_button'))).top,
        greaterThan(surface.height),
      );
      await tester.scrollUntilVisible(
        find.byKey(const Key('prepare_role_import_button')),
        240,
        scrollable: scrollable,
      );
      await tester.pump();
      expect(overflows, isEmpty);
      _expectWithinSurface(
        tester.getRect(find.byKey(const Key('prepare_role_import_button'))),
        surface,
      );

      assistant.setRoleImportRowSelected(0, true);
      await tester.pump();
      await tester.runAsync(() => assistant.prepareRoleImportPlan());
      await tester.pump();
      expect(overflows, isEmpty);
      expect(
        tester.getRect(find.byKey(const Key('role_import_confirm'))).top,
        greaterThan(surface.height),
      );
      await tester.scrollUntilVisible(
        find.byKey(const Key('role_import_confirm')),
        240,
        scrollable: scrollable,
      );
      await tester.scrollUntilVisible(
        find.byKey(const Key('role_import_reject')),
        240,
        scrollable: scrollable,
      );
      await tester.pump();
      expect(overflows, isEmpty);
      _expectWithinSurface(
        tester.getRect(find.byKey(const Key('role_import_confirm'))),
        surface,
      );
      _expectWithinSurface(
        tester.getRect(find.byKey(const Key('role_import_reject'))),
        surface,
      );
      _expectWithinSurface(
        tester.getRect(find.byKey(const Key('assistant_input'))),
        surface,
      );
      expect(find.byKey(const Key('role_import_pending')), findsOneWidget);
    },
  );
}

void _expectWithinSurface(Rect rect, Size surface) {
  expect(rect.top, greaterThanOrEqualTo(0));
  expect(rect.bottom, lessThanOrEqualTo(surface.height));
}
