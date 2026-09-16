import 'dart:io';

import 'package:path_provider/path_provider.dart';

/// Creates and removes ephemeral voice recording files in app temp storage.
class VoiceTempFiles {
  VoiceTempFiles({Directory? directory}) : _directory = directory;

  final Directory? _directory;

  Future<String> createTempAudioPath(String extension) async {
    final directory = _directory ?? await getTemporaryDirectory();
    final unique = DateTime.now().microsecondsSinceEpoch;
    final safeExtension = extension.replaceAll('.', '');
    return '${directory.path}/secretary_voice_$unique.$safeExtension';
  }

  Future<String> createTempWavPath() async {
    return createTempAudioPath('wav');
  }

  Future<void> deleteIfExists(String? path) async {
    if (path == null || path.isEmpty) {
      return;
    }
    try {
      final file = File(path);
      if (await file.exists()) {
        await file.delete();
      }
    } on FileSystemException {
      // Ephemeral recordings may already be gone after stop/reset/dispose.
    }
  }
}
