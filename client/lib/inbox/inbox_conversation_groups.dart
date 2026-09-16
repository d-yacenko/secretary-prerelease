import '../api/api_models.dart';
import '../ui/date_format.dart';
import '../ui/inbox_date_groups.dart';
import 'inbox_feed_merge.dart';
import 'inbox_review_marker.dart';

bool _prefixMatch(List<InboxSourceObjectOut> objects, int start, List<String> ids) {
  if (ids.isEmpty || start + ids.length > objects.length) {
    return false;
  }
  for (var i = 0; i < ids.length; i++) {
    if (objects[start + i].id != ids[i]) {
      return false;
    }
  }
  return true;
}

List<InboxSourceListEntry> overlayInboxConversationEntries(
  List<InboxSourceObjectOut> objects,
  List<InboxConversationGroup> overlay,
) {
  if (objects.isEmpty) {
    return const [];
  }
  if (overlay.isEmpty) {
    return groupInboxSourceEntries(objects);
  }
  final visual = <({InboxSourceObjectOut? object, InboxConversationStackEntry? stack})>[];
  var i = 0;
  var overlayIndex = 0;
  while (i < objects.length) {
    var consumed = false;
    if (overlayIndex < overlay.length) {
      final group = overlay[overlayIndex];
      final ids = group.coveredIds;
      if (group.type == 'stack' &&
          group.stack != null &&
          ids.length >= 2 &&
          _prefixMatch(objects, i, ids)) {
        visual.add((
          object: null,
          stack: InboxConversationStackEntry(
            stack: group.stack!,
            children: objects.sublist(i, i + ids.length)
              ..sort((a, b) => compareInboxFeedOrder(b, a)),
          ),
        ));
        i += ids.length;
        overlayIndex += 1;
        consumed = true;
      } else if (group.type == 'singleton' &&
          ids.length == 1 &&
          objects[i].id == ids.first) {
        visual.add((object: objects[i], stack: null));
        i += 1;
        overlayIndex += 1;
        consumed = true;
      }
    }
    if (!consumed) {
      visual.add((object: objects[i], stack: null));
      i += 1;
    }
  }
  final entries = <InboxSourceListEntry>[];
  DateTime? currentDate;
  var undatedOpen = false;
  for (final item in visual) {
    final stamp = item.stack != null
        ? item.stack!.children.first.feedStamp
        : item.object!.feedStamp;
    final date = parseLocalInboxDate(stamp);
    if (date == null) {
      if (!undatedOpen) {
        entries.add(
          const InboxDateSeparatorEntry(date: null, label: 'Без даты'),
        );
        undatedOpen = true;
        currentDate = null;
      }
    } else {
      undatedOpen = false;
      if (currentDate != date) {
        currentDate = date;
        entries.add(
          InboxDateSeparatorEntry(
            date: date,
            label: formatInboxDateSeparator(date),
          ),
        );
      }
    }
    if (item.stack != null) {
      entries.add(item.stack!);
    } else {
      entries.add(InboxSourceObjectEntry(item.object!));
    }
  }
  return entries;
}

int _objectCountOf(InboxSourceListEntry entry) {
  return switch (entry) {
    InboxSourceObjectEntry() => 1,
    InboxConversationStackEntry(:final children) => children.length,
    _ => 0,
  };
}

List<InboxSourceListEntry> insertReviewMarkerAcrossStacks({
  required List<InboxSourceListEntry> entries,
  required int insertBeforeObjectIndex,
}) {
  if (insertBeforeObjectIndex <= 0) {
    return [const InboxReviewMarkerEntry(), ...entries];
  }
  var objectCount = 0;
  var insertAt = entries.length;
  for (var i = 0; i < entries.length; i++) {
    final count = _objectCountOf(entries[i]);
    if (count == 0) {
      continue;
    }
    if (objectCount == insertBeforeObjectIndex) {
      insertAt = i;
      break;
    }
    objectCount += count;
    if (objectCount == insertBeforeObjectIndex) {
      insertAt = i + 1;
      break;
    }
  }
  while (insertAt > 0 && entries[insertAt - 1] is InboxDateSeparatorEntry) {
    insertAt -= 1;
  }
  return [
    ...entries.sublist(0, insertAt),
    const InboxReviewMarkerEntry(),
    ...entries.sublist(insertAt),
  ];
}

List<InboxSourceListEntry> groupInboxFeedEntries({
  required List<InboxSourceObjectOut> objects,
  required List<InboxConversationGroup> overlay,
  required InboxReviewMarker? marker,
  required bool hasMore,
}) {
  final grouped = overlayInboxConversationEntries(objects, overlay);
  final insertAt = reviewMarkerInsertIndex(
    objects: objects,
    marker: marker,
    hasMore: hasMore,
  );
  if (insertAt == null) {
    return grouped;
  }
  return insertReviewMarkerAcrossStacks(
    entries: grouped,
    insertBeforeObjectIndex: insertAt,
  );
}

bool inboxProviderIsMail(String provider) {
  return provider == 'gmail' || provider == 'yandex_mail';
}

String inboxStackCardKind(String provider) {
  return inboxProviderIsMail(provider) ? 'email' : 'chat_message';
}

String inboxStackHeaderTitle(InboxConversationStack stack) {
  final summary = stack.summary?.trim() ?? '';
  final label = stack.conversationLabel.trim();
  if (inboxProviderIsMail(stack.provider)) {
    if (summary.isNotEmpty) {
      return summary;
    }
    if (label.isNotEmpty) {
      return label;
    }
    return '${stack.messageCount} сообщений';
  }
  final topic = summary.isNotEmpty ? summary : '${stack.messageCount} сообщений';
  if (label.isEmpty) {
    return topic;
  }
  return '$label: $topic';
}

String formatConversationTimeRange(String startIso, String endIso) {
  final start = formatUserTime(startIso);
  final end = formatUserTime(endIso);
  if (start.isEmpty) {
    return end;
  }
  if (end.isEmpty || start == end) {
    return start;
  }
  return '$start–$end';
}
