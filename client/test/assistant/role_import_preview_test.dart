import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:path/path.dart' as p;
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/assistant/assistant_controller.dart';
import 'package:personal_secretary/assistant/role_import_preview.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/local/extraction/extraction_constants.dart';
import 'package:personal_secretary/local/local_file_intake_service.dart';
import 'package:personal_secretary/local/local_intake_actions.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../test_secretary_api_client.dart';

const _png = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 1];
const _jpeg = [0xFF, 0xD8, 0xFF, 2];
const _webp = [0x52, 0x49, 0x46, 0x46, 0, 0, 0, 0, 0x57, 0x45, 0x42, 0x50, 3];

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory tempDir;

  setUp(() {
    SharedPreferences.setMockInitialValues({
      'secretary_device_key': 'device-key-1',
      'secretary_device_display_name': 'Test device',
    });
    tempDir = Directory.systemTemp.createTempSync('role-import-preview-');
  });

  tearDown(() {
    if (tempDir.existsSync()) {
      tempDir.deleteSync(recursive: true);
    }
  });

  testWidgets('paperclip and drop send raster bytes and keep documents local', (
    tester,
  ) async {
    final png = File('${tempDir.path}/shot.png')..writeAsBytesSync(_png);
    final jpeg = File('${tempDir.path}/shot.jpeg')..writeAsBytesSync(_jpeg);
    final webp = File('${tempDir.path}/shot.webp')..writeAsBytesSync(_webp);
    final note = File('${tempDir.path}/note.txt')..writeAsStringSync('hello');

    final registerBodies = <String>[];
    var extractCalls = 0;
    var localIntakeCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/resources/register') {
        registerBodies.add(utf8.decode(request.bodyBytes, allowMalformed: true));
        final name = p.basename(registerBodies.last.contains('shot.png')
            ? 'shot.png'
            : registerBodies.last.contains('shot.jpeg')
                ? 'shot.jpeg'
                : 'shot.webp');
        return _json({
          'object_id': 'obj-$name',
          'status': 'created',
          'kind': 'file',
          'title': name,
          'canonical_uri': null,
          'provider': 'upload',
          'external_id': 'hash',
          'jobs_enqueued': 0,
          'representations_created': 0,
        }, statusCode: 201);
      }
      if (request.url.path.startsWith('/objects/')) {
        final id = request.url.path.split('/').last;
        return _json(_object(id: id, title: id.replaceFirst('obj-', '')));
      }
      if (request.url.path == '/people/role-import/extract') {
        extractCalls += 1;
        return _json(_proposal(sourceId: 'unused'));
      }
      if (request.url.path == '/local/files/client-intake') {
        localIntakeCalls += 1;
        return http.Response('{}', 500);
      }
      return http.Response('{}', 404);
    });

    final apiClient = testSecretaryApiClient(mock);
    apiClient.configure(baseUrl: 'https://example.com', token: 'secret-token');
    final auth = _auth(apiClient);
    final assistant = AssistantController(apiClient: apiClient, authController: auth);
    final intake = _CountingIntake(apiClient);
    final actions = LocalIntakeActions(
      apiClient: apiClient,
      authController: auth,
      assistantController: assistant,
      intakeService: intake,
    );
    final context = await _context(tester);

    FilePicker.platform = _FakeFilePicker(
      pickFilesResult: FilePickerResult([
        PlatformFile(name: 'shot.png', path: png.path, size: _png.length),
      ]),
    );
    await tester.runAsync(() => actions.pickAndRegisterFile(context));
    await tester.pump();
    await tester.runAsync(() => actions.registerDroppedFiles(context, [jpeg.path]));
    await tester.pump();
    await tester.runAsync(() => actions.registerDroppedFiles(context, [webp.path]));
    await tester.pump();

    expect(registerBodies, hasLength(3));
    for (final body in registerBodies) {
      expect(body, contains('"ingest_content":false'));
      expect(body, isNot(contains(tempDir.path)));
      expect(body, isNot(contains('secret-token')));
    }
    expect(assistant.objectContext?.id, 'obj-shot.webp');
    expect(extractCalls, 0);
    expect(intake.registerCalls, 0);
    expect(localIntakeCalls, 0);

    await tester.runAsync(() => actions.registerDroppedFiles(context, [note.path]));
    await tester.pump();
    expect(intake.registerCalls, 1);
    expect(registerBodies, hasLength(3));
    expect(assistant.objectContext?.title, 'note.txt');
    expect(extractCalls, 0);
  });

  testWidgets('unsupported image is a local error and is not uploaded', (
    tester,
  ) async {
    final gif = File('${tempDir.path}/anim.gif')..writeAsBytesSync([1, 2, 3]);
    var registerCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/resources/register' ||
          request.url.path == '/local/files/client-intake') {
        registerCalls += 1;
      }
      return http.Response('{}', 404);
    });
    final apiClient = testSecretaryApiClient(mock);
    apiClient.configure(baseUrl: 'https://example.com', token: 'secret-token');
    final intake = _CountingIntake(apiClient);
    final actions = LocalIntakeActions(
      apiClient: apiClient,
      authController: _auth(apiClient),
      intakeService: intake,
    );
    final context = await _context(tester);
    await tester.runAsync(() => actions.registerDroppedFiles(context, [gif.path]));
    await tester.pump();
    expect(find.text(kUnsupportedRoleImageMessage), findsOneWidget);
    expect(registerCalls, 0);
    expect(intake.registerCalls, 0);
  });

  testWidgets('explicit extract previews a draft and ignores a stale response', (
    tester,
  ) async {
    final firstGate = Completer<void>();
    var extractCalls = 0;
    String? sentBody;
    final mock = MockClient((request) async {
      if (request.url.path == '/assistant/conversations/current' ||
          request.url.path == '/assistant/conversations') {
        return http.Response('{}', 404);
      }
      if (request.url.path == '/people/role-import/extract') {
        extractCalls += 1;
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        final sourceId = body['source_object_id'] as String;
        if (sourceId == 'source-c') {
          return _json(_proposal(sourceId: sourceId));
        }
        if (extractCalls == 1) {
          await firstGate.future;
          return _json(
            _proposal(
              sourceId: sourceId,
              items: [
                _item(name: 'Старая', role: 'Архив'),
              ],
            ),
          );
        }
        return _json(
          _proposal(
            sourceId: sourceId,
            items: [
              _item(
                name: 'Анна',
                role: 'Директор',
                contextText: 'правление',
                evidence: 'Анна, директор',
                locator: 'стр. 1',
              ),
            ],
            sourceTruncated: true,
          ),
        );
      }
      if (request.url.path == '/assistant/message') {
        sentBody = request.body;
        return _json({
          'answer': 'ok',
          'references': [],
          'affected_objects': [],
        });
      }
      return http.Response('{}', 404);
    });
    final apiClient = testSecretaryApiClient(mock);
    apiClient.configure(baseUrl: 'https://example.com', token: 'secret-token');
    final auth = _auth(apiClient);
    final assistant = AssistantController(apiClient: apiClient, authController: auth);
    assistant.setObjectContext(_secretaryObject('source-a', 'a.png'));

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ListenableBuilder(
            listenable: assistant,
            builder: (context, _) => RoleImportPreviewPanel(
              loading: assistant.roleImportLoading,
              error: assistant.roleImportError,
              preview: assistant.roleImportPreview,
              onExtract: assistant.extractRoles,
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.byKey(const Key('extract_roles_button')));
    await tester.pump();
    expect(extractCalls, 1);
    expect(assistant.messages, isEmpty);

    assistant.setObjectContext(_secretaryObject('source-b', 'b.png'));
    firstGate.complete();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 20));
    expect(assistant.roleImportPreview, isNull);
    expect(find.text('Старая'), findsNothing);

    await tester.tap(find.byKey(const Key('extract_roles_button')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 20));
    expect(extractCalls, 2);
    expect(find.text('Черновик извлечения ролей'), findsOneWidget);
    expect(find.text('Ничего не сохранено'), findsOneWidget);
    expect(find.text('Анна'), findsOneWidget);
    expect(find.text('Директор'), findsOneWidget);
    expect(find.text('правление'), findsOneWidget);
    expect(find.text('Анна, директор'), findsOneWidget);
    expect(find.text('стр. 1'), findsOneWidget);
    expect(find.text('Источник или список строк обрезан'), findsOneWidget);
    expect(find.text('Сохранить'), findsNothing);
    expect(find.text('Подтвердить'), findsNothing);
    expect(assistant.messages, isEmpty);

    assistant.setObjectContext(_secretaryObject('source-c', 'c.png'));
    await tester.pump();
    expect(find.text('Анна'), findsNothing);

    await assistant.extractRoles();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 20));
    expect(find.text('Роли не найдены'), findsOneWidget);
    expect(find.text('Ничего не сохранено'), findsOneWidget);

    await assistant.sendMessage('обычный вопрос');
    expect(sentBody, isNotNull);
    final sent = jsonDecode(sentBody!) as Map<String, dynamic>;
    expect(sent['message'], 'обычный вопрос');
    expect(sent['context_object_id'], 'source-c');
    expect(sent.containsKey('image'), isFalse);
    expect(sentBody, isNot(contains('data:image')));
  });

  testWidgets('extraction error can be retried', (tester) async {
    var extractCalls = 0;
    final mock = MockClient((request) async {
      if (request.url.path == '/people/role-import/extract') {
        extractCalls += 1;
        if (extractCalls == 1) {
          return http.Response(
            jsonEncode({'detail': 'source has no stored text'}),
            422,
            headers: {'content-type': 'application/json'},
          );
        }
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        return _json(
          _proposal(
            sourceId: body['source_object_id'] as String,
            items: [_item(name: 'Борис', role: 'Юрист')],
          ),
        );
      }
      return http.Response('{}', 404);
    });
    final apiClient = testSecretaryApiClient(mock);
    apiClient.configure(baseUrl: 'https://example.com', token: 'secret-token');
    final assistant = AssistantController(
      apiClient: apiClient,
      authController: _auth(apiClient),
    );
    assistant.setObjectContext(_secretaryObject('source-a', 'a.png'));
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ListenableBuilder(
            listenable: assistant,
            builder: (context, _) => RoleImportPreviewPanel(
              loading: assistant.roleImportLoading,
              error: assistant.roleImportError,
              preview: assistant.roleImportPreview,
              onExtract: assistant.extractRoles,
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.byKey(const Key('extract_roles_button')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 20));
    expect(find.byKey(const Key('role_import_error')), findsOneWidget);
    await tester.tap(find.byKey(const Key('role_import_retry')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 20));
    expect(extractCalls, 2);
    expect(find.text('Борис'), findsOneWidget);
    expect(find.text('Ничего не сохранено'), findsOneWidget);
  });
}

http.Response _json(Object body, {int statusCode = 200}) {
  return http.Response.bytes(
    utf8.encode(jsonEncode(body)),
    statusCode,
    headers: {'content-type': 'application/json; charset=utf-8'},
  );
}

Map<String, dynamic> _object({required String id, required String title}) {
  return {
    'id': id,
    'kind': 'file',
    'title': title,
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
  };
}

SecretaryObject _secretaryObject(String id, String title) {
  return SecretaryObject.fromJson(_object(id: id, title: title));
}

Map<String, dynamic> _item({
  required String name,
  required String role,
  String? contextText,
  String evidence = 'цитата',
  String? locator,
}) {
  return {
    'person_name': name,
    'role': role,
    'context': contextText,
    'evidence_text': evidence,
    'source_locator': locator,
  };
}

Map<String, dynamic> _proposal({
  required String sourceId,
  List<Map<String, dynamic>> items = const [],
  bool sourceTruncated = false,
  bool itemsTruncated = false,
}) {
  return {
    'source_object_id': sourceId,
    'source_revision': 'abc',
    'source_kind': 'image',
    'source_truncated': sourceTruncated,
    'items_truncated': itemsTruncated,
    'items': items,
  };
}

AuthController _auth(SecretaryApiClient apiClient) {
  final auth = AuthController(
    apiClient: apiClient,
    tokenStore: FakeTokenStore(),
    serverUrlStore: FakeServerUrlStore(),
  );
  auth.status = AuthStatus.authenticated;
  return auth;
}

Future<BuildContext> _context(WidgetTester tester) async {
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
  return actionContext;
}

class _CountingIntake extends LocalFileIntakeService {
  _CountingIntake(SecretaryApiClient apiClient) : super(apiClient: apiClient);

  int registerCalls = 0;

  @override
  Future<SecretaryObject> registerFileAndFetch(
    File file, {
    String? intakeMode,
  }) async {
    registerCalls += 1;
    return SecretaryObject(
      id: 'obj-note',
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

class _FakeFilePicker extends FilePicker {
  _FakeFilePicker({this.pickFilesResult});

  final FilePickerResult? pickFilesResult;

  @override
  Future<FilePickerResult?> pickFiles({
    String? dialogTitle,
    String? initialDirectory,
    FileType type = FileType.any,
    List<String>? allowedExtensions,
    Function(FilePickerStatus)? onFileLoading,
    bool allowCompression = true,
    int compressionQuality = 30,
    bool allowMultiple = false,
    bool withData = false,
    bool withReadStream = false,
    bool lockParentWindow = false,
    bool readSequential = false,
  }) async {
    return pickFilesResult;
  }

  @override
  Future<String?> getDirectoryPath({
    String? dialogTitle,
    bool lockParentWindow = false,
    String? initialDirectory,
  }) async {
    return null;
  }
}
