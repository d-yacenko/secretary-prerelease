import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:path/path.dart' as p;

import '../api/api_error.dart';
import '../api/api_models.dart';
import '../api/secretary_api_client.dart';
import '../auth/auth_controller.dart';
import '../capture/capture_controller.dart';
import '../assistant/assistant_controller.dart';
import 'local_file_intake_service.dart';

typedef IntakeObjectHandler = void Function(SecretaryObject object);
typedef ActiveContextChooser = Future<SecretaryObject?> Function(
  BuildContext context,
  List<SecretaryObject> objects,
);

class LocalIntakeActions {
  LocalIntakeActions({
    required this.apiClient,
    required this.authController,
    this.captureController,
    this.assistantController,
    this.onIntakeObject,
    this.onIntakeSuccess,
    this.attachToCapture = false,
    this.forInbox = false,
    this.chooseActiveContext,
    LocalFileIntakeService? intakeService,
  })  : _intakeService = intakeService ?? LocalFileIntakeService(apiClient: apiClient);

  final SecretaryApiClient apiClient;
  final AuthController authController;
  final CaptureController? captureController;
  final AssistantController? assistantController;
  final IntakeObjectHandler? onIntakeObject;
  final VoidCallback? onIntakeSuccess;
  final bool attachToCapture;
  final bool forInbox;
  final ActiveContextChooser? chooseActiveContext;

  final LocalFileIntakeService _intakeService;
  bool _busy = false;

  static const _explicitLocalIntakeMode = 'explicit_local';

  Future<void> pickAndRegisterFile(BuildContext context) async {
    if (_busy) {
      return;
    }
    if (kIsWeb) {
      _showMessage(context, 'Выбор файла недоступен в этой среде');
      return;
    }
    final result = await FilePicker.platform.pickFiles();
    if (result == null || result.files.isEmpty) {
      return;
    }
    final path = result.files.single.path;
    if (path == null) {
      _showMessage(context, 'Не удалось прочитать файл');
      return;
    }
    _busy = true;
    try {
      await _registerPaths(context, [path]);
    } finally {
      _busy = false;
    }
  }

  Future<void> pickAndRegisterFolder(BuildContext context) async {
    if (_busy) {
      return;
    }
    if (kIsWeb) {
      return;
    }
    final path = await FilePicker.platform.getDirectoryPath();
    if (path == null) {
      return;
    }
    _busy = true;
    try {
      await _registerFolder(context, Directory(path));
    } finally {
      _busy = false;
    }
  }

  Future<void> registerDroppedFiles(
    BuildContext context,
    List<String> paths,
  ) async {
    if (paths.isEmpty || _busy) {
      return;
    }
    _busy = true;
    try {
      await _registerPaths(context, paths.take(10).toList());
    } finally {
      _busy = false;
    }
  }

  Future<void> _registerPaths(BuildContext context, List<String> paths) async {
    final files = <File>[];
    final directories = <Directory>[];
    final errors = <String>[];

    for (final path in paths) {
      final type = FileSystemEntity.typeSync(path);
      if (type == FileSystemEntityType.directory) {
        directories.add(Directory(path));
      } else if (type == FileSystemEntityType.file) {
        files.add(File(path));
      } else {
        errors.add('Не удалось прочитать: $path');
      }
    }

    var intakeSucceeded = false;

    for (final directory in directories) {
      try {
        final ok = await _registerFolder(context, directory, notifySuccess: false);
        if (ok) {
          intakeSucceeded = true;
        }
      } on AuthenticationException {
        authController.handleAuthenticationFailure();
        return;
      } on ApiException catch (e) {
        errors.add(e.message);
      } catch (_) {
        errors.add('Не удалось зарегистрировать папку: ${directory.path}');
      }
    }

    if (files.isEmpty) {
      if (errors.isNotEmpty) {
        _showMessage(context, errors.join('\n'));
      }
      if (intakeSucceeded) {
        _notifyIntakeSuccess();
      }
      return;
    }

    if (files.length == 1) {
      final succeeded = await _registerSingleFile(
        context,
        files.first,
        notifySuccess: false,
      );
      if (succeeded) {
        intakeSucceeded = true;
      }
      if (errors.isNotEmpty) {
        _showMessage(context, errors.join('\n'));
      }
      if (intakeSucceeded) {
        _notifyIntakeSuccess();
      }
      return;
    }

    final objects = <SecretaryObject>[];
    for (final file in files) {
      try {
        objects.add(
          await _intakeService.registerFileAndFetch(
            file,
            intakeMode: _explicitLocalIntakeMode,
          ),
        );
      } on AuthenticationException {
        authController.handleAuthenticationFailure();
        return;
      } on ApiException catch (e) {
        errors.add('${file.path}: ${e.message}');
      } catch (_) {
        errors.add('Не удалось зарегистрировать: ${file.path}');
      }
    }

    if (objects.isEmpty) {
      if (errors.isNotEmpty) {
        _showMessage(context, errors.join('\n'));
      }
      return;
    }

    if (forInbox) {
      _showMessage(context, 'Добавлено файлов: ${objects.length}');
      _notifyIntakeSuccess();
      if (errors.isNotEmpty) {
        _showMessage(context, errors.join('\n'));
      }
      return;
    }

    final chosen = await _askActiveContext(context, objects);
    if (chosen != null) {
      _attachObject(chosen);
    }
    _showMessage(
      context,
      'Добавлено файлов: ${objects.length}. Активный контекст: ${chosen?.title ?? "не выбран"}',
    );
    if (errors.isNotEmpty) {
      _showMessage(context, errors.join('\n'));
    }
  }

  Future<bool> _registerSingleFile(
    BuildContext context,
    File file, {
    bool notifySuccess = true,
  }) async {
    try {
      final object = await _intakeService.registerFileAndFetch(
        file,
        intakeMode: _explicitLocalIntakeMode,
      );
      if (!forInbox) {
        onIntakeObject?.call(object);
        _attachObject(object);
      }
      _showMessage(
        context,
        forInbox
            ? 'Файл добавлен: ${object.title}'
            : object.metadata['indexing_policy'] == 'metadata_only'
                ? 'Формат пока индексируется только по метаданным: ${object.title}'
                : 'Файл добавлен: ${object.title}',
      );
      if (notifySuccess) {
        _notifyIntakeSuccess();
      }
      return true;
    } on AuthenticationException {
      authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      _showMessage(context, e.message);
    } catch (_) {
      _showMessage(context, 'Не удалось зарегистрировать источник');
    }
    return false;
  }

  void _attachObject(SecretaryObject object) {
    if (forInbox) {
      return;
    }
    if (attachToCapture && captureController != null) {
      captureController!.attachObjectContext(object);
      return;
    }
    if (assistantController != null) {
      assistantController!.setObjectContext(object);
    }
  }

  Future<SecretaryObject?> _askActiveContext(
    BuildContext context,
    List<SecretaryObject> objects,
  ) async {
    if (chooseActiveContext != null) {
      return chooseActiveContext!(context, objects);
    }
    return showDialog<SecretaryObject>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Выберите активный контекст'),
        content: SizedBox(
          width: double.maxFinite,
          child: ListView.builder(
            shrinkWrap: true,
            itemCount: objects.length,
            itemBuilder: (context, index) {
              final object = objects[index];
              return ListTile(
                title: Text(object.title),
                onTap: () => Navigator.pop(context, object),
              );
            },
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Отмена'),
          ),
        ],
      ),
    );
  }

  Future<bool> _registerFolder(
    BuildContext context,
    Directory root, {
    bool notifySuccess = true,
  }) async {
    try {
      await _intakeService.registerFolder(root);
      _showMessage(context, 'Папка добавлена: ${p.basename(root.path)}');
      if (notifySuccess) {
        _notifyIntakeSuccess();
      }
      return true;
    } on AuthenticationException {
      authController.handleAuthenticationFailure();
    } on ApiException catch (e) {
      _showMessage(context, e.message);
    } catch (_) {
      _showMessage(context, 'Не удалось зарегистрировать источник');
    }
    return false;
  }

  void _notifyIntakeSuccess() {
    onIntakeSuccess?.call();
  }

  void _showMessage(BuildContext context, String message) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }
}

Widget buildAddFileButton({
  required LocalIntakeActions actions,
  required BuildContext context,
}) {
  return TextButton(
    key: const Key('add_local_file_button'),
    onPressed: () => actions.pickAndRegisterFile(context),
    child: const Text('Добавить файл'),
  );
}

Widget buildAddFolderButton({
  required LocalIntakeActions actions,
  required BuildContext context,
}) {
  return TextButton(
    key: const Key('add_local_folder_button'),
    onPressed: () => actions.pickAndRegisterFolder(context),
    child: const Text('Добавить папку'),
  );
}
