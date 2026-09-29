import 'dart:math' as math;
import 'dart:ui';

import '../api/api_models.dart';
import 'graph_layout.dart';
import 'task_map_hierarchy.dart';

/// Clearance between canonical Task bounds and the unanchored Person shelf.
///
/// One card width plus the ordinary node gap keeps a 186×100 Person card
/// from overlapping Task bounds. The shelf means only “no current Task anchor”.
const double kPeopleLandscapeShelfGap = kGraphNodeWidth + kGraphNodeHorizontalGap;

/// Shelf columns. Rows continue with the ordinary graph node step.
const int kPeopleLandscapeShelfColumns = kGraphOverviewColumns;

/// Shelf origin when the Task context has no Task nodes.
const Offset kPeopleLandscapeNeutralShelfOrigin = Offset.zero;

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
    placed[personId] = _place(bases[personId]!, placed);
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
  final anchoredPositions = projectPeopleFromTasks(
    personIds: anchored.keys,
    taskPositions: hierarchy.positions,
    taskIdsByPerson: anchored,
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
  if (taskBounds != null) {
    // Stay right of Task bounds and of already placed anchored cards.
    var right = taskBounds.right;
    for (final position in anchoredPositions.values) {
      right = math.max(right, position.dx + kGraphNodeWidth);
    }
    origin = Offset(right + kPeopleLandscapeShelfGap, taskBounds.top);
  }
  final placed = <String, Offset>{};
  for (var index = 0; index < ordered.length; index++) {
    final column = index % kPeopleLandscapeShelfColumns;
    final row = index ~/ kPeopleLandscapeShelfColumns;
    placed[ordered[index]] = Offset(
      origin.dx + column * GraphLayout.overviewColumnStep,
      origin.dy + row * GraphLayout.overviewRowStep,
    );
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

Offset _place(Offset base, Map<String, Offset> placed) {
  if (!_overlaps(base, placed)) {
    return base;
  }
  final step = _minCenterSeparation();
  final angleStep = (2 * math.pi) / _angularSlots;
  for (var ring = 0; ring < _maxRings; ring++) {
    final radius = step + ring * step;
    for (var slot = 0; slot < _angularSlots; slot++) {
      final angle = angleStep * slot - math.pi / 2;
      final center = Offset(
        base.dx + kGraphNodeWidth / 2 + math.cos(angle) * radius,
        base.dy + kGraphNodeHeight / 2 + math.sin(angle) * radius,
      );
      final candidate = Offset(
        center.dx - kGraphNodeWidth / 2,
        center.dy - kGraphNodeHeight / 2,
      );
      if (!_overlaps(candidate, placed)) {
        return candidate;
      }
    }
  }
  throw StateError('no free local slot for person landscape');
}

bool _overlaps(Offset candidate, Map<String, Offset> placed) {
  for (final other in placed.values) {
    if (GraphLayout.nodeRectsOverlap(candidate, other)) {
      return true;
    }
  }
  return false;
}

double _minCenterSeparation() {
  final sepW = kGraphNodeWidth + kGraphNodeHorizontalGap;
  final sepH = kGraphNodeHeight + kGraphNodeVerticalGap;
  return math.sqrt(sepW * sepW + sepH * sepH);
}
