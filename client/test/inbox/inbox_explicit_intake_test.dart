import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/capture/capture_controller.dart';
import 'package:personal_secretary/inbox/inbox_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  const baseUrl = 'https://secretary.example';
  const token = 'inbox-token';

  Map<String, dynamic> inboxJson({
    List<Map<String, dynamic>>? recentSources,
  }) {
    return {
      'unresolved_notifications': [],
      'recent_source_objects': recentSources ?? [],
      'source_sync_status': [],
    };
  }

  Map<String, dynamic> intakeLinkJson({
    required String objectId,
    required String status,
    String contentStatus = 'metadata_only',
    int contentJobsEnqueued = 0,
  }) {
    return {
      'object_id': objectId,
      'provider': 'google_drive',
      'kind': 'file',
      'status': status,
      'content_status': contentStatus,
      'content_jobs_enqueued': contentJobsEnqueued,
    };
  }

  Widget buildInbox(
    MockClient mock, {
    GlobalKey<InboxScreenState>? inboxKey,
    Duration passiveRefreshInterval = const Duration(seconds: 30),
  }) {
    final apiClient = SecretaryApiClient(httpClient: mock);
    apiClient.configure(baseUrl: baseUrl, token: token);
    final auth = AuthController(
      apiClient: apiClient,
      tokenStore: FakeTokenStore(),
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    final capture = CaptureController(apiClient: apiClient, authController: auth);
    return MaterialApp(
      home: Scaffold(
        body: InboxScreen(
          key: inboxKey,
          apiClient: apiClient,
          authController: auth,
          captureController: capture,
          passiveRefreshInterval: passiveRefreshInterval,
        ),
      ),
    );
  }

  testWidgets('shows link input and add button', (tester) async {
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(jsonEncode(inboxJson()), 200);
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('inbox_link_input')), findsOneWidget);
    expect(find.byKey(const Key('inbox_link_add_button')), findsOneWidget);
    expect(find.byTooltip('Добавить во входящие'), findsOneWidget);
    expect(find.byIcon(Icons.move_to_inbox_outlined), findsOneWidget);
  });

  testWidgets('empty inbox still shows intake controls', (tester) async {
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(jsonEncode(inboxJson()), 200);
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    expect(find.text('Входящие пусты'), findsOneWidget);
    expect(find.byKey(const Key('inbox_link_input')), findsOneWidget);
    expect(find.byKey(const Key('inbox_add_file_button')), findsOneWidget);
    expect(find.byKey(const Key('inbox_add_folder_button')), findsOneWidget);
  });

  testWidgets('add submits trimmed link to intake endpoint', (tester) async {
    String? intakeBody;
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(jsonEncode(inboxJson()), 200);
        }
        if (request.url.path == '/intake/link') {
          intakeBody = request.body;
          return http.Response(
            jsonEncode(intakeLinkJson(objectId: 'drive-obj-1', status: 'created')),
            200,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
      find.byKey(const Key('inbox_link_input')),
      '  https://drive.google.com/file/d/abc/view  ',
    );
    await tester.tap(find.byKey(const Key('inbox_link_add_button')));
    await tester.pump();

    final decoded = jsonDecode(intakeBody!) as Map<String, dynamic>;
    expect(decoded['url'], 'https://drive.google.com/file/d/abc/view');
  });

  testWidgets('successful link intake refreshes inbox', (tester) async {
    int inboxCalls = 0;
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          inboxCalls++;
          final sources = inboxCalls >= 2
              ? <Map<String, dynamic>>[
                  {
                    'id': 'drive-obj-1',
                    'title': 'Imported drive file',
                    'kind': 'file',
                    'provider': 'google_drive',
                    'state': 'observed',
                    'status': null,
                    'primary_at': '2026-08-31T10:00:00Z',
                    'excerpt': 'body',
                  },
                ]
              : <Map<String, dynamic>>[];
          return http.Response(jsonEncode(inboxJson(recentSources: sources)), 200);
        }
        if (request.url.path == '/intake/link') {
          return http.Response(
            jsonEncode(intakeLinkJson(objectId: 'drive-obj-1', status: 'created')),
            200,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
      find.byKey(const Key('inbox_link_input')),
      'https://drive.google.com/file/d/abc/view',
    );
    await tester.tap(find.byKey(const Key('inbox_link_add_button')));
    await tester.pumpAndSettle();

    expect(inboxCalls, greaterThanOrEqualTo(2));
    expect(find.text('Imported drive file'), findsOneWidget);
  });

  testWidgets('link intake snackbar reflects ready content status', (tester) async {
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(jsonEncode(inboxJson()), 200);
        }
        if (request.url.path == '/intake/link') {
          return http.Response(
            jsonEncode({
              'object_id': 'drive-obj-1',
              'provider': 'google_drive',
              'kind': 'file',
              'status': 'unchanged',
              'content_status': 'ready',
              'content_jobs_enqueued': 0,
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
      find.byKey(const Key('inbox_link_input')),
      'https://drive.google.com/file/d/abc/view',
    );
    await tester.tap(find.byKey(const Key('inbox_link_add_button')));
    await tester.pumpAndSettle();

    expect(find.text('Содержимое уже проиндексировано'), findsOneWidget);
  });

  testWidgets('link intake snackbar reflects pending content status', (tester) async {
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(jsonEncode(inboxJson()), 200);
        }
        if (request.url.path == '/intake/link') {
          return http.Response(
            jsonEncode({
              'object_id': 'drive-obj-2',
              'provider': 'google_drive',
              'kind': 'file',
              'status': 'created',
              'content_status': 'pending',
              'content_jobs_enqueued': 1,
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
      find.byKey(const Key('inbox_link_input')),
      'https://drive.google.com/file/d/abc/view',
    );
    await tester.tap(find.byKey(const Key('inbox_link_add_button')));
    await tester.pumpAndSettle();

    expect(find.text('Добавлено, содержимое обрабатывается'), findsOneWidget);
  });

  testWidgets('link intake success statuses keep inbox visible', (tester) async {
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(
            jsonEncode(inboxJson(
              recentSources: [
                {
                  'id': 'email-1',
                  'title': 'Existing inbox row',
                  'kind': 'email',
                  'provider': 'gmail',
                  'state': 'observed',
                  'status': null,
                  'primary_at': '2026-08-31T10:00:00Z',
                  'excerpt': 'body',
                },
              ],
            )),
            200,
          );
        }
        if (request.url.path == '/intake/link') {
          return http.Response(
            jsonEncode(
              intakeLinkJson(
                objectId: 'drive-obj-1',
                status: 'unchanged',
                contentStatus: 'ready',
              ),
            ),
            200,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
      find.byKey(const Key('inbox_link_input')),
      'https://drive.google.com/file/d/abc/view',
    );
    await tester.tap(find.byKey(const Key('inbox_link_add_button')));
    await tester.pumpAndSettle();

    expect(find.text('Existing inbox row'), findsOneWidget);
    expect(find.text('Содержимое уже проиндексировано'), findsOneWidget);
  });

  testWidgets('link intake validation error keeps inbox visible', (tester) async {
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(
            jsonEncode(inboxJson(
              recentSources: [
                {
                  'id': 'email-1',
                  'title': 'Stable inbox row',
                  'kind': 'email',
                  'provider': 'gmail',
                  'state': 'observed',
                  'status': null,
                  'primary_at': '2026-08-31T10:00:00Z',
                  'excerpt': 'body',
                },
              ],
            )),
            200,
          );
        }
        if (request.url.path == '/intake/link') {
          return http.Response(
            jsonEncode({'detail': 'unsupported link url'}),
            400,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
      find.byKey(const Key('inbox_link_input')),
      'https://evil.example/not-supported',
    );
    await tester.tap(find.byKey(const Key('inbox_link_add_button')));
    await tester.pumpAndSettle();

    expect(find.text('Stable inbox row'), findsOneWidget);
    expect(find.text('unsupported link url'), findsOneWidget);
    expect(find.text('Не удалось загрузить входящие'), findsNothing);
  });

  testWidgets('duplicate link submit blocked while pending', (tester) async {
    int intakeCalls = 0;
    final intakeCompleter = Completer<http.Response>();
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(jsonEncode(inboxJson()), 200);
        }
        if (request.url.path == '/intake/link') {
          intakeCalls++;
          return intakeCompleter.future;
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
      find.byKey(const Key('inbox_link_input')),
      'https://drive.google.com/file/d/abc/view',
    );
    await tester.tap(find.byKey(const Key('inbox_link_add_button')));
    await tester.pump();

    final addButton = tester.widget<FilledButton>(
      find.byKey(const Key('inbox_link_add_button')),
    );
    expect(addButton.onPressed, isNull);
    expect(intakeCalls, 1);

    intakeCompleter.complete(
      http.Response(
        jsonEncode(intakeLinkJson(objectId: 'drive-obj-1', status: 'created')),
        200,
      ),
    );
    await tester.pumpAndSettle();
  });

  testWidgets('file picker uses local intake client file endpoint', (tester) async {
    final tempDir = Directory.systemTemp.createTempSync('inbox-file-picker-');
    final file = File('${tempDir.path}/picked.txt');
    file.writeAsStringSync('hello');

    FilePicker.platform = _FakeFilePicker(
      pickFilesResult: FilePickerResult(
        [PlatformFile(path: file.path, name: 'picked.txt', size: 5)],
      ),
    );

    int clientIntakeCalls = 0;
    String? clientIntakeBody;
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(jsonEncode(inboxJson()), 200);
        }
        if (request.url.path == '/local/devices/register') {
          return http.Response(
            jsonEncode({
              'device_id': 'device-1',
              'device_key': 'device-key-1',
              'display_name': 'Test device',
              'created': true,
            }),
            201,
          );
        }
        if (request.url.path == '/local/files/client-intake') {
          clientIntakeCalls++;
          clientIntakeBody = request.body;
          return http.Response(
            jsonEncode({
              'object_id': 'local-file-1',
              'status': 'created',
              'jobs_enqueued': 0,
              'representations_created': 1,
              'metadata_only': false,
            }),
            201,
          );
        }
        if (request.url.path == '/objects/local-file-1') {
          return http.Response(
            jsonEncode({
              'id': 'local-file-1',
              'kind': 'file',
              'title': 'picked.txt',
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
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('inbox_add_file_button')));
    await tester.pumpAndSettle();

    expect(clientIntakeCalls, 1);
    final pickerDecoded = jsonDecode(clientIntakeBody!) as Map<String, dynamic>;
    expect(pickerDecoded['intake_mode'], 'explicit_local');
    tempDir.deleteSync(recursive: true);
  });

  testWidgets('folder picker uses explicit folder client intake', (tester) async {
    final tempDir = Directory.systemTemp.createTempSync('inbox-folder-picker-');
    final folder = Directory('${tempDir.path}/picked-folder');
    folder.createSync();

    FilePicker.platform = _FakeFilePicker(directoryPath: folder.path);

    int folderIntakeCalls = 0;
    int fileIntakeCalls = 0;
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(jsonEncode(inboxJson()), 200);
        }
        if (request.url.path == '/local/devices/register') {
          return http.Response(
            jsonEncode({
              'device_id': 'device-1',
              'device_key': 'device-key-1',
              'display_name': 'Test device',
              'created': true,
            }),
            201,
          );
        }
        if (request.url.path == '/local/folders/client-intake') {
          folderIntakeCalls++;
          return http.Response(
            jsonEncode({
              'object_id': 'folder-obj-1',
              'status': 'created',
            }),
            201,
          );
        }
        if (request.url.path == '/local/files/client-intake') {
          fileIntakeCalls++;
          return http.Response('{}', 201);
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('inbox_add_folder_button')));
    await tester.pumpAndSettle();

    expect(folderIntakeCalls, 1);
    expect(fileIntakeCalls, 0);
    tempDir.deleteSync(recursive: true);
  });

  testWidgets('dropped local file forwarded to client file intake', (tester) async {
    final inboxKey = GlobalKey<InboxScreenState>();
    final tempDir = Directory.systemTemp.createTempSync('inbox-drop-file-');
    final file = File('${tempDir.path}/dropped.txt');
    file.writeAsStringSync('drop-content');

    int clientIntakeCalls = 0;
    String? clientIntakeBody;
    await tester.pumpWidget(
      buildInbox(
        MockClient((request) async {
          if (request.url.path == '/inbox') {
            return http.Response(jsonEncode(inboxJson()), 200);
          }
          if (request.url.path == '/local/devices/register') {
            return http.Response(
              jsonEncode({
                'device_id': 'device-1',
                'device_key': 'device-key-1',
                'display_name': 'Test device',
                'created': true,
              }),
              201,
            );
          }
          if (request.url.path == '/local/files/client-intake') {
            clientIntakeCalls++;
            clientIntakeBody = request.body;
            return http.Response(
              jsonEncode({
                'object_id': 'local-file-2',
                'status': 'created',
                'jobs_enqueued': 0,
                'representations_created': 1,
                'metadata_only': false,
              }),
              201,
            );
          }
          if (request.url.path == '/objects/local-file-2') {
            return http.Response(
              jsonEncode({
                'id': 'local-file-2',
                'kind': 'file',
                'title': 'dropped.txt',
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
              }),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
        inboxKey: inboxKey,
      ),
    );
    await tester.pumpAndSettle();

    inboxKey.currentState!.handleDroppedPaths([file.path]);
    await tester.pumpAndSettle();

    expect(clientIntakeCalls, 1);
    final decoded = jsonDecode(clientIntakeBody!) as Map<String, dynamic>;
    expect(decoded['intake_mode'], 'explicit_local');
    tempDir.deleteSync(recursive: true);
  });

  testWidgets('failed local file intake does not refresh inbox', (tester) async {
    final inboxKey = GlobalKey<InboxScreenState>();
    final tempDir = Directory.systemTemp.createTempSync('inbox-fail-file-');
    final file = File('${tempDir.path}/failed.txt');
    file.writeAsStringSync('fail-content');

    int inboxCalls = 0;
    await tester.pumpWidget(
      buildInbox(
        MockClient((request) async {
          if (request.url.path == '/inbox') {
            inboxCalls++;
            return http.Response(jsonEncode(inboxJson()), 200);
          }
          if (request.url.path == '/local/devices/register') {
            return http.Response(
              jsonEncode({
                'device_id': 'device-1',
                'device_key': 'device-key-1',
                'display_name': 'Test device',
                'created': true,
              }),
              201,
            );
          }
          if (request.url.path == '/local/files/client-intake') {
            return http.Response(
              jsonEncode({'detail': 'intake failed'}),
              400,
            );
          }
          return http.Response('{}', 404);
        }),
        inboxKey: inboxKey,
      ),
    );
    await tester.pumpAndSettle();

    inboxKey.currentState!.handleDroppedPaths([file.path]);
    await tester.pumpAndSettle();

    expect(inboxCalls, 1);
    tempDir.deleteSync(recursive: true);
  });

  testWidgets('dropped local folder uses folder intake only', (tester) async {
    final inboxKey = GlobalKey<InboxScreenState>();
    final tempDir = Directory.systemTemp.createTempSync('inbox-drop-folder-');
    final folder = Directory('${tempDir.path}/dropped-folder');
    folder.createSync();
    File('${folder.path}/child.txt').writeAsStringSync('child');

    int folderIntakeCalls = 0;
    int fileIntakeCalls = 0;
    await tester.pumpWidget(
      buildInbox(
        MockClient((request) async {
          if (request.url.path == '/inbox') {
            return http.Response(jsonEncode(inboxJson()), 200);
          }
          if (request.url.path == '/local/devices/register') {
            return http.Response(
              jsonEncode({
                'device_id': 'device-1',
                'device_key': 'device-key-1',
                'display_name': 'Test device',
                'created': true,
              }),
              201,
            );
          }
          if (request.url.path == '/local/folders/client-intake') {
            folderIntakeCalls++;
            return http.Response(
              jsonEncode({
                'object_id': 'folder-obj-2',
                'status': 'created',
              }),
              201,
            );
          }
          if (request.url.path == '/local/files/client-intake') {
            fileIntakeCalls++;
            return http.Response('{}', 201);
          }
          return http.Response('{}', 404);
        }),
        inboxKey: inboxKey,
      ),
    );
    await tester.pumpAndSettle();

    inboxKey.currentState!.handleDroppedPaths([folder.path]);
    await tester.pumpAndSettle();

    expect(folderIntakeCalls, 1);
    expect(fileIntakeCalls, 0);
    tempDir.deleteSync(recursive: true);
  });

  testWidgets('local intake completion refreshes inbox', (tester) async {
    final inboxKey = GlobalKey<InboxScreenState>();
    final tempDir = Directory.systemTemp.createTempSync('inbox-refresh-');
    final file = File('${tempDir.path}/refresh.txt');
    file.writeAsStringSync('refresh');

    int inboxCalls = 0;
    await tester.pumpWidget(
      buildInbox(
        MockClient((request) async {
          if (request.url.path == '/inbox') {
            inboxCalls++;
            final sources = inboxCalls >= 2
                ? <Map<String, dynamic>>[
                    {
                      'id': 'local-file-3',
                      'title': 'refresh.txt',
                      'kind': 'file',
                      'provider': 'local_device',
                      'state': 'observed',
                      'status': null,
                      'primary_at': '2026-08-31T10:00:00Z',
                      'excerpt': 'body',
                    },
                  ]
                : <Map<String, dynamic>>[];
            return http.Response(jsonEncode(inboxJson(recentSources: sources)), 200);
          }
          if (request.url.path == '/local/devices/register') {
            return http.Response(
              jsonEncode({
                'device_id': 'device-1',
                'device_key': 'device-key-1',
                'display_name': 'Test device',
                'created': true,
              }),
              201,
            );
          }
          if (request.url.path == '/local/files/client-intake') {
            return http.Response(
              jsonEncode({
                'object_id': 'local-file-3',
                'status': 'created',
                'jobs_enqueued': 0,
                'representations_created': 1,
                'metadata_only': false,
              }),
              201,
            );
          }
          if (request.url.path == '/objects/local-file-3') {
            return http.Response(
              jsonEncode({
                'id': 'local-file-3',
                'kind': 'file',
                'title': 'refresh.txt',
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
              }),
              200,
            );
          }
          return http.Response('{}', 404);
        }),
        inboxKey: inboxKey,
      ),
    );
    await tester.pumpAndSettle();

    inboxKey.currentState!.handleDroppedPaths([file.path]);
    await tester.pumpAndSettle();

    expect(inboxCalls, greaterThanOrEqualTo(2));
    expect(find.text('refresh.txt'), findsOneWidget);
    tempDir.deleteSync(recursive: true);
  });

  testWidgets('explicit intake does not call sources sync', (tester) async {
    int syncCalls = 0;
    await tester.pumpWidget(
      buildInbox(MockClient((request) async {
        if (request.url.path == '/inbox') {
          return http.Response(jsonEncode(inboxJson()), 200);
        }
        if (request.url.path == '/sources/sync') {
          syncCalls++;
          return http.Response('{"triggered":[],"count":0}', 200);
        }
        if (request.url.path == '/intake/link') {
          return http.Response(
            jsonEncode(intakeLinkJson(objectId: 'drive-obj-1', status: 'created')),
            200,
          );
        }
        return http.Response('{}', 404);
      })),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
      find.byKey(const Key('inbox_link_input')),
      'https://drive.google.com/file/d/abc/view',
    );
    await tester.tap(find.byKey(const Key('inbox_link_add_button')));
    await tester.pumpAndSettle();

    expect(syncCalls, 0);
  });
}

class _FakeFilePicker extends FilePicker {
  _FakeFilePicker({
    this.pickFilesResult,
    this.directoryPath,
  });

  final FilePickerResult? pickFilesResult;
  final String? directoryPath;

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
    return directoryPath;
  }
}
