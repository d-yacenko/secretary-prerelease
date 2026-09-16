import 'dart:io' show Platform;

import 'package:flutter/foundation.dart' show kIsWeb;

/// Injectable platform facts for source navigation presentation.
abstract class PlatformCapabilities {
  bool get canOpenLocalSourcePaths;
  bool get isAndroid;
}

class DefaultPlatformCapabilities implements PlatformCapabilities {
  @override
  bool get isAndroid => !kIsWeb && Platform.isAndroid;

  @override
  bool get canOpenLocalSourcePaths => !kIsWeb && !isAndroid;
}

class StubPlatformCapabilities implements PlatformCapabilities {
  StubPlatformCapabilities({
    this.canOpenLocalSourcePaths = true,
    this.isAndroid = false,
  });

  @override
  final bool canOpenLocalSourcePaths;

  @override
  final bool isAndroid;
}
