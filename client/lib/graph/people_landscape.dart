import 'dart:math' as math;
import 'dart:ui';

import 'graph_layout.dart';

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
