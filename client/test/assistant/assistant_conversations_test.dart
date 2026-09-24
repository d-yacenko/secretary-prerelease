import 'dart:async';
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
import 'package:personal_secretary/assistant/voice_invocation_source.dart';
import 'package:personal_secretary/assistant/voice_temp_files.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/capture/capture_controller.dart';
import 'package:personal_secretary/timezone/client_timezone_context.dart';

void main() {
  const baseUrl = 'https://secretary.example';

  http.Response jsonResponse(Object body, int status) {
    return http.Response.bytes(
      utf8.encode(jsonEncode(body)),
      status,
      headers: const {'content-type': 'application/json; charset=utf-8'},
    );
  }

  Map<String, dynamic> conversation({
    required String id,
    String? title,
    bool current = false,
    String? lastMessageAt,
  }) {
    return {
      'id': id,
      'title': title,
      'is_current': current,
      'created_at': '2026-09-24T10:00:00Z',
      'updated_at': '2026-09-24T10:00:00Z',
      'last_message_at': lastMessageAt,
    };
  }

  Map<String, dynamic> storedMessage({
    required String id,
    required String role,
    required String content,
    Map<String, dynamic>? plan,
    List<Map<String, dynamic>> references = const [],
  }) {
    return {
      'id': id,
      'role': role,
      'content': content,
      'created_at': '2026-09-24T10:00:00Z',
      'client_turn_id': null,
      'references': references,
      'affected_objects': [],
      'pending_action_plan': plan,
      'inbox_review_receipt': null,
    };
  }

  Future<AssistantController> pump({
    required WidgetTester tester,
    required MockClient mock,
    Size size = const Size(1100, 800),
    String Function()? newTurnId,
    AssistantActionPlanOperationState operation =
        AssistantActionPlanOperationState.idle,
  }) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final apiClient = SecretaryApiClient(
      httpClient: mock,
      timezoneProvider: const FixedClientTimezoneProvider(
        ClientTimezoneContext(zoneId: 'UTC', utcOffsetMinutes: 0),
      ),
    );
    apiClient.configure(baseUrl: baseUrl, token: 't');
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(
        directory: Directory.systemTemp.createTempSync('assistant_conv'),
      ),
      newTurnId: newTurnId,
    );
    assistant.actionPlanOperationState = operation;
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
    return assistant;
  }

  testWidgets('startup restores the current conversation', (tester) async {
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/conversations/current') {
        return jsonResponse(
          conversation(id: 'c-old', title: 'Старый', current: true),
          200,
        );
      }
      if (request.url.path == '/assistant/conversations/c-old/messages') {
        return jsonResponse({
          'messages': [
            storedMessage(id: 'm1', role: 'user', content: 'Привет'),
            storedMessage(
              id: 'm2',
              role: 'assistant',
              content: 'Здравствуйте',
              references: [
                {
                  'object_id': 'obj-1',
                  'title': 'Письмо',
                  'kind': 'email',
                  'provider': 'gmail',
                },
              ],
            ),
          ],
          'has_more': false,
        }, 200);
      }
      if (request.url.path == '/assistant/conversations') {
        return jsonResponse({
          'conversations': [
            conversation(
              id: 'c-old',
              title: 'Старый',
              current: true,
              lastMessageAt: '2026-09-24T11:00:00Z',
            ),
          ],
        }, 200);
      }
      return http.Response('{}', 404);
    });
    final assistant = await pump(tester: tester, mock: mock);
    expect(find.text('Привет'), findsOneWidget);
    expect(find.text('Здравствуйте'), findsOneWidget);
    expect(find.text('Письмо'), findsOneWidget);
    expect(assistant.conversationId, 'c-old');
    expect(tester.takeException(), isNull);
  });

  testWidgets('first run creates a fresh conversation', (tester) async {
    var created = 0;
    final mock = MockClient((request) async {
      if (request.method == 'GET' &&
          request.url.path == '/assistant/conversations/current') {
        return jsonResponse(
          {'detail': 'assistant_conversation not found'},
          404,
        );
      }
      if (request.method == 'POST' &&
          request.url.path == '/assistant/conversations') {
        created += 1;
        return jsonResponse(conversation(id: 'c-new', current: true), 201);
      }
      if (request.url.path == '/assistant/conversations/c-new/messages') {
        return jsonResponse({'messages': [], 'has_more': false}, 200);
      }
      if (request.url.path == '/assistant/conversations') {
        return jsonResponse({
          'conversations': [conversation(id: 'c-new', current: true)],
        }, 200);
      }
      return http.Response('{}', 404);
    });
    final assistant = await pump(tester: tester, mock: mock);
    expect(created, 1);
    expect(assistant.messages, isEmpty);
    expect(assistant.conversationId, 'c-new');
    expect(find.text('Новый диалог'), findsWidgets);
  });

  testWidgets('new dialog empties the transcript and keeps history', (
    tester,
  ) async {
    var currentId = 'c-old';
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/conversations/current') {
        return jsonResponse(
          conversation(id: currentId, title: 'Старый', current: true),
          200,
        );
      }
      if (request.url.path.endsWith('/messages')) {
        final id = request.url.path.split('/')[3];
        final messages = id == 'c-old'
            ? [storedMessage(id: 'm1', role: 'user', content: 'Старый текст')]
            : <Map<String, dynamic>>[];
        return jsonResponse({'messages': messages, 'has_more': false}, 200);
      }
      if (request.method == 'POST' &&
          request.url.path == '/assistant/conversations') {
        currentId = 'c-new';
        return jsonResponse(conversation(id: 'c-new', current: true), 201);
      }
      if (request.url.path == '/assistant/conversations') {
        return jsonResponse({
          'conversations': [
            conversation(id: 'c-new', current: currentId == 'c-new'),
            conversation(id: 'c-old', title: 'Старый', current: false),
          ],
        }, 200);
      }
      return http.Response('{}', 404);
    });
    final assistant = await pump(tester: tester, mock: mock);
    expect(find.text('Старый текст'), findsOneWidget);
    await tester.tap(find.byKey(const Key('assistant_new_conversation')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.text('Старый текст'), findsNothing);
    expect(assistant.conversationId, 'c-new');
    expect(find.text('Старый'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('selecting history restores that conversation for the next send', (
    tester,
  ) async {
    final sentConversations = <String>[];
    final sentHistories = <dynamic>[];
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/conversations/current') {
        return jsonResponse(
          conversation(id: 'c-new', title: 'Новый', current: true),
          200,
        );
      }
      if (request.url.path == '/assistant/conversations/c-old/select') {
        return jsonResponse(
          conversation(id: 'c-old', title: 'Старый', current: true),
          200,
        );
      }
      if (request.url.path.endsWith('/messages')) {
        final id = request.url.path.split('/')[3];
        return jsonResponse({
          'messages': id == 'c-old'
              ? [
                  storedMessage(id: 'u', role: 'user', content: 'Старый вопрос'),
                  storedMessage(
                    id: 'a',
                    role: 'assistant',
                    content: 'Старый ответ',
                    references: [
                      {
                        'object_id': 'obj-9',
                        'title': 'Граф',
                        'kind': 'note',
                      },
                    ],
                  ),
                ]
              : [],
          'has_more': false,
        }, 200);
      }
      if (request.url.path == '/assistant/conversations') {
        return jsonResponse({
          'conversations': [
            conversation(id: 'c-new', title: 'Новый', current: true),
            conversation(id: 'c-old', title: 'Старый', current: false),
          ],
        }, 200);
      }
      if (request.url.path == '/assistant/message') {
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        sentConversations.add(body['conversation_id']?.toString() ?? '');
        sentHistories.add(body['history']);
        return jsonResponse({
          'answer': 'Продолжение',
          'references': [],
          'affected_objects': [],
          'conversation_id': body['conversation_id'],
        }, 200);
      }
      return http.Response('{}', 404);
    });
    final assistant = await pump(tester: tester, mock: mock);
    await tester.tap(find.byKey(const Key('assistant_history_item_c-old')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.text('Старый вопрос'), findsOneWidget);
    expect(find.text('Граф'), findsOneWidget);
    await assistant.sendMessage('ещё');
    await assistant.sendMessage(
      'голосом',
      source: VoiceInvocationSource.screenMic,
    );
    expect(sentConversations, ['c-old', 'c-old']);
    expect(sentHistories, [[], []]);
  });

  testWidgets('desktop history stays inside the chat and narrow does not', (
    tester,
  ) async {
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/conversations/current') {
        return jsonResponse(
          conversation(id: 'c1', title: 'Один', current: true),
          200,
        );
      }
      if (request.url.path.endsWith('/messages')) {
        return jsonResponse({'messages': [], 'has_more': false}, 200);
      }
      if (request.url.path == '/assistant/conversations') {
        return jsonResponse({
          'conversations': [
            conversation(id: 'c1', title: 'Один', current: true),
          ],
        }, 200);
      }
      return http.Response('{}', 404);
    });
    await pump(tester: tester, mock: mock, size: const Size(1100, 800));
    expect(find.byKey(const Key('assistant_history_panel')), findsOneWidget);
    expect(find.byKey(const Key('assistant_input')), findsOneWidget);
    expect(tester.takeException(), isNull);

    await pump(tester: tester, mock: mock, size: const Size(640, 800));
    expect(find.byKey(const Key('assistant_history_panel')), findsOneWidget);
    expect(tester.takeException(), isNull);

    await pump(tester: tester, mock: mock, size: const Size(360, 760));
    expect(find.byKey(const Key('assistant_history_panel')), findsNothing);
    expect(find.byKey(const Key('assistant_input')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('in-flight approval blocks a new dialog with an explanation', (
    tester,
  ) async {
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/conversations/current') {
        return http.Response(
          jsonEncode(conversation(id: 'c1', current: true)),
          200,
        );
      }
      if (request.url.path.endsWith('/messages')) {
        return jsonResponse({'messages': [], 'has_more': false}, 200);
      }
      if (request.url.path == '/assistant/conversations') {
        return http.Response(
          jsonEncode({
            'conversations': [conversation(id: 'c1', current: true)],
          }),
          200,
        );
      }
      return http.Response('{}', 404);
    });
    await pump(
      tester: tester,
      mock: mock,
      operation: AssistantActionPlanOperationState.approving,
    );
    expect(find.text(conversationSwitchWaitMessage), findsOneWidget);
    final button = tester.widget<TextButton>(
      find.byKey(const Key('assistant_new_conversation')),
    );
    expect(button.onPressed, isNull);
  });

  testWidgets('network retry reuses the same client turn id', (tester) async {
    final turnIds = <String>[];
    var attempts = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/conversations/current') {
        return http.Response(
          jsonEncode(conversation(id: 'c1', current: true)),
          200,
        );
      }
      if (request.url.path.endsWith('/messages')) {
        return jsonResponse({'messages': [], 'has_more': false}, 200);
      }
      if (request.url.path == '/assistant/conversations') {
        return http.Response(
          jsonEncode({
            'conversations': [conversation(id: 'c1', current: true)],
          }),
          200,
        );
      }
      if (request.url.path == '/assistant/message') {
        attempts += 1;
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        turnIds.add(body['client_turn_id'] as String);
        if (attempts == 1) {
          return jsonResponse({'detail': 'unavailable'}, 503);
        }
        return jsonResponse({
          'answer': 'ok',
          'references': [],
          'affected_objects': [],
        }, 200);
      }
      return http.Response('{}', 404);
    });
    var issued = 0;
    final assistant = await pump(
      tester: tester,
      mock: mock,
      newTurnId: () {
        issued += 1;
        return 'turn-$issued';
      },
    );
    await assistant.sendMessage('повтор');
    await assistant.sendMessage('повтор');
    await tester.pump();
    expect(turnIds, ['turn-1', 'turn-1']);
    expect(find.text('ok'), findsOneWidget);
  });

  testWidgets('older pages prepend without duplicates', (tester) async {
    final requestedCursors = <String?>[];
    final histories = <dynamic>[];
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/conversations/current') {
        return jsonResponse(conversation(id: 'c1', title: 'Длинный', current: true), 200);
      }
      if (request.url.path == '/assistant/conversations/c1/messages') {
        final beforeId = request.url.queryParameters['before_id'];
        requestedCursors.add(beforeId);
        if (beforeId == null) {
          return jsonResponse({
            'messages': [
              storedMessage(id: 'm50', role: 'user', content: 'новое-50'),
              storedMessage(id: 'm51', role: 'assistant', content: 'новое-51'),
            ],
            'has_more': true,
          }, 200);
        }
        return jsonResponse({
          'messages': [
            storedMessage(id: 'm48', role: 'user', content: 'старое-48'),
            storedMessage(id: 'm49', role: 'assistant', content: 'старое-49'),
            storedMessage(id: 'm50', role: 'user', content: 'новое-50'),
          ],
          'has_more': false,
        }, 200);
      }
      if (request.url.path == '/assistant/conversations') {
        return jsonResponse({
          'conversations': [
            conversation(id: 'c1', title: 'Длинный', current: true),
          ],
        }, 200);
      }
      if (request.url.path == '/assistant/message') {
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        histories.add(body['history']);
        expect(body['conversation_id'], 'c1');
        return jsonResponse({
          'answer': 'дальше',
          'references': [],
          'affected_objects': [],
          'conversation_id': 'c1',
        }, 200);
      }
      return http.Response('{}', 404);
    });
    final assistant = await pump(tester: tester, mock: mock);
    expect(find.text('новое-51'), findsOneWidget);
    expect(find.text('старое-48'), findsNothing);
    expect(assistant.hasOlderMessages, isTrue);
    await tester.tap(find.byKey(const Key('assistant_load_older_messages')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.text('старое-48'), findsOneWidget);
    expect(find.text('новое-50'), findsOneWidget);
    expect(assistant.messages.map((message) => message.content).toList(), [
      'старое-48',
      'старое-49',
      'новое-50',
      'новое-51',
    ]);
    expect(requestedCursors, [null, 'm50']);
    expect(assistant.hasOlderMessages, isFalse);
    await assistant.sendMessage('ещё', source: VoiceInvocationSource.typed);
    await assistant.sendMessage(
      'голосом',
      source: VoiceInvocationSource.screenMic,
    );
    expect(histories, [[], []]);
  });

  testWidgets('transient bootstrap failure stays retryable and does not send', (
    tester,
  ) async {
    var currentAttempts = 0;
    var posts = 0;
    String? sentConversation;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/conversations/current') {
        currentAttempts += 1;
        if (currentAttempts == 1) {
          return jsonResponse({'detail': 'unavailable'}, 503);
        }
        return jsonResponse(conversation(id: 'c1', current: true), 200);
      }
      if (request.url.path.endsWith('/messages')) {
        return jsonResponse({'messages': [], 'has_more': false}, 200);
      }
      if (request.url.path == '/assistant/conversations') {
        return jsonResponse({
          'conversations': [conversation(id: 'c1', current: true)],
        }, 200);
      }
      if (request.url.path == '/assistant/message') {
        posts += 1;
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        sentConversation = body['conversation_id'] as String?;
        return jsonResponse({
          'answer': 'после повтора',
          'references': [],
          'affected_objects': [],
          'conversation_id': body['conversation_id'],
        }, 200);
      }
      return http.Response('{}', 404);
    });
    final assistant = await pump(tester: tester, mock: mock);
    expect(posts, 0);
    expect(assistant.persistentMode, isFalse);
    await assistant.sendMessage('ещё');
    expect(posts, 1);
    expect(sentConversation, 'c1');
    expect(assistant.persistentMode, isTrue);
    expect(find.text('после повтора'), findsNothing);
    await tester.pump();
    expect(find.text('после повтора'), findsOneWidget);
  });

  testWidgets('missing conversation routes keep the legacy send path', (
    tester,
  ) async {
    Map<String, dynamic>? sent;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/conversations/current' ||
          request.url.path == '/assistant/conversations') {
        return jsonResponse({'detail': 'not found'}, 404);
      }
      if (request.url.path == '/assistant/message') {
        sent = jsonDecode(request.body) as Map<String, dynamic>;
        return jsonResponse({
          'answer': 'legacy-ok',
          'references': [],
          'affected_objects': [],
        }, 200);
      }
      return http.Response('{}', 404);
    });
    final assistant = await pump(tester: tester, mock: mock);
    expect(assistant.persistentMode, isFalse);
    await assistant.sendMessage('по-старому');
    expect(sent?['conversation_id'], isNull);
    expect(sent?['client_turn_id'], isNull);
    expect(sent?['history'], isEmpty);
    expect(assistant.messages.last.content, 'legacy-ok');
  });

  testWidgets('the next session bootstraps its own conversation', (tester) async {
    var phase = 'a';
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/conversations/current') {
        final id = phase == 'a' ? 'c-a' : 'c-b';
        final title = phase == 'a' ? 'Диалог A' : 'Диалог B';
        return jsonResponse(
          conversation(id: id, title: title, current: true),
          200,
        );
      }
      if (request.url.path.endsWith('/messages')) {
        final id = request.url.path.split('/')[3];
        return jsonResponse({
          'messages': [
            storedMessage(
              id: 'm-$id',
              role: 'user',
              content: id == 'c-a' ? 'тайна-a' : 'ответ-b',
            ),
          ],
          'has_more': false,
        }, 200);
      }
      if (request.url.path == '/assistant/conversations') {
        final id = phase == 'a' ? 'c-a' : 'c-b';
        final title = phase == 'a' ? 'Диалог A' : 'Диалог B';
        return jsonResponse({
          'conversations': [
            conversation(id: id, title: title, current: true),
          ],
        }, 200);
      }
      return http.Response('{}', 404);
    });
    final assistant = await pump(tester: tester, mock: mock);
    expect(assistant.conversationId, 'c-a');
    expect(find.text('тайна-a'), findsOneWidget);
    expect(find.text('Диалог A'), findsOneWidget);
    phase = 'b';
    assistant.resetSession();
    await assistant.restorePersistentConversation();
    await tester.pump();
    expect(assistant.conversationId, 'c-b');
    expect(assistant.messages.single.content, 'ответ-b');
    expect(find.text('тайна-a'), findsNothing);
    expect(find.text('Диалог A'), findsNothing);
    expect(find.text('Диалог B'), findsOneWidget);
  });

  testWidgets('a stale bootstrap cannot restore the previous conversation', (
    tester,
  ) async {
    final gate = Completer<http.Response>();
    var currentCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/conversations/current') {
        currentCalls += 1;
        if (currentCalls == 1) {
          return gate.future;
        }
        return jsonResponse(
          conversation(id: 'c-b', title: 'Диалог B', current: true),
          200,
        );
      }
      if (request.url.path.endsWith('/messages')) {
        final id = request.url.path.split('/')[3];
        return jsonResponse({
          'messages': [
            storedMessage(
              id: 'm-$id',
              role: 'user',
              content: id == 'c-a' ? 'тайна-a' : 'ответ-b',
            ),
          ],
          'has_more': false,
        }, 200);
      }
      if (request.url.path == '/assistant/conversations') {
        return jsonResponse({
          'conversations': [
            conversation(id: 'c-b', title: 'Диалог B', current: true),
          ],
        }, 200);
      }
      return http.Response('{}', 404);
    });
    final apiClient = SecretaryApiClient(
      httpClient: mock,
      timezoneProvider: const FixedClientTimezoneProvider(
        ClientTimezoneContext(zoneId: 'UTC', utcOffsetMinutes: 0),
      ),
    );
    apiClient.configure(baseUrl: baseUrl, token: 't');
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: auth,
      voiceRecorder: FakeVoiceRecorder(),
      voiceTempFiles: VoiceTempFiles(
        directory: Directory.systemTemp.createTempSync('assistant_epoch'),
      ),
    );
    final pending = assistant.restorePersistentConversation();
    await tester.pump();
    assistant.resetSession();
    gate.complete(
      jsonResponse(conversation(id: 'c-a', title: 'Диалог A', current: true), 200),
    );
    await pending;
    await tester.pump();
    expect(assistant.conversationId, isNull);
    expect(assistant.messages, isEmpty);
    expect(assistant.conversations, isEmpty);
    expect(assistant.persistentMode, isFalse);
    await assistant.restorePersistentConversation();
    expect(assistant.conversationId, 'c-b');
    expect(assistant.messages.single.content, 'ответ-b');
    expect(find.text('тайна-a'), findsNothing);
  });

  testWidgets('a stale send does not restore the previous transcript', (
    tester,
  ) async {
    final gate = Completer<http.Response>();
    var sendStarted = false;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/conversations/current') {
        return jsonResponse(
          conversation(id: 'c-a', title: 'Диалог A', current: true),
          200,
        );
      }
      if (request.url.path == '/assistant/conversations/c-a/messages') {
        return jsonResponse({
          'messages': [
            storedMessage(id: 'm-a', role: 'user', content: 'исходное-a'),
          ],
          'has_more': false,
        }, 200);
      }
      if (request.url.path == '/assistant/conversations') {
        return jsonResponse({
          'conversations': [
            conversation(id: 'c-a', title: 'Диалог A', current: true),
          ],
        }, 200);
      }
      if (request.url.path == '/assistant/message') {
        sendStarted = true;
        return gate.future;
      }
      return http.Response('{}', 404);
    });
    final assistant = await pump(tester: tester, mock: mock);
    expect(find.text('исходное-a'), findsOneWidget);
    final pending = assistant.sendMessage('секрет-a');
    await tester.pump();
    expect(sendStarted, isTrue);
    assistant.resetSession();
    gate.complete(
      jsonResponse({
        'answer': 'ответ-a',
        'references': [],
        'affected_objects': [],
        'conversation_id': 'c-a',
        'user_message_id': 'u-new',
        'assistant_message_id': 'a-new',
      }, 200),
    );
    await pending;
    await tester.pump();
    expect(assistant.messages, isEmpty);
    expect(assistant.conversationId, isNull);
    expect(assistant.persistentMode, isFalse);
    expect(assistant.conversations, isEmpty);
    expect(find.text('секрет-a'), findsNothing);
    expect(find.text('ответ-a'), findsNothing);
    expect(find.text('исходное-a'), findsNothing);
  });
}
