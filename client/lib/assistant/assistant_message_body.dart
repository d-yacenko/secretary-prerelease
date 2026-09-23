import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:url_launcher/url_launcher.dart';

enum AssistantLinkKind { external, objectDetail, ignore }

class AssistantLinkTarget {
  const AssistantLinkTarget(this.kind, {this.uri, this.objectId});

  final AssistantLinkKind kind;
  final Uri? uri;
  final String? objectId;
}

/// Internal object links open only when the server validated that exact id.
AssistantLinkTarget classifyAssistantLink(
  String? href,
  Set<String> openableObjectIds,
) {
  if (href == null || href.isEmpty) {
    return const AssistantLinkTarget(AssistantLinkKind.ignore);
  }
  final uri = Uri.tryParse(href);
  if (uri == null || !uri.hasScheme) {
    return const AssistantLinkTarget(AssistantLinkKind.ignore);
  }
  if (uri.scheme == 'http' || uri.scheme == 'https') {
    return AssistantLinkTarget(AssistantLinkKind.external, uri: uri);
  }
  if (uri.scheme == 'secretary' && uri.host == 'object') {
    if (uri.pathSegments.length != 1) {
      return const AssistantLinkTarget(AssistantLinkKind.ignore);
    }
    final objectId = uri.pathSegments.single;
    if (!openableObjectIds.contains(objectId)) {
      return const AssistantLinkTarget(AssistantLinkKind.ignore);
    }
    return AssistantLinkTarget(
      AssistantLinkKind.objectDetail,
      objectId: objectId,
    );
  }
  return const AssistantLinkTarget(AssistantLinkKind.ignore);
}

/// Renders Assistant Markdown safely (no HTML/WebView).
class AssistantMessageBody extends StatelessWidget {
  const AssistantMessageBody({
    super.key,
    required this.content,
    this.openableObjectIds = const {},
    this.onOpenObject,
    this.onOpenExternal,
  });

  final String content;
  final Set<String> openableObjectIds;
  final void Function(String objectId)? onOpenObject;
  final void Function(Uri uri)? onOpenExternal;

  @override
  Widget build(BuildContext context) {
    return MarkdownBody(
      data: content,
      selectable: true,
      onTapLink: (text, href, title) {
        final target = classifyAssistantLink(href, openableObjectIds);
        switch (target.kind) {
          case AssistantLinkKind.external:
            final uri = target.uri;
            if (uri == null) {
              return;
            }
            if (onOpenExternal != null) {
              onOpenExternal!(uri);
            } else {
              launchUrl(uri, mode: LaunchMode.externalApplication);
            }
          case AssistantLinkKind.objectDetail:
            final objectId = target.objectId;
            if (objectId != null) {
              onOpenObject?.call(objectId);
            }
          case AssistantLinkKind.ignore:
            return;
        }
      },
      styleSheet: MarkdownStyleSheet.fromTheme(Theme.of(context)),
    );
  }
}
