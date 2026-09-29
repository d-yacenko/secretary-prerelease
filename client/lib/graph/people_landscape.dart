import 'dart:math' as math;
import 'dart:ui';

import '../api/api_models.dart';
import 'graph_layout.dart';
import 'task_map_hierarchy.dart';

/// Clearance between anchored Task geography and the unanchored strip.
///
/// The strip means only “no current Task anchor”.
const double kPeopleLandscapeShelfGap = kGraphNodeWidth + kGraphNodeHorizontalGap;

/// Unrooted People overview card. Smaller than the rooted 186×100 card.
const double kPeopleLandscapeOverviewCardWidth = 156;
const double kPeopleLandscapeOverviewCardHeight = 56;

/// Local gap used when compact cards would touch or nearly touch.
const double kPeopleLandscapeOverviewCardGap = 8;

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

PeopleLandscapeOverview projectPeopleLandscapeOverview({
  required Iterable<String> personIds,
  required Iterable<PersonPresentation> people,
  required List<SecretaryObject> landscapeTasks,
  required List<SecretaryEdge> landscapeTaskEdges,
  required bool landscapeTaskContextComplete,
}) {
  final visibleIds = personIds.toList();
  if (!landscapeTaskContextComplete) {
    return _unusable(visibleIds);
  }
  final hierarchy = projectTaskMapHierarchy(
    nodes: landscapeTasks,
    edges: landscapeTaskEdges,
  );
  final peopleById = {for (final person in people) person.personId: person};
  final anchored = <String, List<String>>{};
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
    if (anchors.any((id) => !hierarchy.positions.containsKey(id))) {
      unresolved.add(personId);
      continue;
    }
    anchored[personId] = person.landscapeTaskIds.toList();
  }
  if (unresolved.isNotEmpty) {
    return _unusable(unresolved);
  }
  final tasks = landscapeTasks.where((node) => node.kind == 'task').toList();
  const cardSize = Size(
    kPeopleLandscapeOverviewCardWidth,
    kPeopleLandscapeOverviewCardHeight,
  );
  final anchoredPositions = projectPeopleFromTasks(
    personIds: anchored.keys,
    taskPositions: hierarchy.positions,
    taskIdsByPerson: anchored,
    cardSize: cardSize,
    nearGap: kPeopleLandscapeOverviewCardGap,
  );
  final taskBounds = tasks.isEmpty ? null : hierarchy.taskBounds;
  final positions = Map<String, Offset>.from(anchoredPositions);
  positions.addAll(_shelfPositions(unanchored, taskBounds, anchoredPositions));
  return PeopleLandscapeOverview(
    usable: true,
    positions: positions,
    anchoredPersonIds: anchored.keys.toList()..sort(),
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
  var origin = kPeopleLandscapeNeutralShelfOrigin;
  if (taskBounds != null || anchoredPositions.isNotEmpty) {
    var right = taskBounds?.right ?? double.negativeInfinity;
    for (final position in anchoredPositions.values) {
      right = math.max(right, position.dx + kPeopleLandscapeOverviewCardWidth);
    }
    origin = Offset(
      right + kPeopleLandscapeShelfGap,
      taskBounds?.top ?? kPeopleLandscapeNeutralShelfOrigin.dy,
    );
  }
  final placed = <String, Offset>{};
  final step = kPeopleLandscapeOverviewCardHeight + kPeopleLandscapeOverviewCardGap;
  for (var index = 0; index < ordered.length; index++) {
    placed[ordered[index]] = Offset(origin.dx, origin.dy + index * step);
  }
  return placed;
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
