import '../api/api_error.dart';
import '../api/api_models.dart';
import '../api/secretary_api_client.dart';

const int kLabelsByObjectsMax = 100;

typedef AuthFailure = void Function();

Future<Map<String, List<LabelItem>>> loadAssignedLabelsByObjects({
  required SecretaryApiClient apiClient,
  required AuthFailure? onAuthFailure,
  required Iterable<String> objectIds,
}) async {
  final unique = <String>[];
  final seen = <String>{};
  for (final id in objectIds) {
    final trimmed = id.trim();
    if (trimmed.isEmpty || !seen.add(trimmed)) {
      continue;
    }
    unique.add(trimmed);
  }
  if (unique.isEmpty) {
    return {};
  }
  final merged = <String, List<LabelItem>>{};
  try {
    for (var offset = 0; offset < unique.length; offset += kLabelsByObjectsMax) {
      final chunk = unique.sublist(
        offset,
        offset + kLabelsByObjectsMax > unique.length
            ? unique.length
            : offset + kLabelsByObjectsMax,
      );
      final part = await apiClient.labelsByObjects(chunk);
      merged.addAll(part);
    }
    return merged;
  } on AuthenticationException {
    onAuthFailure?.call();
    return {};
  } on ApiException {
    return {};
  }
}