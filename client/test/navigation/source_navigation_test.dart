import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/local/client_device_store.dart';
import 'package:personal_secretary/navigation/external_launcher.dart';
import 'package:personal_secretary/navigation/platform_capabilities.dart';
import 'package:personal_secretary/navigation/source_navigation_presenter.dart';
import 'package:personal_secretary/navigation/source_navigation_service.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _FakeApiClient extends SecretaryApiClient {
  _FakeApiClient(this.target) : super();

  final OpenTarget target;

  @override
  Future<OpenTarget> getOpenTarget(String objectId) async => target;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  test('presenter marks other device as disabled', () async {
    final target = OpenTarget(
      available: true,
      action: 'local_file',
      label: 'Открыть файл',
      deviceKey: 'other-device',
      localPath: '/home/user/file.txt',
    );
    final presenter = SourceNavigationPresenter();
    final presentation = await presenter.present(target);
    expect(presentation.canOpen, isFalse);
    expect(presentation.disabledReason, 'Файл находится на другом устройстве');
  });

  test('android local target disabled in presenter', () async {
    SharedPreferences.setMockInitialValues({
      'secretary_device_key': 'desk-test',
      'secretary_device_display_name': 'Test',
    });
    final presenter = SourceNavigationPresenter(
      deviceStore: ClientDeviceStore(preferences: await SharedPreferences.getInstance()),
      platform: StubPlatformCapabilities(
        canOpenLocalSourcePaths: false,
        isAndroid: true,
      ),
    );
    final presentation = await presenter.present(
      OpenTarget(
        available: true,
        action: 'local_file',
        label: 'Открыть файл',
        deviceKey: 'desk-test',
        localPath: '/home/user/file.txt',
      ),
    );
    expect(presentation.canOpen, isFalse);
    expect(presentation.canShowInFolder, isFalse);
    expect(
      presentation.disabledReason,
      'Исходный файл сейчас недоступен на этом устройстве',
    );
  });

  test('recording launcher launches safe https url', () async {
    final launcher = RecordingExternalLauncher();
    final service = SourceNavigationService(
      apiClient: _FakeApiClient(
        OpenTarget(
          available: true,
          action: 'web_url',
          label: 'Открыть в Gmail',
          url: 'https://mail.google.com/mail/',
        ),
      ),
      launcher: launcher,
    );
    await service.launchForObject('obj-1');
    expect(launcher.launches.single.action, 'launchUrl');
    expect(launcher.launches.single.target, 'https://mail.google.com/mail/');
  });

  test('javascript url is not launched', () async {
    final launcher = RecordingExternalLauncher();
    final service = SourceNavigationService(
      apiClient: _FakeApiClient(
        OpenTarget(
          available: true,
          action: 'web_url',
          label: 'Bad',
          url: 'javascript:alert(1)',
        ),
      ),
      launcher: launcher,
    );
    await expectLater(
      service.launchForObject('obj-1'),
      throwsA(isA<SourceLaunchException>()),
    );
    expect(launcher.launches, isEmpty);
  });
}
