import 'dart:io';

import '../api/api_models.dart';
import '../api/secretary_api_client.dart';
import 'client_device_store.dart';
import 'client_wire_metadata.dart';
import 'local_resource_extractor.dart';

class LocalFileIntakeService {
  LocalFileIntakeService({
    required SecretaryApiClient apiClient,
    ClientDeviceStore? deviceStore,
    LocalResourceExtractor? extractor,
  })  : _apiClient = apiClient,
        _deviceStore = deviceStore ?? ClientDeviceStore(),
        _extractor = extractor ?? LocalResourceExtractor();

  final SecretaryApiClient _apiClient;
  final ClientDeviceStore _deviceStore;
  final LocalResourceExtractor _extractor;

  Future<ClientFileIntakeResult> registerFile(
    File file, {
    String? intakeMode,
  }) async {
    final device = await _deviceStore.loadOrCreate();
    await _apiClient.registerLocalDevice(
      deviceKey: device.deviceKey,
      displayName: device.displayName,
    );
    final extraction = await _extractor.extractFile(file);
    return _apiClient.clientFileIntake(
      deviceKey: device.deviceKey,
      sourcePath: extraction.sourcePath,
      filename: extraction.filename,
      size: extraction.size,
      modifiedAt: extraction.modifiedAt,
      contentRevision: extraction.contentRevision,
      representations: sanitizeClientRepresentations(extraction.representations),
      contentHash: extraction.contentHash,
      metadataOnly: extraction.metadataOnly,
      intakeMode: intakeMode,
    );
  }

  Future<SecretaryObject> registerFileAndFetch(
    File file, {
    String? intakeMode,
  }) async {
    final result = await registerFile(file, intakeMode: intakeMode);
    return _apiClient.getObject(result.objectId);
  }

  Future<ClientFolderIntakeResult> registerFolder(Directory root) async {
    final device = await _deviceStore.loadOrCreate();
    await _apiClient.registerLocalDevice(
      deviceKey: device.deviceKey,
      displayName: device.displayName,
    );
    final rootPath = _normalizeRootPath(root.path);
    return _apiClient.clientFolderIntake(
      deviceKey: device.deviceKey,
      rootPath: rootPath,
      clientSourcePath: root.path,
      displayName: device.displayName,
    );
  }

  String _normalizeRootPath(String absolutePath) {
    return absolutePath.replaceAll('\\', '/').replaceFirst(RegExp('^/+'), '');
  }
}
