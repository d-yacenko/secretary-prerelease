import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/assistant/assistant_controller.dart';
import 'package:personal_secretary/assistant/assistant_screen.dart';
import 'package:personal_secretary/assistant/fake_voice_recorder.dart';
import 'package:personal_secretary/assistant/voice_temp_files.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/capture/capture_controller.dart';
import 'package:personal_secretary/timezone/client_timezone_context.dart';

void main() {
  const baseUrl = 'https://secretary.example';
  const token = 'keyboard-token';

  ({
    Widget widget,
    AssistantController assistant,
    SecretaryApiClient apiClient,
    AuthController auth,
    CaptureController capture,
  }) buildAssistant(MockClient mock) {
    final apiClient = SecretaryApiClient(
      httpClient: mock,
      timezoneProvider: const FixedClientTimezoneProvider(
        ClientTimezoneContext(zoneId: 'Europe/Amsterdam', utcOffsetMinutes: 120),
      ),
    );
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final capture = CaptureController(apiClient: apiClient, authController: auth);
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(
        directory: Directory.systemTemp.createTempSync('keyboard_voice'),
      ),
    );
    final widget = MaterialApp(
      home: Scaffold(
        body: AssistantScreen(
          controller: assistant,
          apiClient: apiClient,
          authController: auth,
          captureController: capture,
        ),
      ),
    );
    return (
      widget: widget,
      assistant: assistant,
      apiClient: apiClient,
      auth: auth,
      capture: capture,
    );
  }

  testWidgets('plain Enter does not send assistant message', (tester) async {
    int assistantCalls = 0;
    final harness = buildAssistant(MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        assistantCalls += 1;
        return http.Response(jsonEncode({'answer': 'ok', 'references': [], 'affected_objects': []}), 200);
      }
      return http.Response('{}', 404);
    }));
    await tester.pumpWidget(harness.widget);
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('assistant_input')), 'line one');
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pump();

    expect(assistantCalls, 0);
    expect(find.text('line one'), findsOneWidget);
  });

  testWidgets('Ctrl+Enter sends exactly one assistant request', (tester) async {
    int assistantCalls = 0;
    final harness = buildAssistant(MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        assistantCalls += 1;
        return http.Response(jsonEncode({'answer': 'ok', 'references': [], 'affected_objects': []}), 200);
      }
      return http.Response('{}', 404);
    }));
    await tester.pumpWidget(harness.widget);
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('assistant_input')), 'send me');
    await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
    await tester.sendKeyDownEvent(LogicalKeyboardKey.enter);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.enter);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));

    expect(assistantCalls, 1);
  });

  testWidgets('Ctrl+Enter blocked when input disabled', (tester) async {
    int assistantCalls = 0;
    final harness = buildAssistant(MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        assistantCalls += 1;
        return http.Response(
          jsonEncode({
            'answer': 'approve first',
            'references': [],
            'affected_objects': [],
            'pending_action_plan': {
              'id': 'plan-1',
              'status': 'pending',
              'expires_at': '2026-08-30T12:00:00Z',
              'actions': [
                {
                  'tool_name': 'create_task',
                  'arguments': {'title': 'Task', 'confidence': 0.8},
                },
              ],
            },
          }),
          200,
        );
      }
      return http.Response('{}', 404);
    }));
    await tester.pumpWidget(harness.widget);
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('assistant_input')), 'first');
    await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
    await tester.sendKeyDownEvent(LogicalKeyboardKey.enter);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.enter);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
    await tester.pumpAndSettle();

    expect(assistantCalls, 1);

    await tester.enterText(find.byKey(const Key('assistant_input')), 'blocked');
    await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
    await tester.sendKeyDownEvent(LogicalKeyboardKey.enter);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.enter);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
    await tester.pump();

    expect(assistantCalls, 1);
  });
}
