import '../api/api_models.dart';
import 'inbox_feed_merge.dart';

InboxSourceObjectOut _markerAnchorItem(InboxReviewMarker marker) {
  return InboxSourceObjectOut(
    id: marker.anchorObjectId,
    title: '',
    kind: 'email',
    provider: null,
    origin: 'source',
    state: 'observed',
    status: null,
    primaryAt: marker.anchorFeedAt,
    excerpt: null,
    feedAt: marker.anchorFeedAt,
  );
}

bool inboxItemIsExactAnchor(
  InboxSourceObjectOut item,
  InboxReviewMarker marker,
) {
  return compareInboxFeedOrder(item, _markerAnchorItem(marker)) == 0;
}

bool inboxItemIsAtOrAboveMarker(
  InboxSourceObjectOut item,
  InboxReviewMarker marker,
) {
  return compareInboxFeedOrder(item, _markerAnchorItem(marker)) <= 0;
}

/// Object-list index where the marker should be inserted, or null if it is
/// older than the currently loaded tail and [hasMore] is true.
int? reviewMarkerInsertIndex({
  required List<InboxSourceObjectOut> objects,
  required InboxReviewMarker? marker,
  required bool hasMore,
}) {
  if (marker == null) {
    return null;
  }
  for (var i = 0; i < objects.length; i++) {
    if (inboxItemIsExactAnchor(objects[i], marker)) {
      return i + 1;
    }
    if (!inboxItemIsAtOrAboveMarker(objects[i], marker)) {
      return i;
    }
  }
  if (hasMore) {
    return null;
  }
  return objects.length;
}
