import 'dart:math' as math;
import 'dart:ui';

import '../api/api_models.dart';
import 'graph_layout.dart';

/// Clearance between anchored Task geography and the unanchored strip.
///
/// The strip means only “no current Task anchor”.
const double kPeopleLandscapeShelfGap = kGraphNodeWidth + kGraphNodeHorizontalGap;

/// Unrooted People marker. Smaller than the rooted 186×100 card.
const double kPeopleLandscapeOverviewCardWidth = 140;
const double kPeopleLandscapeOverviewCardHeight = 44;

/// Local gap used when compact cards would touch or nearly touch.
const double kPeopleLandscapeOverviewCardGap = 8;

/// Gap between markers that share one exact Task-anchor set.
const double kPeopleLandscapeIntraClusterGap = 6;

/// Origin of the vertical unanchored strip when no Task geography exists.
const Offset kPeopleLandscapeNeutralShelfOrigin = Offset.zero;

const int kPeopleLandscapeCompactCueLimit = 28;

const int _angularSlots = 24;
const int _maxRings = 48;

/// Derived Person top-lefts from existing Task top-lefts.
///
/// Does not persist coordinates, mutate Task positions, or read role semantics.
/// The same Task id counts once. People with no usable Task anchor are omitted.
/// Overlaps are separated locally in stable Person-id order.
Map<String, Offset> projectPeopleFromTasks({
  required Iterable<String> personIds,
  required Map<String, Offset> taskPositions,
  required Map<String, Iterable<String>> taskIdsByPerson,
  Size cardSize = const Size(kGraphNodeWidth, kGraphNodeHeight),
  double nearGap = 0,
}) {
  final bases = <String, Offset>{};
  for (final personId in personIds) {
    final anchor = _anchor(taskIdsByPerson[personId] ?? const [], taskPositions);
    if (anchor != null) {
      bases[personId] = anchor;
    }
  }
  final ordered = bases.keys.toList()..sort();
  final placed = <String, Offset>{};
  for (final personId in ordered) {
    placed[personId] = _place(bases[personId]!, placed, cardSize, nearGap);
  }
  return placed;
}

class PeopleLandscapeOverview {
  const PeopleLandscapeOverview({
    required this.usable,
    required this.positions,
    required this.anchoredPersonIds,
    required this.unanchoredPersonIds,
    required this.unresolvedPersonIds,
    required this.taskBounds,
  });

  final bool usable;
  final Map<String, Offset> positions;
  final List<String> anchoredPersonIds;
  final List<String> unanchoredPersonIds;
  final List<String> unresolvedPersonIds;

  /// Canonical Task bounds when the projection is usable and Tasks exist.
  final Rect? taskBounds;
}

/// Bounds of every canonical Task card, including Tasks outside the current window.
Rect? canonicalTaskWorldBounds(Map<String, Offset> taskCenters) {
  if (taskCenters.isEmpty) {
    return null;
  }
  var minX = double.infinity;
  var minY = double.infinity;
  var maxX = double.negativeInfinity;
  var maxY = double.negativeInfinity;
  const halfW = kGraphNodeWidth / 2;
  const halfH = kGraphNodeHeight / 2;
  for (final center in taskCenters.values) {
    minX = math.min(minX, center.dx - halfW);
    minY = math.min(minY, center.dy - halfH);
    maxX = math.max(maxX, center.dx + halfW);
    maxY = math.max(maxY, center.dy + halfH);
  }
  return Rect.fromLTRB(minX, minY, maxX, maxY);
}

Offset peopleMarkerTopLeft(Offset center) {
  return center -
      const Offset(
        kPeopleLandscapeOverviewCardWidth / 2,
        kPeopleLandscapeOverviewCardHeight / 2,
      );
}

Offset peopleMarkerCenter(Offset topLeft) {
  return topLeft +
      const Offset(
        kPeopleLandscapeOverviewCardWidth / 2,
        kPeopleLandscapeOverviewCardHeight / 2,
      );
}

/// People markers on the canonical Task-center world.
///
/// [taskCenters] are persisted Task centers, not card top-lefts. Returned
/// positions are marker top-lefts, so an unspread marker's center is the
/// Task center or the unweighted centroid of distinct anchors.
PeopleLandscapeOverview projectPeopleLandscapeOverview({
  required Iterable<String> personIds,
  required Iterable<PersonPresentation> people,
  required Map<String, Offset> taskCenters,
  required bool canonicalCentersActive,
}) {
  final visibleIds = personIds.toList();
  if (!canonicalCentersActive) {
    return _unusable(visibleIds);
  }
  final peopleById = {for (final person in people) person.personId: person};
  final bases = <String, Offset>{};
  final unanchored = <String>[];
  final unresolved = <String>[];
  for (final personId in visibleIds) {
    final person = peopleById[personId];
    if (person == null || !person.landscapeTaskIdsComplete) {
      unresolved.add(personId);
      continue;
    }
    final anchors = person.landscapeTaskIds.toSet().toList()..sort();
    if (anchors.isEmpty) {
      unanchored.add(personId);
      continue;
    }
    if (anchors.any((id) => !taskCenters.containsKey(id))) {
      unresolved.add(personId);
      continue;
    }
    var x = 0.0;
    var y = 0.0;
    for (final id in anchors) {
      final center = taskCenters[id]!;
      x += center.dx;
      y += center.dy;
    }
    bases[personId] = Offset(x / anchors.length, y / anchors.length);
  }
  if (unresolved.isNotEmpty) {
    return _unusable(unresolved);
  }
  const cardSize = Size(
    kPeopleLandscapeOverviewCardWidth,
    kPeopleLandscapeOverviewCardHeight,
  );
  final ordered = bases.keys.toList()..sort();
  final groups = <String, List<String>>{};
  final anchorOf = <String, Offset>{};
  for (final personId in ordered) {
    final anchors = peopleById[personId]!.landscapeTaskIds.toSet().toList()..sort();
    final key = anchors.join('\u0001');
    (groups[key] ??= <String>[]).add(personId);
    anchorOf[key] = bases[personId]!;
  }
  final groupKeys = groups.keys.toList()
    ..sort((a, b) => groups[a]!.first.compareTo(groups[b]!.first));
  final anchoredPositions = <String, Offset>{};
  for (final key in groupKeys) {
    final members = groups[key]!;
    final packed = _packSameAnchorCluster(members.length);
    final anchor = anchorOf[key]!;
    final cluster = <String, Offset>{
      for (var index = 0; index < members.length; index++)
        members[index]: packed[index] + anchor,
    };
    final delta = _separateCluster(cluster, anchoredPositions, cardSize);
    anchoredPositions.addAll({
      for (final entry in cluster.entries) entry.key: entry.value + delta,
    });
  }
  final taskBounds = canonicalTaskWorldBounds(taskCenters);
  final positions = Map<String, Offset>.from(anchoredPositions);
  positions.addAll(_shelfPositions(unanchored, taskBounds, anchoredPositions));
  return PeopleLandscapeOverview(
    usable: true,
    positions: positions,
    anchoredPersonIds: ordered,
    unanchoredPersonIds: unanchored..sort(),
    unresolvedPersonIds: const [],
    taskBounds: taskBounds,
  );
}

PeopleLandscapeOverview _unusable(List<String> unresolved) {
  final ids = List<String>.from(unresolved)..sort();
  return PeopleLandscapeOverview(
    usable: false,
    positions: const {},
    anchoredPersonIds: const [],
    unanchoredPersonIds: const [],
    unresolvedPersonIds: ids,
    taskBounds: null,
  );
}

Map<String, Offset> _shelfPositions(
  List<String> personIds,
  Rect? taskBounds,
  Map<String, Offset> anchoredPositions,
) {
  final ordered = List<String>.from(personIds)..sort();
  if (ordered.isEmpty) {
    return const {};
  }
  final origin = taskBounds == null && anchoredPositions.isEmpty
      ? kPeopleLandscapeNeutralShelfOrigin
      : Offset(
          _occupiedRight(taskBounds, anchoredPositions) + kPeopleLandscapeShelfGap,
          taskBounds?.top ?? kPeopleLandscapeNeutralShelfOrigin.dy,
        );
  final placed = <String, Offset>{};
  final step = kPeopleLandscapeOverviewCardHeight + kPeopleLandscapeOverviewCardGap;
  for (var index = 0; index < ordered.length; index++) {
    placed[ordered[index]] = Offset(origin.dx, origin.dy + index * step);
  }
  return placed;
}

double _occupiedRight(Rect? taskBounds, Map<String, Offset> anchoredPositions) {
  var right = taskBounds?.right ?? double.negativeInfinity;
  for (final topLeft in anchoredPositions.values) {
    right = math.max(right, topLeft.dx + kPeopleLandscapeOverviewCardWidth);
  }
  return right;
}

List<Offset> _packSameAnchorCluster(int count) {
  if (count <= 0) {
    return const [];
  }
  final cols = count == 1
      ? 1
      : count == 2
          ? 2
          : math.max(1, math.sqrt(count).ceil());
  final stepX = kPeopleLandscapeOverviewCardWidth + kPeopleLandscapeIntraClusterGap;
  final stepY = kPeopleLandscapeOverviewCardHeight + kPeopleLandscapeIntraClusterGap;
  final topLefts = <Offset>[
    for (var index = 0; index < count; index++)
      Offset((index % cols) * stepX, (index ~/ cols) * stepY),
  ];
  var sumX = 0.0;
  var sumY = 0.0;
  for (final topLeft in topLefts) {
    final center = peopleMarkerCenter(topLeft);
    sumX += center.dx;
    sumY += center.dy;
  }
  final shift = Offset(sumX / count, sumY / count);
  return [for (final topLeft in topLefts) topLeft - shift];
}

Offset _separateCluster(
  Map<String, Offset> cluster,
  Map<String, Offset> placed,
  Size cardSize,
) {
  if (placed.isEmpty || !_clusterHits(cluster, placed, cardSize)) {
    return Offset.zero;
  }
  for (var ring = 1; ring <= 64; ring++) {
    final radius = ring * kPeopleLandscapeIntraClusterGap;
    for (var slot = 0; slot < 8; slot++) {
      final angle = slot * math.pi / 4;
      final delta = Offset(math.cos(angle) * radius, math.sin(angle) * radius);
      final shifted = {
        for (final entry in cluster.entries) entry.key: entry.value + delta,
      };
      if (!_clusterHits(shifted, placed, cardSize)) {
        return delta;
      }
    }
  }
  throw StateError('no free local slot for person landscape');
}

bool _clusterHits(
  Map<String, Offset> cluster,
  Map<String, Offset> placed,
  Size cardSize,
) {
  for (final candidate in cluster.values) {
    final probe = _cardRect(candidate, cardSize, 0);
    for (final other in placed.values) {
      final rect = _cardRect(other, cardSize, 0);
      if (probe.left < rect.right - 0.01 &&
          probe.right > rect.left + 0.01 &&
          probe.top < rect.bottom - 0.01 &&
          probe.bottom > rect.top + 0.01) {
        return true;
      }
    }
  }
  return false;
}

Offset? _anchor(Iterable<String> taskIds, Map<String, Offset> taskPositions) {
  final ids = taskIds.where(taskPositions.containsKey).toSet().toList()..sort();
  if (ids.isEmpty) {
    return null;
  }
  var x = 0.0;
  var y = 0.0;
  for (final id in ids) {
    final position = taskPositions[id]!;
    x += position.dx;
    y += position.dy;
  }
  final count = ids.length;
  return Offset(x / count, y / count);
}

Offset _place(Offset base, Map<String, Offset> placed, Size cardSize, double nearGap) {
  if (!_overlaps(base, placed, cardSize, nearGap)) {
    return base;
  }
  final step = _minCenterSeparation(cardSize, nearGap);
  final angleStep = (2 * math.pi) / _angularSlots;
  for (var ring = 0; ring < _maxRings; ring++) {
    final radius = step + ring * step;
    for (var slot = 0; slot < _angularSlots; slot++) {
      final angle = angleStep * slot - math.pi / 2;
      final center = Offset(
        base.dx + cardSize.width / 2 + math.cos(angle) * radius,
        base.dy + cardSize.height / 2 + math.sin(angle) * radius,
      );
      final candidate = Offset(
        center.dx - cardSize.width / 2,
        center.dy - cardSize.height / 2,
      );
      if (!_overlaps(candidate, placed, cardSize, nearGap)) {
        return candidate;
      }
    }
  }
  throw StateError('no free local slot for person landscape');
}

bool _overlaps(Offset candidate, Map<String, Offset> placed, Size cardSize, double nearGap) {
  final probe = _cardRect(candidate, cardSize, nearGap);
  for (final other in placed.values) {
    if (probe.overlaps(_cardRect(other, cardSize, nearGap))) {
      return true;
    }
  }
  return false;
}

Rect _cardRect(Offset topLeft, Size cardSize, double nearGap) {
  return Rect.fromLTWH(
    topLeft.dx - nearGap / 2,
    topLeft.dy - nearGap / 2,
    cardSize.width + nearGap,
    cardSize.height + nearGap,
  );
}

double _minCenterSeparation(Size cardSize, double nearGap) {
  final gapX = nearGap > 0 ? nearGap : kGraphNodeHorizontalGap;
  final gapY = nearGap > 0 ? nearGap : kGraphNodeVerticalGap;
  final sepW = cardSize.width + gapX;
  final sepH = cardSize.height + gapY;
  return math.sqrt(sepW * sepW + sepH * sepH);
}
