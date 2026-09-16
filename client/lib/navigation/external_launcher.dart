import 'dart:io';

import 'package:url_launcher/url_launcher.dart' as url_launcher;

abstract class ExternalLauncher {
  Future<bool> launchUrl(
    Uri uri, {
    url_launcher.LaunchMode mode = url_launcher.LaunchMode.externalApplication,
  });

  Future<ProcessResult> runExecutable(
    String executable,
    List<String> arguments, {
    bool runInShell = false,
  });
}

class ProductionExternalLauncher implements ExternalLauncher {
  @override
  Future<bool> launchUrl(
    Uri uri, {
    url_launcher.LaunchMode mode = url_launcher.LaunchMode.externalApplication,
  }) {
    return url_launcher.launchUrl(uri, mode: mode);
  }

  @override
  Future<ProcessResult> runExecutable(
    String executable,
    List<String> arguments, {
    bool runInShell = false,
  }) {
    return Process.run(executable, arguments, runInShell: runInShell);
  }
}

class RecordingExternalLauncher implements ExternalLauncher {
  final List<RecordedLaunch> launches = [];

  @override
  Future<bool> launchUrl(
    Uri uri, {
    url_launcher.LaunchMode mode = url_launcher.LaunchMode.externalApplication,
  }) async {
    launches.add(RecordedLaunch(action: 'launchUrl', target: uri.toString()));
    return true;
  }

  @override
  Future<ProcessResult> runExecutable(
    String executable,
    List<String> arguments, {
    bool runInShell = false,
  }) async {
    launches.add(
      RecordedLaunch(
        action: 'runExecutable',
        target: executable,
        arguments: List<String>.from(arguments),
      ),
    );
    return ProcessResult(0, 0, '', '');
  }
}

class RecordedLaunch {
  RecordedLaunch({
    required this.action,
    required this.target,
    this.arguments = const [],
  });

  final String action;
  final String target;
  final List<String> arguments;
}
