const int maxSpeechInputChars = 3000;

final _fence = RegExp(r'```(?:[\w.+-]+)?\n?(.*?)```', dotAll: true);
final _inlineCode = RegExp(r'`([^`]+)`');
final _link = RegExp(r'\[([^\]]+)\]\([^)]+\)');
final _image = RegExp(r'!\[([^\]]*)\]\([^)]+\)');
final _bold = RegExp(r'(\*\*|__)(.*?)\1');
final _italic = RegExp(
  r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)',
);
final _heading = RegExp(r'^#{1,6}\s+', multiLine: true);
final _blockquote = RegExp(r'^>\s?', multiLine: true);
final _list = RegExp(r'^(\s*)(?:[-*+]|\d+\.)\s+', multiLine: true);
final _hr = RegExp(r'^\s*([-*_]\s*){3,}\s*$', multiLine: true);
final _markup = RegExp(r'[*_`#]+');
final _spaces = RegExp(r'[ \t]{2,}');
final _newlines = RegExp(r'\n{3,}');
final _sentences = RegExp(r'(?<=[.!?…])\s+');

/// Strip presentation-only Markdown. Do not summarize or rewrite.
String prepareSpeechText(String text) {
  var prepared = text.replaceAll('\r\n', '\n').replaceAll('\r', '\n');
  prepared = prepared.replaceAllMapped(
    _fence,
    (match) => match.group(1)?.trim() ?? '',
  );
  prepared = prepared.replaceAllMapped(
    _image,
    (match) => match.group(1)?.trim() ?? '',
  );
  prepared = prepared.replaceAllMapped(
    _link,
    (match) => match.group(1)?.trim() ?? '',
  );
  prepared = prepared.replaceAllMapped(
    _inlineCode,
    (match) => match.group(1) ?? '',
  );
  prepared = prepared.replaceAllMapped(_bold, (match) => match.group(2) ?? '');
  prepared = prepared.replaceAllMapped(
    _italic,
    (match) => match.group(1) ?? match.group(2) ?? '',
  );
  prepared = prepared.replaceAll(_heading, '');
  prepared = prepared.replaceAll(_blockquote, '');
  prepared = prepared.replaceAllMapped(_list, (match) => match.group(1) ?? '');
  prepared = prepared.replaceAll(_hr, '');
  prepared = prepared.replaceAll(_markup, '');
  prepared = prepared.replaceAll(_spaces, ' ');
  prepared = prepared.replaceAll(_newlines, '\n\n');
  return prepared.trim();
}

/// Pack prepared speech text into <= 3000-character chunks at paragraph/sentence bounds.
List<String> chunkSpeechText(String text) {
  final prepared = prepareSpeechText(text);
  if (prepared.isEmpty) {
    return const [];
  }
  return _pack(prepared, maxSpeechInputChars);
}

List<String> _pack(String text, int limit) {
  if (text.length <= limit) {
    return [text];
  }
  final chunks = <String>[];
  final current = StringBuffer();

  void flush() {
    final value = current.toString().trim();
    if (value.isNotEmpty) {
      chunks.add(value);
    }
    current.clear();
  }

  void appendPiece(String piece) {
    final trimmed = piece.trim();
    if (trimmed.isEmpty) {
      return;
    }
    if (trimmed.length > limit) {
      for (final part in _splitHard(trimmed, limit)) {
        appendPiece(part);
      }
      return;
    }
    if (current.isEmpty) {
      current.write(trimmed);
      return;
    }
    if (current.length + 2 + trimmed.length <= limit) {
      current.write('\n\n');
      current.write(trimmed);
      return;
    }
    flush();
    current.write(trimmed);
  }

  for (final raw in text.split(RegExp(r'\n\s*\n'))) {
    final paragraph = raw.trim();
    if (paragraph.isEmpty) {
      continue;
    }
    if (paragraph.length <= limit) {
      appendPiece(paragraph);
      continue;
    }
    for (final sentence in paragraph.split(_sentences)) {
      appendPiece(sentence);
    }
  }
  flush();
  return chunks;
}

List<String> _splitHard(String text, int limit) {
  final parts = <String>[];
  var remaining = text;
  while (remaining.length > limit) {
    var cut = remaining.lastIndexOf(' ', limit);
    if (cut <= 0) {
      cut = limit;
    }
    parts.add(remaining.substring(0, cut).trim());
    remaining = remaining.substring(cut).trim();
  }
  if (remaining.isNotEmpty) {
    parts.add(remaining);
  }
  return parts;
}
