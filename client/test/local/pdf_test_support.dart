import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider_platform_interface/path_provider_platform_interface.dart';
import 'package:pdfrx/pdfrx.dart';
import 'package:plugin_platform_interface/plugin_platform_interface.dart';

class _FakePathProvider extends Fake
    with MockPlatformInterfaceMixin
    implements PathProviderPlatform {
  @override
  Future<String?> getTemporaryPath() async => Directory.systemTemp.path;

  @override
  Future<String?> getApplicationSupportPath() async => Directory.systemTemp.path;

  @override
  Future<String?> getLibraryPath() async => Directory.systemTemp.path;

  @override
  Future<String?> getApplicationDocumentsPath() async => Directory.systemTemp.path;

  @override
  Future<String?> getExternalStoragePath() async => Directory.systemTemp.path;

  @override
  Future<List<String>?> getExternalCachePaths() async => [Directory.systemTemp.path];

  @override
  Future<List<String>?> getExternalStoragePaths({
    StorageDirectory? type,
  }) async =>
      [Directory.systemTemp.path];

  @override
  Future<String?> getDownloadsPath() async => Directory.systemTemp.path;

  @override
  Future<String?> getApplicationCachePath() async => Directory.systemTemp.path;
}

bool _pdfInitialized = false;
bool? _pdfAvailable;

Future<bool> isPdfAvailableForTests() async {
  if (_pdfAvailable != null) {
    return _pdfAvailable!;
  }
  try {
    await configurePdfForTests();
    _pdfAvailable = true;
  } catch (error) {
    _pdfAvailable = false;
    // ignore: avoid_print
    print('PDFium unavailable for tests: $error');
  }
  return _pdfAvailable!;
}

Future<void> configurePdfForTests() async {
  if (_pdfInitialized) {
    return;
  }
  TestWidgetsFlutterBinding.ensureInitialized();
  PathProviderPlatform.instance = _FakePathProvider();
  final bundled = _resolveBundledPdfiumPath();
  if (bundled != null) {
    Pdfrx.pdfiumModulePath = bundled;
    await _installPdfiumBesideFlutterTester(bundled);
  }
  await pdfrxFlutterInitialize(dismissPdfiumWasmWarnings: true)
      .timeout(const Duration(seconds: 30));
  _pdfInitialized = true;
}

String? _resolveBundledPdfiumPath() {
  final roots = <String>{
    Directory.current.path,
    _findPackageRoot(Directory.current.path),
  };
  for (final root in roots) {
    for (final suffix in const [
      'build/linux/x64/debug/bundle/lib/libpdfium.so',
      'build/linux/x64/release/bundle/lib/libpdfium.so',
    ]) {
      final path = p.normalize(p.join(root, suffix));
      if (File(path).existsSync()) {
        return path;
      }
    }
  }
  return null;
}

String _findPackageRoot(String start) {
  var dir = Directory(start);
  while (true) {
    if (File(p.join(dir.path, 'pubspec.yaml')).existsSync()) {
      return dir.path;
    }
    final parent = dir.parent;
    if (parent.path == dir.path) {
      return start;
    }
    dir = parent;
  }
}

Future<void> _installPdfiumBesideFlutterTester(String bundledPath) async {
  final testerLib = p.join(
    File(Platform.resolvedExecutable).parent.path,
    'lib',
    'libpdfium.so',
  );
  if (File(testerLib).existsSync()) {
    return;
  }
  await Directory(p.dirname(testerLib)).create(recursive: true);
  await File(bundledPath).copy(testerLib);
}

void requirePdfForTests() {
  if (_pdfAvailable != true) {
    fail('BLOCKED: PDFium is required but unavailable on this host');
  }
}
