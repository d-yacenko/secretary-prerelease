import '../api/api_error.dart';
import '../api/secretary_api_client.dart';

const int kBookmarksByObjectsMax = 100;

typedef AuthFailure = void Function();

class BookmarkBatchLoadResult {
  const BookmarkBatchLoadResult({
    required this.succeeded,
    required this.bookmarks,
  });

  final bool succeeded;
  final Map<String, String> bookmarks;
}

List<String> uniqueObjectIds(Iterable<String> objectIds) {
  final unique = <String>[];
  final seen = <String>{};
  for (final id in objectIds) {
    final trimmed = id.trim();
    if (trimmed.isEmpty || !seen.add(trimmed)) {
      continue;
    }
    unique.add(trimmed);
  }
  return unique;
}

Future<BookmarkBatchLoadResult> loadBookmarksByObjects({
  required SecretaryApiClient apiClient,
  required AuthFailure? onAuthFailure,
  required Iterable<String> objectIds,
}) async {
  final unique = uniqueObjectIds(objectIds);
  if (unique.isEmpty) {
    return const BookmarkBatchLoadResult(succeeded: true, bookmarks: {});
  }
  final merged = <String, String>{};
  try {
    for (var offset = 0; offset < unique.length; offset += kBookmarksByObjectsMax) {
      final chunk = unique.sublist(
        offset,
        offset + kBookmarksByObjectsMax > unique.length
            ? unique.length
            : offset + kBookmarksByObjectsMax,
      );
      merged.addAll(await apiClient.bookmarksByObjects(chunk));
    }
    return BookmarkBatchLoadResult(succeeded: true, bookmarks: merged);
  } on AuthenticationException {
    onAuthFailure?.call();
    return const BookmarkBatchLoadResult(succeeded: false, bookmarks: {});
  } on ApiException {
    return const BookmarkBatchLoadResult(succeeded: false, bookmarks: {});
  }
}
