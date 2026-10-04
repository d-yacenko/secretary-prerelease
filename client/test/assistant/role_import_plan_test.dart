import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/role_import_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/assistant/assistant_controller.dart';
import 'package:personal_secretary/assistant/fake_speech_player.dart';
import 'package:personal_secretary/assistant/role_import_preview.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';

import '../test_secretary_api_client.dart';

const _previewBody = {
  'source_object_id': 'obj-1',
  'source_revision': 'rev-1',
  'source_kind': 'text',
  'source_truncated': false,
  'items_truncated': false,
  'items': [
    {
      'row_index': 0,
      'person_name': 'Ольга',
      'role': 'директор',
      'context_text': null,
      'evidence_text': 'Ольга — директор',
      'source_locator': null,
    },
    {
      'row_index': 1,
      'person_name': 'Борис',
      'role': 'директор',
      'context_text': null,
      'evidence_text': 'Борис — директор',
      'source_locator': null,
    },
    {
      'row_index': 2,
      'person_name': 'Ада',
      'role': 'аналитик',
      'context_text': null,
      'evidence_text': 'Ада — аналитик',
      'source_locator': null,
    },
    {
      'row_index': 3,
      'person_name': 'Никто',
      'role': 'гость',
      'context_text': null,
      'evidence_text': 'Никто — гость',
      'source_locator': null,
    },
  ],
};

const _groundBody = {
  'source_object_id': 'obj-1',
  'source_revision': 'rev-1',
  'source_kind': 'text',
  'source_truncated': false,
  'grounding_revision': 'ground-1',
  'items_truncated': false,
  'items': [
    {
      'row_index': 0,
      'person_resolution': {
        'state': 'resolved',
        'person_id': 'p1',
        'title': 'Ольга',
        'candidates': [],
        'promotion_candidates': [],
      },
      'role_resolution': {
        'state': 'reuse_existing',
        'display_text': 'директор',
        'suggestions': [],
      },
    },
    {
      'row_index': 1,
      'person_resolution': {
        'state': 'ambiguous',
        'person_id': null,
        'title': null,
        'candidates': [
          {'person_id': 'p2', 'title': 'Борис'},
        ],
        'promotion_candidates': [],
      },
      'role_resolution': {
        'state': 'propose_new',
        'display_text': 'директор',
        'suggestions': ['генеральный директор'],
      },
    },
    {
      'row_index': 2,
      'person_resolution': {
        'state': 'promotion_candidates',
        'person_id': null,
        'title': null,
        'candidates': [],
        'promotion_candidates': [
          {
            'candidate_key': 'k',
            'display_name': 'Ада',
            'provider': 'email',
            'direct_hit_count': 2,
          },
        ],
      },
      'role_resolution': {
        'state': 'propose_new',
        'display_text': 'аналитик',
        'suggestions': [],
      },
    },
    {
      'row_index': 3,
      'person_resolution': {
        'state': 'unresolved',
        'person_id': null,
        'title': null,
        'candidates': [],
        'promotion_candidates': [],
      },
      'role_resolution': {
        'state': 'propose_new',
        'display_text': 'гость',
        'suggestions': [],
      },
    },
  ],
};

Map<String, dynamic> _plan({
  required String status,
  Map<String, dynamic>? result,
  String? failure,
}) {
  return {
    'id': 'plan-1',
    'status': status,
    'expires_at': '2099-01-01T00:00:00Z',
    'summary': 'Подтвердите изменения ролей',
    'actions': [
      {
        'tool_name': 'apply_role_import_batch',
        'arguments': const {'operation_id': 'op-1'},
        'presentation': {
          'operation': 'apply_role_import_batch',
          'source_object_id': 'obj-1',
          'source_title': 'Договор',
          'selected_count': 2,
          'total_extracted_rows': 4,
          'source_truncated': false,
          'items_truncated': false,
          'rows': [
            {
              'row_index': 0,
              'target_display': 'Ольга',
              'target_mode': 'existing_person',
              'role': 'директор',
              'context': null,
              'vocabulary_mode': 'reuse_existing',
            },
            {
              'row_index': 2,
              'target_display': 'Ада',
              'target_mode': 'promote_person',
              'role': 'аналитик',
              'context': 'проект',
              'vocabulary_mode': 'create_if_missing',
            },
          ],
        },
      },
    ],
    if (result != null) 'result': result,
    if (failure != null) 'failure': failure,
  };
}

Map<String, dynamic> _executed({required bool changed}) {
  return {
    'actions': [
      {
        'output': {
          'changed': changed,
          'people_created': changed ? 1 : 0,
          'assignments_changed': changed ? 1 : 0,
          'assignments_no_op': changed ? 0 : 1,
          'duplicate_rows': 0,
          'rows': [
            {'row_index': 0, 'status': 'applied'},
            {'row_index': 2, 'status': 'already_active'},
            {'row_index': 1, 'status': 'duplicate_selected_row'},
          ],
        },
      },
    ],
  };
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late List<String> paths;
  late Map<String, dynamic>? prepareBody;
  late int prepareCalls;
  late int approveCalls;
  late int rejectCalls;
  late int resumeCalls;
  late String prepareStatus;
  late int prepareStatusCode;
  late String prepareDetail;
  late Completer<http.Response>? prepareGate;
  late Completer<http.Response>? approveGate;
  late Completer<http.Response>? rejectGate;
  late int conversationCreates;
  late bool conversationsAvailable;
  late bool approveChanged;
  late String approveStatus;
  late String? approveFailure;

  AssistantController controllerFor(AuthController auth, SecretaryApiClient client) {
    return AssistantController(
      apiClient: client,
      authController: auth,
      speechPlayer: FakeSpeechPlayer(),
    );
  }

  SecretaryApiClient clientFor() {
    final client = testSecretaryApiClient(
        MockClient((request) async {
          paths.add(request.url.path);
          if (request.url.path.endsWith('/resume')) {
            resumeCalls += 1;
          }
          if (request.url.path == '/conversations/missing') {
            return http.Response('{"detail":"missing"}', 404);
          }
          if (request.url.path == '/people/role-import/extract') {
            return http.Response(
              jsonEncode(_previewBody),
              200,
              headers: {'content-type': 'application/json'},
            );
          }
          if (request.url.path == '/people/role-import/ground') {
            return http.Response(
              jsonEncode(_groundBody),
              200,
              headers: {'content-type': 'application/json'},
            );
          }
          if (request.url.path == '/people/role-import/action-plan') {
            prepareCalls += 1;
            prepareBody = jsonDecode(request.body) as Map<String, dynamic>;
            final response = http.Response(
              prepareStatusCode == 200
                  ? jsonEncode(_plan(status: prepareStatus))
                  : jsonEncode({'detail': prepareDetail}),
              prepareStatusCode,
              headers: {'content-type': 'application/json'},
            );
            final gate = prepareGate;
            if (gate != null) {
              return gate.future;
            }
            return response;
          }
          if (request.url.path.endsWith('/approve')) {
            approveCalls += 1;
            final response = http.Response(
              jsonEncode(
                _plan(
                  status: approveStatus,
                  result: approveStatus == 'executed'
                      ? _executed(changed: approveChanged)
                      : null,
                  failure: approveFailure,
                ),
              ),
              200,
              headers: {'content-type': 'application/json'},
            );
            final gate = approveGate;
            if (gate != null) {
              return gate.future;
            }
            return response;
          }
          if (request.url.path.endsWith('/reject')) {
            rejectCalls += 1;
            final response = http.Response(
              jsonEncode(_plan(status: 'rejected')),
              200,
              headers: {'content-type': 'application/json'},
            );
            final gate = rejectGate;
            if (gate != null) {
              return gate.future;
            }
            return response;
          }
          if (conversationsAvailable &&
              request.method == 'POST' &&
              request.url.path == '/assistant/conversations') {
            conversationCreates += 1;
            return http.Response(
              jsonEncode({
                'id': 'conv-$conversationCreates',
                'title': 'Новый',
                'is_current': true,
                'created_at': '2026-10-04T00:00:00Z',
                'updated_at': '2026-10-04T00:00:00Z',
              }),
              201,
              headers: {'content-type': 'application/json'},
            );
          }
          if (conversationsAvailable &&
              request.method == 'GET' &&
              request.url.path == '/assistant/conversations') {
            return http.Response(
              jsonEncode({'conversations': []}),
              200,
              headers: {'content-type': 'application/json'},
            );
          }
          if (request.url.path == '/assistant/message') {
            return http.Response(
              jsonEncode({
                'answer': 'Нужно подтверждение',
                'references': [],
                'affected_objects': [],
                'pending_action_plan': {
                  'id': 'chat-plan',
                  'status': 'pending',
                  'expires_at': '2099-01-01T00:00:00Z',
                  'actions': [
                    {
                      'tool_name': 'create_task',
                      'arguments': {'title': 'задача'},
                    },
                  ],
                },
              }),
              200,
              headers: {'content-type': 'application/json'},
            );
          }
          return http.Response('{}', 404);
        }),
    );
    client.configure(baseUrl: 'https://example.com', token: 'secret-token');
    return client;
  }

  setUp(() {
    paths = [];
    prepareBody = null;
    prepareCalls = 0;
    approveCalls = 0;
    rejectCalls = 0;
    resumeCalls = 0;
    prepareStatus = 'pending';
    prepareStatusCode = 200;
    prepareDetail = 'role_import_source_changed';
    prepareGate = null;
    approveGate = null;
    rejectGate = null;
    conversationCreates = 0;
    conversationsAvailable = false;
    approveChanged = true;
    approveStatus = 'executed';
    approveFailure = null;
  });

  AssistantController start() {
    final client = clientFor();
    final auth = AuthController(
      apiClient: client,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final controller = controllerFor(auth, client);
    controller.setObjectContext(
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
    return controller;
  }

  Future<void> ground(WidgetTester tester, AssistantController controller) async {
    await tester.runAsync(() async {
      await controller.extractRoles();
      await controller.groundRoles();
    });
    await tester.pump();
  }

  Widget panel(AssistantController controller) {
    return MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(
          child: AnimatedBuilder(
          animation: controller,
          builder: (context, _) => RoleImportPreviewPanel(
            preview: controller.roleImportPreview,
            loading: controller.roleImportLoading,
            error: controller.roleImportError,
            grounded: controller.roleGrounding,
            sourceStale: controller.roleImportStale,
            choices: controller.roleImportChoices,
            phase: controller.roleImportPhase,
            plan: controller.roleImportPlan,
            planError: controller.roleImportPlanError,
            groundingStale: controller.roleImportGroundingStale,
            selectionFrozen: controller.roleImportSelectionFrozen,
            canPrepare: controller.canPrepareRoleImport,
            operationsEnabled: !controller.roleImportBlockedByChatPlan,
            onExtract: controller.extractRoles,
            onGround: controller.groundRoles,
            onToggleRow: controller.setRoleImportRowSelected,
            onChoosePerson: controller.chooseRoleImportPerson,
            onChoosePromotion: controller.chooseRoleImportPromotion,
            onPrepare: controller.prepareRoleImportPlan,
            onApprove: controller.approveRoleImportPlan,
            onReject: controller.rejectRoleImportPlan,
            onEditSelection: controller.editRoleImportSelection,
          ),
        ),
        ),
      ),
    );
  }

  Future<void> show(WidgetTester tester, AssistantController controller) async {
    tester.view.physicalSize = const Size(1200, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(panel(controller));
  }

  testWidgets('selection starts empty and stays explicit', (tester) async {
    final controller = start();
    await show(tester, controller);
    await ground(tester, controller);

    expect(controller.roleImportChoices, isEmpty);
    expect(find.byType(Checkbox), findsNWidgets(3));
    for (final checkbox in tester.widgetList<Checkbox>(find.byType(Checkbox))) {
      expect(checkbox.value, isFalse);
    }
    expect(
      tester.widget<TextButton>(find.byKey(const Key('prepare_role_import_button'))).onPressed,
      isNull,
    );

    await tester.tap(find.byKey(const Key('role_import_select_1')));
    await tester.pump();
    expect(controller.roleImportChoices[1]?.selected, isNot(true));

    await tester.tap(find.byKey(const Key('role_import_choose_person_p2')));
    await tester.pump();
    expect(controller.roleImportChoices[1]?.selected, isNot(true));
    await tester.tap(find.byKey(const Key('role_import_select_1')));
    await tester.pump();
    expect(controller.roleImportChoices[1]?.personId, 'p2');

    await tester.tap(find.byKey(const Key('role_import_select_2')));
    await tester.pump();
    expect(controller.roleImportChoices[2]?.selected, isNot(true));
    await tester.tap(find.byKey(const Key('role_import_choose_promotion_k')));
    await tester.pump();
    expect(controller.roleImportChoices[2]?.selected, isNot(true));
    expect(find.text('После подтверждения будет создан новый Person'), findsOneWidget);

    expect(find.byKey(const Key('role_import_select_3')), findsNothing);
    expect(find.text('Person не найден'), findsOneWidget);
    expect(find.text('генеральный директор'), findsOneWidget);
    expect(find.byType(Radio<String>), findsNothing);

    await tester.tap(find.byKey(const Key('role_import_select_0')));
    await tester.tap(find.byKey(const Key('role_import_select_2')));
    await tester.pump();
    expect(
      tester.widget<TextButton>(find.byKey(const Key('prepare_role_import_button'))).onPressed,
      isNotNull,
    );
    expect(prepareCalls, 0);
  });

  testWidgets('prepare sends explicit targets and renders frozen presentation', (tester) async {
    final controller = start();
    await show(tester, controller);
    await ground(tester, controller);
    controller.chooseRoleImportPromotion(2, 'k');
    controller.setRoleImportRowSelected(0, true);
    controller.setRoleImportRowSelected(2, true);
    await tester.pump();

    await tester.tap(find.text('Подготовить изменения'));
    await tester.pump();
    await tester.pump();

    final selections = prepareBody!['selections'] as List;
    expect(prepareBody!['source_revision'], 'rev-1');
    expect(prepareBody!['grounding_revision'], 'ground-1');
    expect(prepareBody!['items_truncated'], isFalse);
    expect(prepareBody!['items'], hasLength(4));
    expect(selections, [
      {'row_index': 0, 'person_id': 'p1'},
      {'row_index': 2, 'promotion_candidate_key': 'k'},
    ]);
    expect(prepareBody!.containsKey('role_term_id'), isFalse);
    expect(jsonEncode(prepareBody), isNot(contains('генеральный директор')));
    expect(find.text('Требует подтверждения'), findsOneWidget);
    expect(find.text('Договор'), findsWidgets);
    expect(find.textContaining('Выбрано 2 из 4'), findsOneWidget);
    expect(find.textContaining('existing Person'), findsOneWidget);
    expect(find.textContaining('Ада · новый Person'), findsOneWidget);
    expect(find.textContaining('существующая роль'), findsOneWidget);
    expect(find.textContaining('новая роль'), findsOneWidget);
    expect(find.textContaining('проект'), findsOneWidget);
    expect(find.textContaining('k'), findsNothing);
    expect(find.text('Подтвердить'), findsOneWidget);
    expect(find.text('Отклонить'), findsOneWidget);
    expect(find.text('Ничего не сохранено'), findsOneWidget);
    expect(
      tester.widget<Checkbox>(find.byKey(const Key('role_import_select_0'))).onChanged,
      isNull,
    );
  });

  testWidgets('approve shows saved counts without resume', (tester) async {
    final controller = start();
    await show(tester, controller);
    await ground(tester, controller);
    controller.setRoleImportRowSelected(0, true);
    await tester.runAsync(controller.prepareRoleImportPlan);
    await tester.pump();
    final before = controller.messages.length;

    await tester.tap(find.text('Подтвердить'));
    await tester.pump();
    await tester.pump();

    expect(approveCalls, 1);
    expect(resumeCalls, 0);
    expect(find.text('Изменения сохранены'), findsOneWidget);
    expect(find.text('Ничего не сохранено'), findsNothing);
    expect(find.textContaining('Создано людей: 1'), findsOneWidget);
    expect(find.text('Применено'), findsOneWidget);
    expect(find.text('Уже было'), findsOneWidget);
    expect(find.text('Дубликат выбранной строки'), findsOneWidget);
    expect(find.text('Подтвердить'), findsNothing);
    expect(controller.messages.length, before);
    expect(find.text('Изменить выбор'), findsNothing);
  });

  testWidgets('unchanged execution does not claim a save', (tester) async {
    approveChanged = false;
    final controller = start();
    await show(tester, controller);
    await ground(tester, controller);
    controller.setRoleImportRowSelected(0, true);
    await tester.runAsync(controller.prepareRoleImportPlan);
    await tester.runAsync(controller.approveRoleImportPlan);
    await tester.pump();

    expect(find.text('Изменений нет'), findsOneWidget);
    expect(find.text('Изменения сохранены'), findsNothing);
    expect(find.text('Ничего не сохранено'), findsNothing);
  });

  testWidgets('reject keeps nothing saved and unlocks selection', (tester) async {
    final controller = start();
    await show(tester, controller);
    await ground(tester, controller);
    controller.setRoleImportRowSelected(0, true);
    await tester.runAsync(controller.prepareRoleImportPlan);
    await tester.pump();
    await tester.tap(find.text('Отклонить'));
    await tester.pump();
    await tester.pump();

    expect(rejectCalls, 1);
    expect(resumeCalls, 0);
    expect(find.text('Отклонено'), findsOneWidget);
    expect(find.text('Ничего не сохранено'), findsOneWidget);
    await tester.tap(find.text('Изменить выбор'));
    await tester.pump();
    expect(controller.roleImportPhase, RoleImportFlowPhase.editing);
    expect(controller.roleImportChoices[0]?.selected, isTrue);
    expect(
      tester.widget<Checkbox>(find.byKey(const Key('role_import_select_0'))).onChanged,
      isNotNull,
    );
  });

  testWidgets('stale source and grounding require explicit restart', (tester) async {
    prepareStatusCode = 422;
    prepareDetail = 'role_import_source_changed';
    final controller = start();
    await show(tester, controller);
    await ground(tester, controller);
    controller.setRoleImportRowSelected(0, true);
    await tester.runAsync(controller.prepareRoleImportPlan);
    await tester.pump();
    expect(find.text('Источник изменился — извлеките роли заново'), findsOneWidget);
    expect(controller.roleGrounding, isNull);
    expect(prepareCalls, 1);

    prepareDetail = 'role_import_grounding_changed';
    await tester.runAsync(() async {
      await controller.extractRoles();
      await controller.groundRoles();
    });
    controller.setRoleImportRowSelected(0, true);
    await tester.runAsync(controller.prepareRoleImportPlan);
    await tester.pump();
    expect(find.text('Сопоставление изменилось — сопоставьте роли заново'), findsOneWidget);
    expect(controller.roleImportPreview, isNotNull);
    expect(paths.where((path) => path.endsWith('/ground')).length, 2);
  });

  testWidgets('chat plan blocks role import and voice stays off the batch', (tester) async {
    final controller = start();
    await show(tester, controller);
    await ground(tester, controller);
    controller.setRoleImportRowSelected(0, true);
    await tester.runAsync(() => controller.sendMessage('создай задачу'));
    await tester.pump();

    expect(controller.roleImportBlockedByChatPlan, isTrue);
    expect(
      tester.widget<TextButton>(find.byKey(const Key('prepare_role_import_button'))).onPressed,
      isNull,
    );
    expect(controller.messages.last.actionPlan?.plan.actions.single.toolName, 'create_task');
    expect(prepareCalls, 0);
    expect(resumeCalls, 0);
  });

  testWidgets('expiry failure drift and late responses stay local', (tester) async {
    final controller = start();
    await show(tester, controller);
    await ground(tester, controller);
    controller.setRoleImportRowSelected(0, true);
    await tester.runAsync(controller.prepareRoleImportPlan);
    await tester.pump();

    approveGate = Completer<http.Response>();
    final first = controller.approveRoleImportPlan();
    final second = controller.approveRoleImportPlan();
    approveGate!.complete(
      http.Response(
        jsonEncode(_plan(status: 'expired')),
        200,
        headers: {'content-type': 'application/json'},
      ),
    );
    await tester.runAsync(() async {
      await first;
      await second;
    });
    await tester.pump();
    expect(approveCalls, 1);
    expect(find.text('Подтверждение истекло'), findsOneWidget);
    expect(find.text('Изменения сохранены'), findsNothing);
    await tester.tap(find.text('Изменить выбор'));
    await tester.pump();
    expect(controller.roleImportPhase, RoleImportFlowPhase.editing);
    approveGate = null;

    await tester.runAsync(controller.prepareRoleImportPlan);
    await tester.pump();
    approveStatus = 'failed';
    approveFailure = 'role_import_grounding_changed';
    await tester.runAsync(controller.approveRoleImportPlan);
    await tester.pump();
    expect(find.text('Сопоставление изменилось — сопоставьте роли заново'), findsOneWidget);
    expect(find.text('Изменения сохранены'), findsNothing);

    await tester.runAsync(() async {
      await controller.extractRoles();
      await controller.groundRoles();
    });
    controller.setRoleImportRowSelected(0, true);
    await tester.runAsync(controller.prepareRoleImportPlan);
    await tester.pump();
    approveFailure = 'Не удалось применить';
    await tester.runAsync(controller.approveRoleImportPlan);
    await tester.pump();
    expect(find.text('Ошибка применения'), findsOneWidget);
    expect(find.text('Изменения сохранены'), findsNothing);
    expect(find.text('Ничего не сохранено'), findsOneWidget);

    controller.setObjectContext(
      SecretaryObject.fromJson({
        'id': 'obj-2',
        'kind': 'file',
        'title': 'Другой',
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
    await tester.pump();
    expect(controller.roleImportPlan, isNull);
    expect(controller.roleImportChoices, isEmpty);

    await tester.runAsync(() async {
      await controller.extractRoles();
      await controller.groundRoles();
    });
    controller.setRoleImportRowSelected(0, true);
    prepareGate = Completer<http.Response>();
    final late = controller.prepareRoleImportPlan();
    await tester.runAsync(controller.groundRoles);
    prepareGate!.complete(
      http.Response(
        jsonEncode(_plan(status: 'pending')),
        200,
        headers: {'content-type': 'application/json'},
      ),
    );
    await tester.runAsync(() => late);
    await tester.pump();
    expect(controller.roleImportPlan, isNull);
    expect(controller.roleImportChoices, isEmpty);
    expect(resumeCalls, 0);
  });

  testWidgets('conversation and session fences clear role import', (tester) async {
    conversationsAvailable = true;
    final controller = start();
    await show(tester, controller);
    await ground(tester, controller);
    controller.setRoleImportRowSelected(0, true);

    expect(controller.canSwitchConversation, isTrue);
    await tester.runAsync(controller.startNewConversation);
    expect(conversationCreates, 1);
    expect(controller.roleImportPreview, isNull);
    expect(controller.roleGrounding, isNull);
    expect(controller.roleImportChoices, isEmpty);
    expect(controller.roleImportPlan, isNull);
    expect(controller.roleImportError, isNull);
    expect(controller.roleImportPlanError, isNull);
    expect(controller.roleImportStale, isFalse);
    expect(controller.roleImportGroundingStale, isFalse);

    controller.setObjectContext(_source('obj-1'));
    await ground(tester, controller);
    controller.setRoleImportRowSelected(0, true);
    prepareGate = Completer<http.Response>();
    final preparing = controller.prepareRoleImportPlan();
    await tester.pump();
    expect(controller.roleImportPhase, RoleImportFlowPhase.preparing);
    expect(controller.canSwitchConversation, isFalse);
    expect(controller.conversationSwitchNotice, conversationSwitchWaitMessage);
    await tester.runAsync(controller.startNewConversation);
    expect(conversationCreates, 1);
    prepareGate!.complete(
      http.Response(
        jsonEncode(_plan(status: 'pending')),
        200,
        headers: {'content-type': 'application/json'},
      ),
    );
    prepareGate = null;
    await tester.runAsync(() => preparing);
    await tester.pump();
    expect(controller.roleImportPhase, RoleImportFlowPhase.pending);
    expect(controller.canSwitchConversation, isFalse);
    final callsAtPending = prepareCalls;
    await tester.runAsync(controller.startNewConversation);
    expect(conversationCreates, 1);
    expect(prepareCalls, callsAtPending);

    approveGate = Completer<http.Response>();
    final approving = controller.approveRoleImportPlan();
    await tester.pump();
    expect(controller.roleImportPhase, RoleImportFlowPhase.approving);
    expect(controller.canSwitchConversation, isFalse);
    await tester.runAsync(controller.startNewConversation);
    expect(conversationCreates, 1);
    expect(approveCalls, 1);
    approveGate!.complete(
      http.Response(
        jsonEncode(_plan(status: 'executed', result: _executed(changed: true))),
        200,
        headers: {'content-type': 'application/json'},
      ),
    );
    approveGate = null;
    await tester.runAsync(() => approving);
    await tester.pump();
    expect(controller.canSwitchConversation, isTrue);
    controller.roleImportPlanError = 'локальная ошибка';
    controller.roleImportStale = true;
    await tester.runAsync(controller.startNewConversation);
    expect(conversationCreates, 2);
    expect(controller.roleImportPlan, isNull);
    expect(controller.roleImportPlanError, isNull);
    expect(controller.roleImportStale, isFalse);
    expect(controller.roleImportPreview, isNull);

    controller.setObjectContext(_source('obj-1'));
    await ground(tester, controller);
    controller.setRoleImportRowSelected(0, true);
    await tester.runAsync(controller.prepareRoleImportPlan);
    rejectGate = Completer<http.Response>();
    final rejecting = controller.rejectRoleImportPlan();
    await tester.pump();
    expect(controller.roleImportPhase, RoleImportFlowPhase.rejecting);
    expect(controller.canSwitchConversation, isFalse);
    await tester.runAsync(controller.startNewConversation);
    expect(conversationCreates, 2);
    expect(rejectCalls, 1);
    rejectGate!.complete(
      http.Response(
        jsonEncode(_plan(status: 'rejected')),
        200,
        headers: {'content-type': 'application/json'},
      ),
    );
    rejectGate = null;
    await tester.runAsync(() => rejecting);
    await tester.pump();
    expect(controller.canSwitchConversation, isTrue);

    controller.resetSession();
    expect(controller.roleImportPreview, isNull);
    expect(controller.roleGrounding, isNull);
    expect(controller.roleImportChoices, isEmpty);
    expect(controller.roleImportPlan, isNull);
    expect(controller.roleImportPhase, RoleImportFlowPhase.editing);

    controller.setObjectContext(_source('obj-1'));
    await ground(tester, controller);
    controller.setRoleImportRowSelected(0, true);
    prepareGate = Completer<http.Response>();
    final latePrepare = controller.prepareRoleImportPlan();
    await tester.pump();
    final preparesBeforeReset = prepareCalls;
    controller.resetSession();
    prepareGate!.complete(
      http.Response(
        jsonEncode(_plan(status: 'pending')),
        200,
        headers: {'content-type': 'application/json'},
      ),
    );
    await tester.runAsync(() => latePrepare);
    expect(controller.roleImportPlan, isNull);
    expect(controller.roleImportPreview, isNull);
    expect(prepareCalls, preparesBeforeReset);

    controller.setObjectContext(_source('obj-1'));
    await ground(tester, controller);
    controller.setRoleImportRowSelected(0, true);
    await tester.runAsync(controller.prepareRoleImportPlan);
    approveGate = Completer<http.Response>();
    final lateApprove = controller.approveRoleImportPlan();
    await tester.pump();
    final approvesBeforeReset = approveCalls;
    controller.resetSession();
    approveGate!.complete(
      http.Response(
        jsonEncode(_plan(status: 'executed', result: _executed(changed: true))),
        200,
        headers: {'content-type': 'application/json'},
      ),
    );
    await tester.runAsync(() => lateApprove);
    expect(controller.roleImportPlan, isNull);
    expect(approveCalls, approvesBeforeReset);

    controller.setObjectContext(_source('obj-1'));
    await ground(tester, controller);
    controller.setRoleImportRowSelected(0, true);
    await tester.runAsync(controller.prepareRoleImportPlan);
    rejectGate = Completer<http.Response>();
    final lateReject = controller.rejectRoleImportPlan();
    await tester.pump();
    final rejectsBeforeReset = rejectCalls;
    controller.resetSession();
    rejectGate!.complete(
      http.Response(
        jsonEncode(_plan(status: 'rejected')),
        200,
        headers: {'content-type': 'application/json'},
      ),
    );
    await tester.runAsync(() => lateReject);
    expect(controller.roleImportPlan, isNull);
    expect(rejectCalls, rejectsBeforeReset);
    expect(resumeCalls, 0);
  });
}

SecretaryObject _source(String id) {
  return SecretaryObject.fromJson({
    'id': id,
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
  });
}
