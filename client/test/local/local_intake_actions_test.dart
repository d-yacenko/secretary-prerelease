import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:path/path.dart' as p;
import 'package:personal_secretary/api/api_error.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/assistant/assistant_controller.dart';
import 'package:personal_secretary/local/local_file_intake_service.dart';
import 'package:personal_secretary/local/local_intake_actions.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../test_secretary_api_client.dart';

http.Response _jsonResponse(Object body, {int statusCode = 200}) {
  return http.Response.bytes(
    utf8.encode(jsonEncode(body)),
    statusCode,
    headers: {'content-type': 'application/json; charset=utf-8'},
  );
}

Map<String, dynamic> _objectJson({
  required String id,
  required String title,
}) {
  return {
    'id': id,
    'kind': 'file',
    'title': title,
    'body': null,
    'provider': 'local_device',
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
  };
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory tempDir;

  setUp(() {
    SharedPreferences.setMockInitialValues({
      'secretary_device_key': 'device-key-1',
      'secretary_device_display_name': 'Test device',
    });
    tempDir = Directory.systemTemp.createTempSync('intake-actions-test-');
  });

  tearDown(() {
    if (tempDir.existsSync()) {
      tempDir.deleteSync(recursive: true);
    }
  });

  testWidgets('multiple dropped files prompt active context choice', (tester) async {
    final fileA = File('${tempDir.path}/a.txt');
    final fileB = File('${tempDir.path}/b.txt');
    fileA.writeAsStringSync('alpha');
    fileB.writeAsStringSync('beta');

    int intakeCount = 0;
    int assistantPosts = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/message') {
        assistantPosts += 1;
      }
      if (request.url.path == '/local/devices/register') {
        return _jsonResponse({
          'device_id': 'device-1',
          'device_key': 'device-key-1',
          'display_name': 'Test device',
          'created': true,
        }, statusCode: 201);
      }
      if (request.url.path == '/local/files/client-intake') {
        intakeCount += 1;
        final objectId = intakeCount == 1 ? 'obj-a' : 'obj-b';
        return _jsonResponse({
          'object_id': objectId,
          'status': 'created',
          'jobs_enqueued': 0,
          'representations_created': 1,
          'metadata_only': false,
        }, statusCode: 201);
      }
      if (request.url.path == '/objects/obj-a') {
        return _jsonResponse(_objectJson(id: 'obj-a', title: 'a.txt'));
      }
      if (request.url.path == '/objects/obj-b') {
        return _jsonResponse(_objectJson(id: 'obj-b', title: 'b.txt'));
      }
      return http.Response('{}', 404);
    });

    final apiClient = testSecretaryApiClient(mock);
    apiClient.configure(baseUrl: 'https://example.com', token: 'token');
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final assistant = AssistantController(apiClient: apiClient, authController: auth);
    final stubIntake = _StubLocalFileIntakeService(apiClient);
    final actions = LocalIntakeActions(
      apiClient: apiClient,
      authController: auth,
      assistantController: assistant,
      intakeService: stubIntake,
    );

    late BuildContext actionContext;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) {
            actionContext = context;
            return const Scaffold(body: SizedBox());
          },
        ),
      ),
    );

    final pending = actions.registerDroppedFiles(
      actionContext,
      [fileA.path, fileB.path],
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    expect(find.text('Выберите активный контекст'), findsOneWidget);
    expect(find.text('a.txt'), findsOneWidget);
    expect(find.text('b.txt'), findsOneWidget);

    await tester.tap(find.text('b.txt'));
    await tester.pump();
    await pending;

    expect(assistant.objectContext?.id, 'obj-b');
    expect(assistant.objectContext?.title, 'b.txt');
    expect(stubIntake.registerCalls, 2);
    expect(assistantPosts, 0);
    expect(find.textContaining('Добавлено файлов: 2'), findsOneWidget);
    expect(find.textContaining('Активный контекст: b.txt'), findsOneWidget);
  });

  testWidgets('assistant drag/drop sends explicit intake mode', (tester) async {
    final file = File('${tempDir.path}/assistant-drop.txt');
    file.writeAsStringSync('assistant');

    String? intakeBody;
    final mock = MockClient((request) async {
      if (request.url.path == '/local/devices/register') {
        return _jsonResponse({
          'device_id': 'device-1',
          'device_key': 'device-key-1',
          'display_name': 'Test device',
          'created': true,
        }, statusCode: 201);
      }
      if (request.url.path == '/local/files/client-intake') {
        intakeBody = request.body;
        return _jsonResponse({
          'object_id': 'obj-assistant',
          'status': 'created',
          'jobs_enqueued': 0,
          'representations_created': 1,
          'metadata_only': false,
        }, statusCode: 201);
      }
      if (request.url.path == '/objects/obj-assistant') {
        return _jsonResponse(_objectJson(id: 'obj-assistant', title: 'assistant-drop.txt'));
      }
      return http.Response('{}', 404);
    });

    final apiClient = testSecretaryApiClient(mock);
    apiClient.configure(baseUrl: 'https://example.com', token: 'token');
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final actions = LocalIntakeActions(
      apiClient: apiClient,
      authController: auth,
      forInbox: false,
    );

    late BuildContext actionContext;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) {
            actionContext = context;
            return const Scaffold(body: SizedBox());
          },
        ),
      ),
    );

    await tester.runAsync(
      () => actions.registerDroppedFiles(actionContext, [file.path]),
    );
    await tester.pump();

    final decoded = jsonDecode(intakeBody!) as Map<String, dynamic>;
    expect(decoded['intake_mode'], 'explicit_local');
  });

  testWidgets('assistant paperclip path sends explicit intake mode', (tester) async {
    final file = File('${tempDir.path}/paperclip.txt');
    file.writeAsStringSync('paperclip');

    final apiClient = testSecretaryApiClient(
      MockClient((_) async => http.Response('{}', 404)),
    );
    final stubIntake = _CapturingStubLocalFileIntakeService(apiClient);
    apiClient.configure(baseUrl: 'https://example.com', token: 'token');
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final actions = LocalIntakeActions(
      apiClient: apiClient,
      authController: auth,
      forInbox: false,
      intakeService: stubIntake,
    );

    late BuildContext actionContext;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) {
            actionContext = context;
            return const Scaffold(body: SizedBox());
          },
        ),
      ),
    );

    await tester.runAsync(
      () => actions.registerDroppedFiles(actionContext, [file.path]),
    );
    await tester.pump();

    expect(stubIntake.capturedIntakeModes, ['explicit_local']);
  });

  testWidgets('user-triggered non-inbox local intake sends explicit intake mode', (tester) async {
    final file = File('${tempDir.path}/plain.txt');
    file.writeAsStringSync('plain');

    String? intakeBody;
    final mock = MockClient((request) async {
      if (request.url.path == '/local/devices/register') {
        return _jsonResponse({
          'device_id': 'device-1',
          'device_key': 'device-key-1',
          'display_name': 'Test device',
          'created': true,
        }, statusCode: 201);
      }
      if (request.url.path == '/local/files/client-intake') {
        intakeBody = request.body;
        return _jsonResponse({
          'object_id': 'obj-plain',
          'status': 'created',
          'jobs_enqueued': 0,
          'representations_created': 1,
          'metadata_only': false,
        }, statusCode: 201);
      }
      if (request.url.path == '/objects/obj-plain') {
        return _jsonResponse(_objectJson(id: 'obj-plain', title: 'plain.txt'));
      }
      return http.Response('{}', 404);
    });

    final apiClient = testSecretaryApiClient(mock);
    apiClient.configure(baseUrl: 'https://example.com', token: 'token');
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final actions = LocalIntakeActions(
      apiClient: apiClient,
      authController: auth,
    );

    late BuildContext actionContext;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) {
            actionContext = context;
            return const Scaffold(body: SizedBox());
          },
        ),
      ),
    );

    await tester.runAsync(
      () => actions.registerDroppedFiles(actionContext, [file.path]),
    );
    await tester.pump();

    final decoded = jsonDecode(intakeBody!) as Map<String, dynamic>;
    expect(decoded['intake_mode'], 'explicit_local');
  });

  testWidgets('multi-file assistant drop sends explicit intake mode for each file', (tester) async {
    final fileA = File('${tempDir.path}/a.txt');
    final fileB = File('${tempDir.path}/b.txt');
    fileA.writeAsStringSync('alpha');
    fileB.writeAsStringSync('beta');

    final apiClient = testSecretaryApiClient(
      MockClient((_) async => http.Response('{}', 404)),
    );
    final stubIntake = _CapturingStubLocalFileIntakeService(apiClient);
    apiClient.configure(baseUrl: 'https://example.com', token: 'token');
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final assistant = AssistantController(apiClient: apiClient, authController: auth);
    final actions = LocalIntakeActions(
      apiClient: apiClient,
      authController: auth,
      assistantController: assistant,
      forInbox: false,
      intakeService: stubIntake,
      chooseActiveContext: (_, objects) async => objects.first,
    );

    late BuildContext actionContext;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) {
            actionContext = context;
            return const Scaffold(body: SizedBox());
          },
        ),
      ),
    );

    await tester.runAsync(
      () => actions.registerDroppedFiles(actionContext, [fileA.path, fileB.path]),
    );
    await tester.pump();

    expect(stubIntake.capturedIntakeModes, ['explicit_local', 'explicit_local']);
  });

  testWidgets('inbox local intake sends explicit intake mode', (tester) async {
    final file = File('${tempDir.path}/inbox.txt');
    file.writeAsStringSync('inbox');

    String? intakeBody;
    final mock = MockClient((request) async {
      if (request.url.path == '/local/devices/register') {
        return _jsonResponse({
          'device_id': 'device-1',
          'device_key': 'device-key-1',
          'display_name': 'Test device',
          'created': true,
        }, statusCode: 201);
      }
      if (request.url.path == '/local/files/client-intake') {
        intakeBody = request.body;
        return _jsonResponse({
          'object_id': 'obj-inbox',
          'status': 'created',
          'jobs_enqueued': 0,
          'representations_created': 1,
          'metadata_only': false,
        }, statusCode: 201);
      }
      if (request.url.path == '/objects/obj-inbox') {
        return _jsonResponse(_objectJson(id: 'obj-inbox', title: 'inbox.txt'));
      }
      return http.Response('{}', 404);
    });

    final apiClient = testSecretaryApiClient(mock);
    apiClient.configure(baseUrl: 'https://example.com', token: 'token');
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final actions = LocalIntakeActions(
      apiClient: apiClient,
      authController: auth,
      forInbox: true,
    );

    late BuildContext actionContext;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) {
            actionContext = context;
            return const Scaffold(body: SizedBox());
          },
        ),
      ),
    );

    await tester.runAsync(
      () => actions.registerDroppedFiles(actionContext, [file.path]),
    );
    await tester.pump();

    final decoded = jsonDecode(intakeBody!) as Map<String, dynamic>;
    expect(decoded['intake_mode'], 'explicit_local');
  });

  testWidgets('failed local intake does not invoke success callback', (tester) async {
    final file = File('${tempDir.path}/fail.txt');
    file.writeAsStringSync('fail');

    int successCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/local/devices/register') {
        return _jsonResponse({
          'device_id': 'device-1',
          'device_key': 'device-key-1',
          'display_name': 'Test device',
          'created': true,
        }, statusCode: 201);
      }
      if (request.url.path == '/local/files/client-intake') {
        return _jsonResponse({'detail': 'intake failed'}, statusCode: 400);
      }
      return http.Response('{}', 404);
    });

    final apiClient = testSecretaryApiClient(mock);
    apiClient.configure(baseUrl: 'https://example.com', token: 'token');
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final actions = LocalIntakeActions(
      apiClient: apiClient,
      authController: auth,
      forInbox: true,
      onIntakeSuccess: () => successCalls++,
    );

    late BuildContext actionContext;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) {
            actionContext = context;
            return const Scaffold(body: SizedBox());
          },
        ),
      ),
    );

    await tester.runAsync(
      () => actions.registerDroppedFiles(actionContext, [file.path]),
    );
    await tester.pump();

    expect(successCalls, 0);
  });

  testWidgets('mixed local drop with partial success invokes one success callback', (tester) async {
    final okFile = File('${tempDir.path}/ok.txt');
    final badFile = File('${tempDir.path}/bad.txt');
    okFile.writeAsStringSync('ok');
    badFile.writeAsStringSync('bad');

    int successCalls = 0;
    final apiClient = testSecretaryApiClient(MockClient((_) async => http.Response('{}', 404)));
    apiClient.configure(baseUrl: 'https://example.com', token: 'token');
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final stubIntake = _PartialFailureStubLocalFileIntakeService(apiClient);
    final actions = LocalIntakeActions(
      apiClient: apiClient,
      authController: auth,
      forInbox: true,
      intakeService: stubIntake,
      onIntakeSuccess: () => successCalls++,
    );

    late BuildContext actionContext;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) {
            actionContext = context;
            return const Scaffold(body: SizedBox());
          },
        ),
      ),
    );

    await actions.registerDroppedFiles(actionContext, [okFile.path, badFile.path]);
    await tester.pump();

    expect(successCalls, 1);
    expect(stubIntake.registerCalls, 2);
  });

  test('registerFileAndFetch loads object for multi-file intake flow', () async {
    final fileA = File('${tempDir.path}/a.txt');
    final fileB = File('${tempDir.path}/b.txt');
    fileA.writeAsStringSync('alpha');
    fileB.writeAsStringSync('beta');

    var intakeCount = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/local/devices/register') {
        return _jsonResponse({
          'device_id': 'device-1',
          'device_key': 'device-key-1',
          'display_name': 'Test device',
          'created': true,
        }, statusCode: 201);
      }
      if (request.url.path == '/local/files/client-intake') {
        intakeCount += 1;
        final objectId = intakeCount == 1 ? 'obj-a' : 'obj-b';
        return _jsonResponse({
          'object_id': objectId,
          'status': 'created',
          'jobs_enqueued': 0,
          'representations_created': 1,
          'metadata_only': false,
        }, statusCode: 201);
      }
      if (request.url.path == '/objects/obj-a') {
        return _jsonResponse(_objectJson(id: 'obj-a', title: 'a.txt'));
      }
      if (request.url.path == '/objects/obj-b') {
        return _jsonResponse(_objectJson(id: 'obj-b', title: 'b.txt'));
      }
      return http.Response('{}', 404);
    });

    final apiClient = testSecretaryApiClient(mock);
    apiClient.configure(baseUrl: 'https://example.com', token: 'token');
    final service = LocalFileIntakeService(apiClient: apiClient);
    final objectA = await service.registerFileAndFetch(fileA);
    final objectB = await service.registerFileAndFetch(fileB);

    expect(objectA.title, 'a.txt');
    expect(objectB.title, 'b.txt');
    expect(intakeCount, 2);
  });

  test('failed local intake surfaces API error', () async {
    final file = File('${tempDir.path}/fail.txt');
    file.writeAsStringSync('fail');

    final mock = MockClient((request) async {
      if (request.url.path == '/local/devices/register') {
        return _jsonResponse({
          'device_id': 'device-1',
          'device_key': 'device-key-1',
          'display_name': 'Test device',
          'created': true,
        }, statusCode: 201);
      }
      if (request.url.path == '/local/files/client-intake') {
        return _jsonResponse({'detail': 'intake failed'}, statusCode: 400);
      }
      return http.Response('{}', 404);
    });

    final apiClient = testSecretaryApiClient(mock);
    apiClient.configure(baseUrl: 'https://example.com', token: 'token');
    final service = LocalFileIntakeService(apiClient: apiClient);
    expect(() => service.registerFile(file), throwsA(isA<ServerException>()));
  });
}

class _CapturingStubLocalFileIntakeService extends _StubLocalFileIntakeService {
  _CapturingStubLocalFileIntakeService(super.apiClient);

  final List<String?> capturedIntakeModes = [];

  @override
  Future<SecretaryObject> registerFileAndFetch(
    File file, {
    String? intakeMode,
  }) async {
    capturedIntakeModes.add(intakeMode);
    return super.registerFileAndFetch(file, intakeMode: intakeMode);
  }
}

class _PartialFailureStubLocalFileIntakeService extends _StubLocalFileIntakeService {
  _PartialFailureStubLocalFileIntakeService(super.apiClient);

  @override
  Future<SecretaryObject> registerFileAndFetch(
    File file, {
    String? intakeMode,
  }) async {
    registerCalls += 1;
    if (p.basename(file.path) == 'bad.txt') {
      throw ServerException('intake failed');
    }
    return SecretaryObject(
      id: 'obj-ok',
      kind: 'document',
      title: p.basename(file.path),
      metadata: {},
      origin: 'user',
      state: 'confirmed',
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    );
  }
}

class _StubLocalFileIntakeService extends LocalFileIntakeService {
  _StubLocalFileIntakeService(SecretaryApiClient apiClient)
      : super(apiClient: apiClient);

  int registerCalls = 0;

  @override
  Future<SecretaryObject> registerFileAndFetch(
    File file, {
    String? intakeMode,
  }) async {
    registerCalls += 1;
    final title = p.basename(file.path);
    final objectId = switch (title) {
      'a.txt' => 'obj-a',
      'b.txt' => 'obj-b',
      'ok.txt' => 'obj-ok',
      _ => 'obj-${title.hashCode}',
    };
    return SecretaryObject(
      id: objectId,
      kind: 'document',
      title: title,
      metadata: {},
      origin: 'user',
      state: 'confirmed',
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    );
  }
}
