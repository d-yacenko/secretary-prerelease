import '../api/api_models.dart';

int compareInboxFeedOrder(InboxSourceObjectOut a, InboxSourceObjectOut b) {
  final aAt = DateTime.tryParse(a.feedStamp);
  final bAt = DateTime.tryParse(b.feedStamp);
  if (aAt != null && bAt != null) {
    final byTime = bAt.compareTo(aAt);
    if (byTime != 0) {
      return byTime;
    }
  } else if (aAt != null) {
    return -1;
  } else if (bAt != null) {
    return 1;
  }
  return b.id.compareTo(a.id);
}

List<InboxSourceObjectOut> mergeInboxFeedHead({
  required List<InboxSourceObjectOut> existing,
  required List<InboxSourceObjectOut> firstPage,
  required bool preserveTail,
}) {
  if (!preserveTail) {
    return List<InboxSourceObjectOut>.of(firstPage);
  }
  final byId = <String, InboxSourceObjectOut>{
    for (final item in existing) item.id: item,
  };
  for (final item in firstPage) {
    byId[item.id] = item;
  }
  final merged = byId.values.toList()
    ..sort(compareInboxFeedOrder);
  return merged;
}
