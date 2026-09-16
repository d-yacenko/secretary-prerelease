import 'dart:io';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:url_launcher/url_launcher.dart' as url_launcher;

import '../api/api_models.dart';
import '../api/secretary_api_client.dart';
import '../local/client_device_store.dart';
import 'external_launcher.dart';

class SourceNavigationService {
  SourceNavigationService({
    required SecretaryApiClient apiClient,
    ClientDeviceStore? deviceStore,
    ExternalLauncher? launcher,
  })  : _apiClient = apiClient,
        _deviceStore = deviceStore ?? ClientDeviceStore(),
        _launcher = launcher ?? ProductionExternalLauncher();

  final SecretaryApiClient _apiClient;
  final ClientDeviceStore _deviceStore;
  final ExternalLauncher _launcher;

  Future<OpenTarget> resolve(String objectId) {
    return _apiClient.getOpenTarget(objectId);
  }

  Future<String?> launchForObject(String objectId) async {
    final target = await resolve(objectId);
    if (!target.available) {
      if (target.reason == 'yandex_exact_message_link_unavailable') {
        return null;
      }
      throw SourceLaunchException('Не удалось открыть источник');
    }

    switch (target.action) {
      case 'web_url':
        final url = target.url;
        if (url == null || !_isSafeWebUrl(url)) {
          throw SourceLaunchException('Не удалось открыть источник');
        }
        final uri = Uri.parse(url);
        if (!await _launcher.launchUrl(uri, mode: url_launcher.LaunchMode.externalApplication)) {
          throw SourceLaunchException('Не удалось открыть источник');
        }
        return null;
      case 'local_file':
      case 'local_folder':
        return await _launchLocal(target);
      default:
        throw SourceLaunchException('Не удалось открыть источник');
    }
  }

  Future<String?> _launchLocal(OpenTarget target) async {
    if (kIsWeb) {
      throw SourceLaunchException('Исходный файл сейчас недоступен на этом устройстве');
    }
    final device = await _deviceStore.loadOrCreate();
    if (target.deviceKey != device.deviceKey) {
      throw SourceLaunchException('Файл находится на другом устройстве');
    }
    final localPath = target.localPath;
    if (localPath == null || localPath.isEmpty) {
      throw SourceLaunchException('Исходный файл сейчас недоступен на этом устройстве');
    }
    if (target.action == 'local_folder') {
      await _openPath(localPath, folder: true);
      return null;
    }
    await _openPath(localPath, folder: false);
    return null;
  }

  Future<void> showInFolder(String filePath) async {
    if (kIsWeb) {
      throw SourceLaunchException('Исходный файл сейчас недоступен на этом устройстве');
    }
    final directory = File(filePath).parent.path;
    await _openPath(directory, folder: true);
  }

  Future<void> _openPath(String path, {required bool folder}) async {
    if (Platform.isLinux) {
      final result = await _launcher.runExecutable('xdg-open', [path], runInShell: false);
      if (result.exitCode != 0) {
        throw SourceLaunchException('Не удалось открыть источник');
      }
      return;
    }
    if (Platform.isAndroid) {
      throw SourceLaunchException('Исходный файл сейчас недоступен на этом устройстве');
    }
    final file = File(path);
    if (!file.existsSync()) {
      throw SourceLaunchException('Исходный файл сейчас недоступен на этом устройстве');
    }
    final result = await _launcher.runExecutable('xdg-open', [path], runInShell: false);
    if (result.exitCode != 0) {
      throw SourceLaunchException('Не удалось открыть источник');
    }
  }

  bool _isSafeWebUrl(String url) {
    final uri = Uri.tryParse(url.trim());
    if (uri == null) {
      return false;
    }
    if (uri.scheme != 'http' && uri.scheme != 'https') {
      return false;
    }
    if (uri.userInfo.isNotEmpty) {
      return false;
    }
    return uri.host.isNotEmpty;
  }
}

class SourceLaunchException implements Exception {
  SourceLaunchException(this.message);
  final String message;
}
