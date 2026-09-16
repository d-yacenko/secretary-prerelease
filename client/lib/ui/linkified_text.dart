import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

final _urlPattern = RegExp(
  r'https?://[^\s<>\[\](){}]+',
  caseSensitive: false,
);

String trimTrailingUrlPunctuation(String value) {
  return value.replaceFirst(RegExp(r'[.,;:!?)]+$'), '');
}

Uri? safeHttpUri(String raw) {
  final trimmed = trimTrailingUrlPunctuation(raw.trim());
  final uri = Uri.tryParse(trimmed);
  if (uri == null || !uri.hasScheme || uri.host.isEmpty) {
    return null;
  }
  if (uri.scheme != 'http' && uri.scheme != 'https') {
    return null;
  }
  return uri;
}

List<InlineSpan> linkifyTextSpans(
  String text, {
  required TextStyle? style,
  required Color linkColor,
  required void Function(Uri uri) onOpen,
}) {
  if (text.isEmpty) {
    return [TextSpan(text: text, style: style)];
  }
  final spans = <InlineSpan>[];
  var start = 0;
  for (final match in _urlPattern.allMatches(text)) {
    if (match.start > start) {
      spans.add(TextSpan(text: text.substring(start, match.start), style: style));
    }
    final raw = match.group(0)!;
    final uri = safeHttpUri(raw);
    if (uri == null) {
      spans.add(TextSpan(text: raw, style: style));
    } else {
      final linkText = trimTrailingUrlPunctuation(raw);
      final suffix = raw.substring(linkText.length);
      spans.add(
        TextSpan(
          text: linkText,
          style: style?.copyWith(
            color: linkColor,
            decoration: TextDecoration.underline,
          ),
          recognizer: TapGestureRecognizer()..onTap = () => onOpen(uri),
        ),
      );
      if (suffix.isNotEmpty) {
        spans.add(TextSpan(text: suffix, style: style));
      }
    }
    start = match.end;
  }
  if (start < text.length) {
    spans.add(TextSpan(text: text.substring(start), style: style));
  }
  return spans;
}

class LinkifiedText extends StatelessWidget {
  const LinkifiedText({
    super.key,
    required this.text,
    this.style,
  });

  final String text;
  final TextStyle? style;

  Future<void> _open(Uri uri) async {
    await launchUrl(uri, mode: LaunchMode.externalApplication);
  }

  @override
  Widget build(BuildContext context) {
    final textStyle = style ?? Theme.of(context).textTheme.bodyMedium;
    return SelectableText.rich(
      TextSpan(
        children: linkifyTextSpans(
          text,
          style: textStyle,
          linkColor: Theme.of(context).colorScheme.primary,
          onOpen: _open,
        ),
      ),
    );
  }
}
