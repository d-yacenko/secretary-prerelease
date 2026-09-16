import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/assistant/assistant_controller.dart';
import 'package:personal_secretary/assistant/assistant_screen.dart';
import 'package:personal_secretary/assistant/fake_voice_recorder.dart';
import 'package:personal_secretary/assistant/voice_temp_files.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/capture/capture_controller.dart';

import '../test_secretary_api_client.dart';

void main() {
  const baseUrl = 'https://secretary.example';
  const token = 'action-plan-token';

  Map<String, dynamic> pendingPlanBody({
    String planId = 'plan-1',
    String title = 'Review the letter',
  }) {
    return {
      'answer': 'I can create a task.',
      'references': [],
      'affected_objects': [],
      'pending_action_plan': {
        'id': planId,
        'status': 'pending',
        'expires_at': '2026-08-30T12:00:00Z',
        'actions': [
          {
            'tool_name': 'create_task',
            'arguments': {'title': title, 'confidence': 0.8},
          },
        ],
      },
    };
  }

  Future<void> pumpAssistant(
    WidgetTester tester,
    AssistantController assistant,
    AuthController auth,
    CaptureController capture,
    SecretaryApiClient apiClient,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: AssistantScreen(
          controller: assistant,
          apiClient: apiClient,
          authController: auth,
          captureController: capture,
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  test('create_calendar_event displayLabel shows user-visible fields', () {
    final action = PendingAction.fromJson({
      'tool_name': 'create_calendar_event',
      'arguments': {
        'summary': 'Созвон с командой',
        'account_email': 'user@example.com',
        'calendar_id': 'primary',
        'start_at': '2026-09-06T15:00:00+03:00',
        'end_at': '2026-09-06T15:30:00+03:00',
        'description': 'Weekly sync',
        'location': 'Office',
      },
    });
    expect(action.displayLabel, contains('Create calendar event'));
    expect(action.displayLabel, contains('Созвон с командой'));
    expect(action.displayLabel, contains('user@example.com'));
    expect(action.displayLabel, contains('calendar: primary'));
    expect(action.displayLabel, contains('2026-09-06T15:00:00+03:00'));
    expect(action.displayLabel, contains('2026-09-06T15:30:00+03:00'));
    expect(action.displayLabel, contains('Weekly sync'));
    expect(action.displayLabel, contains('Office'));
    expect(action.displayLabel, isNot(contains('operation_id')));
  });

  test('send_email displayLabel shows complete inspectable email', () {
    final action = PendingAction.fromJson({
      'tool_name': 'send_email',
      'arguments': {
        'account_email': 'user@example.com',
        'to': ['ivan@example.com'],
        'subject': 'Статус задачи',
        'body': 'Краткий статус по задаче X.\nГотово к отправке.',
      },
    });
    expect(action.displayLabel, contains('Отправить письмо'));
    expect(action.displayLabel, contains('From: user@example.com'));
    expect(action.displayLabel, contains('To: ivan@example.com'));
    expect(action.displayLabel, contains('Subject: Статус задачи'));
    expect(action.displayLabel, contains('Краткий статус по задаче X.'));
    expect(action.displayLabel, contains('Готово к отправке.'));
    expect(action.displayLabel, isNot(contains('operation_id')));
    expect(action.displayLabel, isNot(contains('rfc822')));
  });

  test(
    'yandex send_email preview shows provider and hides technical fields',
    () {
      final action = PendingAction.fromJson({
        'tool_name': 'send_email',
        'arguments': {
          'provider': 'yandex',
          'account_email': 'user@yandex.ru',
          'to': ['ivan@example.com'],
          'subject': 'Статус',
          'body': 'Полное тело письма.',
          'operation_id': 'should-hide',
          'rfc822_message_id': '<secret@id>',
        },
      });
      expect(action.displayLabel, contains('Provider: Yandex'));
      expect(action.displayLabel, contains('From: user@yandex.ru'));
      expect(action.displayLabel, contains('To: ivan@example.com'));
      expect(action.displayLabel, contains('Subject: Статус'));
      expect(action.displayLabel, contains('Полное тело письма.'));
      expect(action.displayLabel, isNot(contains('operation_id')));
      expect(action.displayLabel, isNot(contains('rfc822')));
      expect(action.displayLabel, isNot(contains('should-hide')));
    },
  );

  test('yandex calendar preview shows default target and hides href', () {
    final action = PendingAction.fromJson({
      'tool_name': 'create_calendar_event',
      'arguments': {
        'provider': 'yandex',
        'account_email': 'user@yandex.ru',
        'calendar_id': 'primary',
        'calendar_label': 'default',
        'calendar_href': '/calendars/user@yandex.ru/events-default/',
        'summary': 'Встреча',
        'start_at': '2026-09-06T15:00:00+03:00',
        'end_at': '2026-09-06T15:30:00+03:00',
        'description': 'Описание',
        'location': 'Офис',
        'operation_id': 'hide-me',
      },
    });
    expect(action.displayLabel, contains('Provider: Yandex'));
    expect(action.displayLabel, contains('user@yandex.ru'));
    expect(action.displayLabel, contains('calendar: default'));
    expect(action.displayLabel, contains('Встреча'));
    expect(action.displayLabel, contains('Описание'));
    expect(action.displayLabel, contains('Офис'));
    expect(action.displayLabel, isNot(contains('events-default')));
    expect(action.displayLabel, isNot(contains('hide-me')));
    expect(action.displayLabel, isNot(contains('operation_id')));
  });

  test('normal response with no pending plan still parses', () {
    final response = AssistantMessageResponse.fromJson({
      'answer': 'Hello',
      'references': [],
      'affected_objects': [],
    });
    expect(response.pendingActionPlan, isNull);
  });

  testWidgets('proposal message renders Approve and Reject', (tester) async {
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        return http.Response(jsonEncode(pendingPlanBody()), 200);
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
    final capture = CaptureController(
      apiClient: apiClient,
      authController: auth,
    );
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(),
    );

    await pumpAssistant(tester, assistant, auth, capture, apiClient);
    await assistant.sendMessage('Create a task');
    await tester.pumpAndSettle();

    expect(find.text('Требует подтверждения'), findsOneWidget);
    expect(find.text('Подтвердить'), findsOneWidget);
    expect(find.text('Отклонить'), findsOneWidget);
    expect(find.text('Create task: Review the letter'), findsOneWidget);
  });

  testWidgets('normal Send disabled while plan pending', (tester) async {
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        return http.Response(jsonEncode(pendingPlanBody()), 200);
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
    final capture = CaptureController(
      apiClient: apiClient,
      authController: auth,
    );
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(),
    );

    await pumpAssistant(tester, assistant, auth, capture, apiClient);
    await assistant.sendMessage('Create a task');
    await tester.pumpAndSettle();

    final sendButton = tester.widget<FilledButton>(
      find.byKey(const Key('assistant_send_button')),
    );
    expect(sendButton.onPressed, isNull);
  });

  testWidgets('microphone remains available while plan pending', (
    tester,
  ) async {
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        return http.Response(jsonEncode(pendingPlanBody()), 200);
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
    final capture = CaptureController(
      apiClient: apiClient,
      authController: auth,
    );
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(),
    );

    await pumpAssistant(tester, assistant, auth, capture, apiClient);
    await assistant.sendMessage('Create a task');
    await tester.pumpAndSettle();

    final sendButton = tester.widget<FilledButton>(
      find.byKey(const Key('assistant_send_button')),
    );
    expect(sendButton.onPressed, isNull);
    final voiceButton = tester.widget<IconButton>(
      find.byKey(const Key('assistant_voice_button')),
    );
    expect(voiceButton.onPressed, isNotNull);
    expect(assistant.isInputBlocked, isTrue);
    expect(assistant.canStartVoiceRecording, isTrue);
    expect(assistant.hasPendingActionPlan, isTrue);
  });

  testWidgets('approve sends plan ID without replacement args', (tester) async {
    String? approvePath;
    Map<String, dynamic>? approveBody;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        return http.Response(jsonEncode(pendingPlanBody()), 200);
      }
      if (request.url.path == '/assistant/action-plans/plan-1/approve') {
        approvePath = request.url.path;
        approveBody = request.body.isEmpty
            ? null
            : jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(
          jsonEncode({
            'id': 'plan-1',
            'status': 'executed',
            'expires_at': '2026-08-30T12:00:00Z',
            'actions': [
              {
                'tool_name': 'create_task',
                'arguments': {'title': 'Review the letter', 'confidence': 0.8},
              },
            ],
            'result': {'actions': []},
          }),
          200,
        );
      }
      if (request.url.path == '/assistant/action-plans/plan-1/resume') {
        return http.Response(
          jsonEncode({
            'answer': 'Done.',
            'affected_objects': [
              {
                'object_id': 'task-1',
                'title': 'Review the letter',
                'kind': 'task',
                'state': 'confirmed',
              },
            ],
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
    final capture = CaptureController(
      apiClient: apiClient,
      authController: auth,
    );
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(),
    );

    await pumpAssistant(tester, assistant, auth, capture, apiClient);
    await assistant.sendMessage('Create a task');
    await tester.pumpAndSettle();

    await tester.tap(find.text('Подтвердить'));
    await tester.pump();
    await tester.pumpAndSettle();

    expect(approvePath, endsWith('/assistant/action-plans/plan-1/approve'));
    expect(approveBody, isNull);
  });

  testWidgets('executed approve triggers resume and appends final message', (
    tester,
  ) async {
    int resumeCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        return http.Response(jsonEncode(pendingPlanBody()), 200);
      }
      if (request.url.path == '/assistant/action-plans/plan-1/approve') {
        return http.Response(
          jsonEncode({
            'id': 'plan-1',
            'status': 'executed',
            'expires_at': '2026-08-30T12:00:00Z',
            'actions': [],
          }),
          200,
        );
      }
      if (request.url.path == '/assistant/action-plans/plan-1/resume') {
        resumeCalls += 1;
        return http.Response(
          jsonEncode({
            'answer': 'Done. I created the task.',
            'affected_objects': [
              {
                'object_id': 'task-1',
                'title': 'Review the letter',
                'kind': 'task',
                'state': 'confirmed',
              },
            ],
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
    final capture = CaptureController(
      apiClient: apiClient,
      authController: auth,
    );
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(),
    );

    await pumpAssistant(tester, assistant, auth, capture, apiClient);
    await assistant.sendMessage('Create a task');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Подтвердить'));
    await tester.pump();
    await tester.pumpAndSettle();

    expect(resumeCalls, 1);
    expect(find.text('Done. I created the task.'), findsOneWidget);
    expect(find.text('Затронутые объекты:'), findsOneWidget);
    expect(find.text('Задача: Review the letter — Открыта'), findsOneWidget);
  });

  testWidgets('reject changes card to Rejected without resume', (tester) async {
    int resumeCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        return http.Response(jsonEncode(pendingPlanBody()), 200);
      }
      if (request.url.path == '/assistant/action-plans/plan-1/reject') {
        return http.Response(
          jsonEncode({
            'id': 'plan-1',
            'status': 'rejected',
            'expires_at': '2026-08-30T12:00:00Z',
            'actions': [],
          }),
          200,
        );
      }
      if (request.url.path.contains('/resume')) {
        resumeCalls += 1;
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
    final capture = CaptureController(
      apiClient: apiClient,
      authController: auth,
    );
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(),
    );

    await pumpAssistant(tester, assistant, auth, capture, apiClient);
    await assistant.sendMessage('Create a task');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Отклонить'));
    await tester.pumpAndSettle();

    expect(find.text('Отклонено'), findsOneWidget);
    expect(resumeCalls, 0);
    expect(assistant.hasPendingActionPlan, isFalse);
  });

  testWidgets('failed approve shows terminal failure state', (tester) async {
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        return http.Response(jsonEncode(pendingPlanBody()), 200);
      }
      if (request.url.path == '/assistant/action-plans/plan-1/approve') {
        return http.Response(
          jsonEncode({
            'id': 'plan-1',
            'status': 'failed',
            'expires_at': '2026-08-30T12:00:00Z',
            'actions': [],
            'failure': 'execution failed',
          }),
          409,
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
    final capture = CaptureController(
      apiClient: apiClient,
      authController: auth,
    );
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(),
    );

    await pumpAssistant(tester, assistant, auth, capture, apiClient);
    await assistant.sendMessage('Create a task');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Подтвердить'));
    await tester.pumpAndSettle();

    expect(find.text('Ошибка'), findsOneWidget);
    expect(find.text('Подтвердить'), findsNothing);
  });

  testWidgets('resetSession clears plan operation state', (tester) async {
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        return http.Response(jsonEncode(pendingPlanBody()), 200);
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
    final capture = CaptureController(
      apiClient: apiClient,
      authController: auth,
    );
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(),
    );

    await pumpAssistant(tester, assistant, auth, capture, apiClient);
    await assistant.sendMessage('Create a task');
    await tester.pumpAndSettle();
    assistant.resetSession();
    await tester.pumpAndSettle();

    expect(assistant.hasPendingActionPlan, isFalse);
    expect(
      assistant.actionPlanOperationState,
      AssistantActionPlanOperationState.idle,
    );
  });

  test('ActionPlanResponse.tryParse rejects generic conflict detail', () {
    final parsed = ActionPlanResponse.tryParse({
      'detail': 'action plan was rejected',
    });
    expect(parsed, isNull);
  });

  test('ActionPlanResponse.tryParse accepts structured failed response', () {
    final parsed = ActionPlanResponse.tryParse({
      'id': 'plan-1',
      'status': 'failed',
      'expires_at': '2026-08-30T12:00:00Z',
      'actions': [],
      'failure': 'execution failed',
    });
    expect(parsed?.status, 'failed');
  });

  testWidgets('approve network failure leaves card pending and retryable', (
    tester,
  ) async {
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        return http.Response(jsonEncode(pendingPlanBody()), 200);
      }
      if (request.url.path.contains('/approve')) {
        throw http.ClientException('Connection failed');
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
    final capture = CaptureController(
      apiClient: apiClient,
      authController: auth,
    );
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(),
    );

    await pumpAssistant(tester, assistant, auth, capture, apiClient);
    await assistant.sendMessage('Create a task');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Подтвердить'));
    await tester.pumpAndSettle();

    expect(
      assistant.messages.last.actionPlan?.cardState,
      ActionPlanCardState.pending,
    );
    expect(
      assistant.actionPlanOperationState,
      AssistantActionPlanOperationState.idle,
    );
    expect(assistant.actionPlanErrorMessage, isNotNull);
    expect(find.text('Подтвердить'), findsOneWidget);
  });

  testWidgets('reject network failure leaves card pending and retryable', (
    tester,
  ) async {
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        return http.Response(jsonEncode(pendingPlanBody()), 200);
      }
      if (request.url.path.contains('/reject')) {
        throw http.ClientException('Connection failed');
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
    final capture = CaptureController(
      apiClient: apiClient,
      authController: auth,
    );
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(),
    );

    await pumpAssistant(tester, assistant, auth, capture, apiClient);
    await assistant.sendMessage('Create a task');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Отклонить'));
    await tester.pumpAndSettle();

    expect(
      assistant.messages.last.actionPlan?.cardState,
      ActionPlanCardState.pending,
    );
    expect(
      assistant.actionPlanOperationState,
      AssistantActionPlanOperationState.idle,
    );
    expect(assistant.actionPlanErrorMessage, isNotNull);
    expect(find.text('Отклонить'), findsOneWidget);
  });

  testWidgets('generic 409 detail on approve does not crash controller', (
    tester,
  ) async {
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        return http.Response(jsonEncode(pendingPlanBody()), 200);
      }
      if (request.url.path.contains('/approve')) {
        return http.Response(
          jsonEncode({'detail': 'action plan was rejected'}),
          409,
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
    final capture = CaptureController(
      apiClient: apiClient,
      authController: auth,
    );
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(),
    );

    await pumpAssistant(tester, assistant, auth, capture, apiClient);
    await assistant.sendMessage('Create a task');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Подтвердить'));
    await tester.pumpAndSettle();

    expect(
      assistant.messages.last.actionPlan?.cardState,
      ActionPlanCardState.pending,
    );
    expect(
      assistant.actionPlanOperationState,
      AssistantActionPlanOperationState.idle,
    );
    expect(find.text('Подтвердить'), findsOneWidget);
  });

  testWidgets('retry approve after transient failure makes second request', (
    tester,
  ) async {
    int approveCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        return http.Response(jsonEncode(pendingPlanBody()), 200);
      }
      if (request.url.path.contains('/approve')) {
        approveCalls += 1;
        if (approveCalls == 1) {
          throw http.ClientException('Connection failed');
        }
        return http.Response(
          jsonEncode({
            'id': 'plan-1',
            'status': 'executed',
            'expires_at': '2026-08-30T12:00:00Z',
            'actions': [],
          }),
          200,
        );
      }
      if (request.url.path.contains('/resume')) {
        return http.Response(
          jsonEncode({'answer': 'Done.', 'affected_objects': []}),
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
    final capture = CaptureController(
      apiClient: apiClient,
      authController: auth,
    );
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(),
    );

    await pumpAssistant(tester, assistant, auth, capture, apiClient);
    await assistant.sendMessage('Create a task');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Подтвердить'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Подтвердить'));
    await tester.pumpAndSettle();

    expect(approveCalls, 2);
  });

  testWidgets('approve malformed 409 body leaves card pending and retryable', (
    tester,
  ) async {
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        return http.Response(jsonEncode(pendingPlanBody()), 200);
      }
      if (request.url.path.contains('/approve')) {
        return http.Response('not-json{{{', 409);
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
    final capture = CaptureController(
      apiClient: apiClient,
      authController: auth,
    );
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(),
    );

    await pumpAssistant(tester, assistant, auth, capture, apiClient);
    await assistant.sendMessage('Create a task');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Подтвердить'));
    await tester.pumpAndSettle();

    expect(
      assistant.messages.last.actionPlan?.cardState,
      ActionPlanCardState.pending,
    );
    expect(
      assistant.actionPlanOperationState,
      AssistantActionPlanOperationState.idle,
    );
    expect(assistant.actionPlanErrorMessage, isNotNull);
    expect(find.text('Подтвердить'), findsOneWidget);
  });

  testWidgets('reject malformed 200 body leaves card pending and retryable', (
    tester,
  ) async {
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        return http.Response(jsonEncode(pendingPlanBody()), 200);
      }
      if (request.url.path.contains('/reject')) {
        return http.Response('not-json{{{', 200);
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
    final capture = CaptureController(
      apiClient: apiClient,
      authController: auth,
    );
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(),
    );

    await pumpAssistant(tester, assistant, auth, capture, apiClient);
    await assistant.sendMessage('Create a task');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Отклонить'));
    await tester.pumpAndSettle();

    expect(
      assistant.messages.last.actionPlan?.cardState,
      ActionPlanCardState.pending,
    );
    expect(
      assistant.actionPlanOperationState,
      AssistantActionPlanOperationState.idle,
    );
    expect(assistant.actionPlanErrorMessage, isNotNull);
    expect(find.text('Отклонить'), findsOneWidget);
  });

  testWidgets('generic 409 detail on reject does not crash controller', (
    tester,
  ) async {
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        return http.Response(jsonEncode(pendingPlanBody()), 200);
      }
      if (request.url.path.contains('/reject')) {
        return http.Response(
          jsonEncode({'detail': 'action plan already executed'}),
          409,
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
    final capture = CaptureController(
      apiClient: apiClient,
      authController: auth,
    );
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(),
    );

    await pumpAssistant(tester, assistant, auth, capture, apiClient);
    await assistant.sendMessage('Create a task');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Отклонить'));
    await tester.pumpAndSettle();

    expect(
      assistant.messages.last.actionPlan?.cardState,
      ActionPlanCardState.pending,
    );
    expect(
      assistant.actionPlanOperationState,
      AssistantActionPlanOperationState.idle,
    );
    expect(find.text('Отклонить'), findsOneWidget);
  });

  testWidgets(
    'prose confirmation without pending_action_plan does not render approval card',
    (tester) async {
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/message') {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'answer':
                    'Ответ Петрушину: «Да, это действительно обидно». Подтвердите отправку.',
                'references': [],
                'affected_objects': [],
                'pending_action_plan': null,
              }),
            ),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
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
      final capture = CaptureController(
        apiClient: apiClient,
        authController: auth,
      );
      final assistant = AssistantController(
        apiClient: apiClient,
        authController: auth,
        voiceRecorder: FakeVoiceRecorder(),
        voiceTempFiles: VoiceTempFiles(),
      );

      await pumpAssistant(tester, assistant, auth, capture, apiClient);
      await assistant.sendMessage(
        'Да, это действительно обидно, ответь это Петрушину.',
      );
      await tester.pumpAndSettle();

      expect(assistant.hasPendingActionPlan, isFalse);
      expect(assistant.messages.last.actionPlan, isNull);
      expect(find.text('Подтвердить'), findsNothing);
      expect(find.text('Отклонить'), findsNothing);
      expect(find.text('Требует подтверждения'), findsNothing);
      expect(find.textContaining('Подтвердите отправку'), findsOneWidget);
    },
  );

  testWidgets(
    'send_message pending_action_plan renders the normal approval card',
    (tester) async {
      final mock = MockClient((request) async {
        if (request.url.path == '/assistant/message') {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'answer': 'Отправка подготовлена.',
                'references': [],
                'affected_objects': [],
                'pending_action_plan': {
                  'id': 'plan-send-1',
                  'status': 'pending',
                  'expires_at': '2026-09-13T15:00:00Z',
                  'actions': [
                    {
                      'tool_name': 'send_message',
                      'arguments': {
                        'provider': 'telegram',
                        'mode': 'reply',
                        'body': 'Да, это действительно обидно',
                        'route': {'chat_display_name': 'Ivan Petrushin'},
                      },
                    },
                  ],
                },
              }),
            ),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
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
      final capture = CaptureController(
        apiClient: apiClient,
        authController: auth,
      );
      final assistant = AssistantController(
        apiClient: apiClient,
        authController: auth,
        voiceRecorder: FakeVoiceRecorder(),
        voiceTempFiles: VoiceTempFiles(),
      );

      await pumpAssistant(tester, assistant, auth, capture, apiClient);
      await assistant.sendMessage('Отправляй');
      await tester.pumpAndSettle();

      expect(assistant.hasPendingActionPlan, isTrue);
      expect(find.text('Требует подтверждения'), findsOneWidget);
      expect(find.text('Подтвердить'), findsOneWidget);
      expect(find.text('Отклонить'), findsOneWidget);
      expect(find.textContaining('Telegram'), findsOneWidget);
      expect(find.textContaining('Да, это действительно обидно'), findsWidgets);
    },
  );
}
