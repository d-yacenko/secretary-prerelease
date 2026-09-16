import 'package:flutter/material.dart';
import 'package:kalender/kalender.dart';

import 'week_overlap.dart';

/// Secretary dense cascade: public kalender overlap vertical geometry, custom
/// horizontal inset from [weekOverlapDepths].
class SecretaryDenseOverlapLayoutStrategy extends EventLayoutStrategy {
  const SecretaryDenseOverlapLayoutStrategy();

  @override
  EventLayoutDelegate createDelegate({
    required Iterable<CalendarEvent> events,
    required InternalDateTime date,
    required TimeOfDayRange timeOfDayRange,
    required double heightPerMinute,
    required double? minimumTileHeight,
    required EventLayoutDelegateCache? cache,
    required Location? location,
  }) {
    return SecretaryDenseOverlapLayoutDelegate(
      events: events,
      date: date,
      heightPerMinute: heightPerMinute,
      timeOfDayRange: timeOfDayRange,
      minimumTileHeight: minimumTileHeight,
      layoutCache: cache ?? EventLayoutDelegateCache(),
      location: location,
    );
  }

  @override
  bool operator ==(Object other) => other.runtimeType == runtimeType;

  @override
  int get hashCode => (SecretaryDenseOverlapLayoutStrategy).hashCode;
}

class SecretaryDenseOverlapLayoutDelegate extends OverlapLayoutDelegate {
  SecretaryDenseOverlapLayoutDelegate({
    required super.events,
    required super.heightPerMinute,
    required super.date,
    required super.location,
    required super.timeOfDayRange,
    required super.minimumTileHeight,
    required super.layoutCache,
  });

  @override
  List<CalendarEvent> sortEvents(Iterable<CalendarEvent> events) {
    final items = events.toList();
    items.sort((a, b) {
      final byDuration = b.duration.compareTo(a.duration);
      if (byDuration != 0) {
        return byDuration;
      }
      final byStart = b
          .internalStart(location: location)
          .compareTo(a.internalStart(location: location));
      if (byStart != 0) {
        return byStart;
      }
      return a.id.compareTo(b.id);
    });
    return items;
  }

  @override
  void performLayout(Size size) {
    final verticalLayoutData = calculateVerticalLayoutData(size);
    final eventList = events.toList();
    final depths = weekOverlapDepthsOnDate(
      events: eventList,
      date: date,
      location: location,
    );

    for (final data in verticalLayoutData) {
      final event = eventList[data.id];
      final inset = weekOverlapLeftInset(depths[event.id] ?? 0);
      final width = size.width * (1.0 - inset);
      final xOffset = size.width * inset;
      if (hasChild(data.id)) {
        layoutChild(
          data.id,
          BoxConstraints.tightFor(width: width, height: data.height),
        );
        positionChild(data.id, Offset(xOffset, data.top));
      }
    }
  }
}
