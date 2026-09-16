import 'package:flutter/foundation.dart' show kIsWeb;

import '../api/api_models.dart';
import '../local/client_device_store.dart';
import 'platform_capabilities.dart';

class SourceActionPresentation {
  const SourceActionPresentation({
    required this.canOpen,
    this.openLabel,
    this.canShowInFolder = false,
    this.showInFolderLabel = 'Показать в папке',
    this.disabledReason,
    this.localPath,
  });

  final bool canOpen;
  final String? openLabel;
  final bool canShowInFolder;
  final String showInFolderLabel;
  final String? disabledReason;
  final String? localPath;

  bool get isDisabled => !canOpen && disabledReason != null;
}

class SourceNavigationPresenter {
  SourceNavigationPresenter({
    ClientDeviceStore? deviceStore,
    PlatformCapabilities? platform,
  })  : _deviceStore = deviceStore ?? ClientDeviceStore(),
        _platform = platform ?? DefaultPlatformCapabilities();

  final ClientDeviceStore _deviceStore;
  final PlatformCapabilities _platform;

  Future<SourceActionPresentation> present(OpenTarget target) async {
    if (!target.available) {
      return SourceActionPresentation(
        canOpen: false,
        disabledReason: _unavailableReason(target),
      );
    }

    if (target.action == 'web_url') {
      return SourceActionPresentation(
        canOpen: true,
        openLabel: target.label,
      );
    }

    if (target.action == 'local_file' || target.action == 'local_folder') {
      if (kIsWeb || !_platform.canOpenLocalSourcePaths) {
        return SourceActionPresentation(
          canOpen: false,
          disabledReason: 'Исходный файл сейчас недоступен на этом устройстве',
        );
      }
      final device = await _deviceStore.loadOrCreate();
      if (target.deviceKey != device.deviceKey) {
        return SourceActionPresentation(
          canOpen: false,
          disabledReason: 'Файл находится на другом устройстве',
        );
      }
      final localPath = target.localPath;
      if (localPath == null || localPath.isEmpty) {
        return SourceActionPresentation(
          canOpen: false,
          disabledReason: 'Исходный файл сейчас недоступен на этом устройстве',
        );
      }
      return SourceActionPresentation(
        canOpen: true,
        openLabel: target.label,
        canShowInFolder: target.action == 'local_file',
        localPath: localPath,
      );
    }

    return SourceActionPresentation(
      canOpen: false,
      disabledReason: 'Не удалось открыть источник',
    );
  }

  String? _unavailableReason(OpenTarget target) {
    if (target.reason == 'client_source_path_missing') {
      return 'Исходный файл сейчас недоступен на этом устройстве';
    }
    if (target.reason == 'yandex_exact_message_link_unavailable') {
      return null;
    }
    return 'Не удалось открыть источник';
  }
}
