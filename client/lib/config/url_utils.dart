/// Parsed and normalized Secretary API base URL.
Uri? parseApiBaseUrl(String raw) {
  final trimmed = raw.trim();
  if (trimmed.isEmpty) {
    return null;
  }

  final uri = Uri.tryParse(trimmed);
  if (uri == null || !uri.hasScheme || uri.host.isEmpty) {
    return null;
  }
  if (uri.scheme != 'http' && uri.scheme != 'https') {
    return null;
  }
  if (uri.hasQuery || uri.fragment.isNotEmpty) {
    return null;
  }

  return Uri(
    scheme: uri.scheme,
    host: uri.host,
    port: _explicitPort(uri),
    pathSegments: _normalizedPathSegments(uri.path),
  );
}

List<String> _normalizedPathSegments(String path) {
  return path.split('/').where((segment) => segment.isNotEmpty).toList();
}

/// Normalizes and validates a Secretary API base URL string.
String? normalizeBaseUrl(String raw) {
  final uri = parseApiBaseUrl(raw);
  return uri?.toString();
}

/// Builds an endpoint URI from a normalized base and absolute API path.
Uri buildApiEndpointUri(Uri baseUri, String endpointPath) {
  if (!endpointPath.startsWith('/')) {
    throw ArgumentError('endpoint path must start with /');
  }
  if (endpointPath.contains('?') || endpointPath.contains('#')) {
    throw ArgumentError('endpoint path must not contain query or fragment');
  }

  final endpointSegments =
      endpointPath.split('/').where((segment) => segment.isNotEmpty).toList();

  return Uri(
    scheme: baseUri.scheme,
    host: baseUri.host,
    port: _explicitPort(baseUri),
    pathSegments: [...baseUri.pathSegments, ...endpointSegments],
  );
}

int? _explicitPort(Uri uri) {
  if (!uri.hasPort) {
    return null;
  }
  final defaultPort = uri.scheme == 'https' ? 443 : 80;
  return uri.port == defaultPort ? null : uri.port;
}
