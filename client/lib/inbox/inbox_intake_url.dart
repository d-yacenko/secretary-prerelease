/// Whether [text] is exactly one absolute http/https URL (trimmed, no extra text).
bool isExactHttpUrl(String text) {
  final trimmed = text.trim();
  if (trimmed.isEmpty || trimmed.contains(RegExp(r'\s'))) {
    return false;
  }
  final uri = Uri.tryParse(trimmed);
  if (uri == null) {
    return false;
  }
  if (uri.scheme != 'http' && uri.scheme != 'https') {
    return false;
  }
  if (uri.host.isEmpty) {
    return false;
  }
  return true;
}
