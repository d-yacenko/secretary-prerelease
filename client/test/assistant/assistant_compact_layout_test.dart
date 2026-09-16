import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/assistant/assistant_controller.dart';
import 'package:personal_secretary/assistant/assistant_screen.dart';
import 'package:personal_secretary/assistant/fake_voice_recorder.dart';
import 'package:personal_secretary/assistant/voice_recorder_exceptions.dart';
import 'package:personal_secretary/assistant/voice_temp_files.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/capture/capture_controller.dart';
import '../test_secretary_api_client.dart';
import 'package:personal_secretary/graph/graph_workspace_controller.dart';
import 'package:personal_secretary/shell/app_shell.dart';

const baseUrl = 'https://secretary.example';
const token = 'compact-token';

Map<String, dynamic> pendingPlanBody({String title = 'Short task'}) => {
      'answer': 'Proposed.',
      'references': [],
      'affected_objects': [],
      'pending_action_plan': {
        'id': 'plan-compact-1',
        'status': 'pending',
        'expires_at': '2026-08-30T12:00:00Z',
        'actions': [
          {
            'tool_name': 'create_task',
            'arguments': {'title': title, 'confidence': 0.5},
          },
        ],
      },
    };

Future<void> setCompactSurface(WidgetTester tester, Size size) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
}

Future<void> pumpAssistantFrames(WidgetTester tester, {int frames = 3}) async {
  for (var i = 0; i < frames; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

AssistantController buildAssistant(SecretaryApiClient apiClient, AuthController auth) {
  return AssistantController(
    apiClient: apiClient,
    authController: auth,
    voiceRecorder: FakeVoiceRecorder(),
    voiceTempFiles: VoiceTempFiles(
      directory: Directory.systemTemp.createTempSync('compact_voice'),
    ),
  );
}

void main() {
  final compactSizes = <Size>[
    const Size(320, 640),
    const Size(360, 800),
    const Size(393, 852),
  ];

  for (final size in compactSizes) {
    testWidgets('assistant composer controls visible at ${size.width}x${size.height}',
        (tester) async {
      await setCompactSurface(tester, size);
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final mock = MockClient((request) async => http.Response('{}', 404));
      final apiClient = testSecretaryApiClient(mock);
      apiClient.configure(baseUrl: baseUrl, token: token);
      final auth = AuthController(
        apiClient: apiClient,
        tokenStore: FakeTokenStore(),
        serverUrlStore: FakeServerUrlStore(),
      );
      auth.status = AuthStatus.authenticated;
      final assistant = buildAssistant(apiClient, auth);

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
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('assistant_input')), findsOneWidget);
      expect(find.byKey(const Key('assistant_voice_button')), findsOneWidget);
      expect(find.byKey(const Key('assistant_send_button')), findsOneWidget);
      await tester.tap(find.byKey(const Key('assistant_voice_button')));
      await pumpAssistantFrames(tester);
      if (assistant.voiceState == AssistantVoiceState.recording) {
        await assistant.cancelVoiceRecording();
      }
      await tester.pumpWidget(const SizedBox.shrink());
      assistant.dispose();
    });
  }

  testWidgets('compact shell hides FAB on Assistant and keeps Capture reachable',
      (tester) async {
    await setCompactSurface(tester, const Size(360, 800));
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final mock = MockClient((request) async {
      if (request.url.path == '/notifications') {
        return http.Response(jsonEncode({'notifications': []}), 200);
      }
      if (request.url.path == '/today') {
        return http.Response(
          jsonEncode({
            'date': '2026-08-28',
            'timezone': 'Europe/Amsterdam',
            'day_start': '2026-08-28T00:00:00+02:00',
            'tasks': [],
            'calendar_events': [],
            'notifications': [],
          }),
          200,
        );
      }
      if (request.url.path == '/graph/workspace') {
        return http.Response(
          jsonEncode({
            'root_id': null,
            'seed_ids': [],
            'nodes': [],
            'edges': [],
            'truncated': false,
          }),
          200,
        );
      }
      return http.Response('{}', 404);
    });
    final apiClient = testSecretaryApiClient(mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final assistant = buildAssistant(apiClient, auth);

    final graph = GraphWorkspaceController(
      apiClient: apiClient,
      authController: auth,
    );

    await tester.pumpWidget(
      MaterialApp(
        home: AppShell(
          authController: auth,
          captureController: CaptureController(
            apiClient: apiClient,
            authController: auth,
          ),
          assistantController: assistant,
          graphController: graph,
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('Секретарь'));
    await tester.pumpAndSettle();

    expect(find.byType(FloatingActionButton), findsNothing);
    expect(find.byTooltip('Задача'), findsOneWidget);
    expect(find.byKey(const Key('assistant_input')), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
    assistant.dispose();
  });

  testWidgets('long pending plan title does not overflow on compact width',
      (tester) async {
    await setCompactSurface(tester, const Size(320, 640));
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final longTitle = 'A' * 120;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        return http.Response(jsonEncode(pendingPlanBody(title: longTitle)), 200);
      }
      if (request.url.path == '/graph/workspace') {
        return http.Response(
          jsonEncode({
            'root_id': null,
            'seed_ids': [],
            'nodes': [],
            'edges': [],
            'truncated': false,
          }),
          200,
        );
      }
      return http.Response('{}', 404);
    });
    final apiClient = testSecretaryApiClient(mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final assistant = buildAssistant(apiClient, auth);

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
    await tester.pumpAndSettle();

    await assistant.sendMessage('create');
    await tester.pumpAndSettle();

    expect(find.text('Подтвердить'), findsOneWidget);
    expect(find.text('Отклонить'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
    assistant.dispose();
  });

  testWidgets('voice error retry keeps composer layout intact', (tester) async {
    await setCompactSurface(tester, const Size(393, 852));
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final apiClient = testSecretaryApiClient(
      MockClient((request) async => http.Response('{}', 404)),
    );
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final voiceRecorder = FakeVoiceRecorder();
    voiceRecorder.throwOnHasPermission = true;
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: voiceRecorder,
      voiceTempFiles: VoiceTempFiles(
        directory: Directory.systemTemp.createTempSync('compact_voice_err'),
      ),
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
    await pumpAssistantFrames(tester);

    await assistant.startVoiceRecording();
    await pumpAssistantFrames(tester);

    expect(find.byKey(const Key('assistant_input')), findsOneWidget);
    expect(find.byKey(const Key('assistant_voice_button')), findsOneWidget);
    expect(find.byKey(const Key('assistant_send_button')), findsOneWidget);
    expect(
      find.descendant(
        of: find.byType(Padding),
        matching: find.widgetWithText(TextButton, 'Повторить'),
      ),
      findsWidgets,
    );
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
    assistant.dispose();
  });
}
