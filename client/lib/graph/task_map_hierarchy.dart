import 'dart:math' as math;
import 'dart:ui';

import '../api/api_models.dart';
import 'graph_layout.dart';
import 'graph_map_edge_presentation.dart';
import 'hybrid_focus_lod.dart';

/// Inflates each Task presentation rect before component packing.
const double kTaskMapHaloAllowance = 80;

/// Gap between parent and child circumradii. Same allowance as the halo.
const double kTaskMapHierarchyGap = 80;

/// Extra gap between already-inflated component envelopes.
const double kTaskMapComponentGap = 24;

/// Shelf width is sqrt(total envelope area) times this landscape factor.
const double kTaskMapPackLandscape = 1.4;

class TaskHierarchyPlacement {
  const TaskHierarchyPlacement({
    required this.id,
    required this.parentId,
    required this.rootId,
    required this.depth,
    required this.radius,
    required this.angle,
    required this.sectorStart,
    required this.sectorEnd,
  });

  final String id;
  final String? parentId;
  final String rootId;
  final int depth;
  final double radius;
  final double angle;
  final double sectorStart;
  final double sectorEnd;
}

class TaskMapComponent {
  const TaskMapComponent({
    required this.key,
    required this.structuralTreeCount,
    required this.depth,
    required this.taskIds,
    required this.envelope,
  });

  final String key;

  /// Confirmed `part_of` trees inside this visual packing component.
  final int structuralTreeCount;
  final int depth;
  final List<String> taskIds;

  /// Inflated component bounds in the final presentation coordinates.
  final Rect envelope;

  double get area => envelope.width * envelope.height;
}

class TaskMapHierarchyProjection {
  const TaskMapHierarchyProjection({
    required this.positions,
    required this.baselinePositions,
    required this.components,
    required this.placements,
    required this.taskRectOverlaps,
    required this.envelopeOverlaps,
    required this.occupiedRows,
    required this.maxColumns,
    required this.taskBounds,
  });

  /// Presentation top-lefts in the 186×100 center convention.
  final Map<String, Offset> positions;

  /// Task-only GraphLayout used for sibling polar order. Not the drawn map.
  final Map<String, Offset> baselinePositions;
  final List<TaskMapComponent> components;
  final Map<String, TaskHierarchyPlacement> placements;
  final int taskRectOverlaps;
  final int envelopeOverlaps;
  final int occupiedRows;
  final int maxColumns;
  final Rect taskBounds;

  int get taskCount => positions.length;

  /// Confirmed `part_of` trees, including several trees that share one visual component.
  int get hierarchyTreeCount {
    final roots = <String>{};
    for (final placement in placements.values) {
      if (placement.parentId == null) {
        roots.add(placement.rootId);
      }
    }
    return roots.length;
  }

  /// Visual packing components that contain no confirmed `part_of` tree.
  int get freeComponentCount =>
      components.where((component) => component.structuralTreeCount == 0).length;
  int get maxDepth {
    var depth = 0;
    for (final placement in placements.values) {
      depth = math.max(depth, placement.depth);
    }
    return depth;
  }
}

/// Presentation geography for visible Tasks. Does not read Flow coordinates.
TaskMapHierarchyProjection projectTaskMapHierarchy({
  required List<SecretaryObject> nodes,
  required List<SecretaryEdge> edges,
}) {
  final tasks = [
    for (final node in nodes)
      if (node.kind == 'task') node,
  ]..sort((a, b) => a.id.compareTo(b.id));
  final taskById = {for (final task in tasks) task.id: task};
  if (tasks.isEmpty) {
    return TaskMapHierarchyProjection(
      positions: const {},
      baselinePositions: const {},
      components: const [],
      placements: const {},
      taskRectOverlaps: 0,
      envelopeOverlaps: 0,
      occupiedRows: 0,
      maxColumns: 0,
      taskBounds: const Rect.fromLTWH(-100, -100, 200, 200),
    );
  }

  final layoutEdges = <SecretaryEdge>[];
  final confirmedPartOf = <SecretaryEdge>[];
  for (final edge in edges) {
    final source = taskById[edge.sourceId];
    final target = taskById[edge.targetId];
    if (source == null || target == null) {
      continue;
    }
    if (!presentGraphMapEdge(
      edge: edge,
      sourceKind: source.kind,
      targetKind: target.kind,
    ).visibleOnTasksMap) {
      continue;
    }
    if (edge.state == 'rejected') {
      continue;
    }
    if (edge.type == 'part_of') {
      if (edge.state == 'confirmed') {
        confirmedPartOf.add(edge);
      }
      continue;
    }
    layoutEdges.add(edge);
  }
  confirmedPartOf.sort((a, b) => a.id.compareTo(b.id));
  layoutEdges.sort((a, b) => a.id.compareTo(b.id));

  final parentOf = <String, String>{};
  for (final edge in confirmedPartOf) {
    parentOf.putIfAbsent(edge.sourceId, () => edge.targetId);
  }
  final childrenOf = <String, List<String>>{};
  for (final entry in parentOf.entries) {
    childrenOf.putIfAbsent(entry.value, () => <String>[]).add(entry.key);
  }
  final hierarchyIds = <String>{
    ...parentOf.keys,
    ...parentOf.values.where(taskById.containsKey),
  };
  final roots = hierarchyIds.where((id) => !parentOf.containsKey(id)).toList()
    ..sort();

  final baselinePositions = GraphLayout.computePositions(
    nodes: tasks,
    edges: [...layoutEdges, ...confirmedPartOf],
    rootId: null,
    existing: const {},
    freshRoot: true,
  );

  final placements = <String, TaskHierarchyPlacement>{};
  final packingAdjacency = _undirected(
    [...confirmedPartOf, ...layoutEdges],
    taskById.keys.toSet(),
  );
  final drafted = <_DraftComponent>[
    for (final memberIds in _components(taskById.keys.toSet(), packingAdjacency))
      _draftVisualComponent(
        memberIds: memberIds,
        taskById: taskById,
        childrenOf: childrenOf,
        roots: roots.where(memberIds.contains).toList(),
        layoutEdges: layoutEdges,
        baselinePositions: baselinePositions,
        placements: placements,
      ),
  ];

  drafted.sort((a, b) {
    final left = a.envelope.width * a.envelope.height;
    final right = b.envelope.width * b.envelope.height;
    final area = right.compareTo(left);
    if (area != 0) {
      return area;
    }
    return a.key.compareTo(b.key);
  });
  final packed = _pack(drafted);
  final components = <TaskMapComponent>[];
  final positions = <String, Offset>{};
  for (final placed in packed) {
    positions.addAll(placed.positions);
    components.add(
      TaskMapComponent(
        key: placed.draft.key,
        structuralTreeCount: placed.draft.structuralTreeCount,
        depth: placed.draft.depth,
        taskIds: placed.draft.taskIds,
        envelope: placed.envelope,
      ),
    );
  }

  return TaskMapHierarchyProjection(
    positions: positions,
    baselinePositions: baselinePositions,
    components: components,
    placements: placements,
    taskRectOverlaps: _rectOverlaps(positions, taskById),
    envelopeOverlaps: _envelopeOverlaps(components),
    occupiedRows: packed.isEmpty ? 0 : packed.map((item) => item.row).reduce(math.max) + 1,
    maxColumns: packed.isEmpty
        ? 0
        : _maxColumns(packed),
    taskBounds: _plainBounds(positions, taskById),
  );
}

class _DraftComponent {
  const _DraftComponent({
    required this.key,
    required this.structuralTreeCount,
    required this.depth,
    required this.taskIds,
    required this.localPositions,
    required this.envelope,
  });

  final String key;
  final int structuralTreeCount;
  final int depth;
  final List<String> taskIds;
  final Map<String, Offset> localPositions;
  final Rect envelope;
}

_DraftComponent _draftVisualComponent({
  required Set<String> memberIds,
  required Map<String, SecretaryObject> taskById,
  required Map<String, List<String>> childrenOf,
  required List<String> roots,
  required List<SecretaryEdge> layoutEdges,
  required Map<String, Offset> baselinePositions,
  required Map<String, TaskHierarchyPlacement> placements,
}) {
  final orderedIds = memberIds.toList()..sort();
  if (roots.isEmpty) {
    final componentTasks = [for (final id in orderedIds) taskById[id]!];
    final internalEdges = [
      for (final edge in layoutEdges)
        if (memberIds.contains(edge.sourceId) && memberIds.contains(edge.targetId)) edge,
    ];
    final laid = GraphLayout.computePositions(
      nodes: componentTasks,
      edges: internalEdges,
      rootId: null,
      existing: const {},
      freshRoot: true,
    );
    return _DraftComponent(
      key: orderedIds.first,
      structuralTreeCount: 0,
      depth: 0,
      taskIds: orderedIds,
      localPositions: laid,
      envelope: _envelope(laid, taskById),
    );
  }

  final centers = <String, Offset>{};
  final membersByRoot = <String, Set<String>>{};
  final primaryBaseline = _baselineCenter(baselinePositions[roots.first]);
  for (final rootId in roots) {
    final rootBaseline = _baselineCenter(baselinePositions[rootId]);
    final origin = rootId == roots.first || primaryBaseline == null || rootBaseline == null
        ? Offset.zero
        : rootBaseline - primaryBaseline;
    membersByRoot[rootId] = _treeMembers(rootId, childrenOf, memberIds);
    _placeLocalTree(
      id: rootId,
      parentId: null,
      rootId: rootId,
      depth: 0,
      sectorStart: -math.pi,
      sectorEnd: math.pi,
      origin: origin,
      taskById: taskById,
      childrenOf: childrenOf,
      layoutEdges: layoutEdges,
      baselinePositions: baselinePositions,
      centers: centers,
      placements: placements,
    );
  }
  _separateStructuralTrees(
    rootIds: roots,
    membersByRoot: membersByRoot,
    centers: centers,
    taskById: taskById,
  );
  final freeIds = memberIds.where((id) => !centers.containsKey(id)).toSet();
  _placeFreeTasks(
    freeIds: freeIds,
    layoutEdges: layoutEdges,
    baselinePositions: baselinePositions,
    centers: centers,
    taskById: taskById,
  );
  final positions = {
    for (final id in orderedIds)
      if (centers.containsKey(id)) id: _topLeftForCenter(centers[id]!),
  };
  final treeIds = membersByRoot.values.expand((ids) => ids).toSet();
  final key = roots.length == 1 && freeIds.isEmpty ? roots.single : orderedIds.first;
  return _DraftComponent(
    key: key,
    structuralTreeCount: roots.length,
    depth: _maxDepth(treeIds, placements),
    taskIds: orderedIds,
    localPositions: positions,
    envelope: _envelope(positions, taskById),
  );
}

void _separateStructuralTrees({
  required List<String> rootIds,
  required Map<String, Set<String>> membersByRoot,
  required Map<String, Offset> centers,
  required Map<String, SecretaryObject> taskById,
}) {
  for (var index = 1; index < rootIds.length; index++) {
    final rootId = rootIds[index];
    final members = membersByRoot[rootId] ?? const <String>{};
    for (var step = 0; step < 48; step++) {
      String? blockedBy;
      for (var earlier = 0; earlier < index; earlier++) {
        final other = membersByRoot[rootIds[earlier]] ?? const <String>{};
        if (_memberRectsOverlap(members, other, centers, taskById)) {
          blockedBy = rootIds[earlier];
          break;
        }
      }
      if (blockedBy == null) {
        break;
      }
      final away = _unit(centers[rootId]! - centers[blockedBy]!, const Offset(1, 0));
      for (final id in members) {
        centers[id] = centers[id]! + away * (28 + step * 6);
      }
    }
  }
}

void _placeFreeTasks({
  required Set<String> freeIds,
  required List<SecretaryEdge> layoutEdges,
  required Map<String, Offset> baselinePositions,
  required Map<String, Offset> centers,
  required Map<String, SecretaryObject> taskById,
}) {
  if (freeIds.isEmpty) {
    return;
  }
  final neighbors = <String, Set<String>>{};
  for (final edge in layoutEdges) {
    neighbors.putIfAbsent(edge.sourceId, () => <String>{}).add(edge.targetId);
    neighbors.putIfAbsent(edge.targetId, () => <String>{}).add(edge.sourceId);
  }
  final remaining = Set<String>.from(freeIds);
  final placedFree = <String>{};
  while (remaining.isNotEmpty) {
    String? next;
    String? anchor;
    for (final id in remaining.toList()..sort()) {
      final found = _freeAnchor(
        id: id,
        neighbors: neighbors[id] ?? const <String>{},
        centers: centers,
        placedFree: placedFree,
        baselinePositions: baselinePositions,
      );
      if (found != null) {
        next = id;
        anchor = found;
        break;
      }
    }
    if (next == null || anchor == null) {
      final leftover = remaining.toList()..sort();
      final laid = GraphLayout.computePositions(
        nodes: [for (final id in leftover) taskById[id]!],
        edges: const [],
        rootId: null,
        existing: const {},
        freshRoot: true,
      );
      for (final id in leftover) {
        centers[id] = _clearFree(
          id: id,
          desired: centerFromTopLeft(laid[id]) ?? Offset.zero,
          centers: centers,
          taskById: taskById,
        );
      }
      break;
    }
    final anchorCenter = centers[anchor]!;
    final baselineDelta =
        (_baselineCenter(baselinePositions[next]) ?? anchorCenter) -
        (_baselineCenter(baselinePositions[anchor]) ?? anchorCenter);
    centers[next] = _clearFree(
      id: next,
      desired: anchorCenter + baselineDelta,
      centers: centers,
      taskById: taskById,
    );
    placedFree.add(next);
    remaining.remove(next);
  }
}

String? _freeAnchor({
  required String id,
  required Set<String> neighbors,
  required Map<String, Offset> centers,
  required Set<String> placedFree,
  required Map<String, Offset> baselinePositions,
}) {
  final placed = neighbors.where(centers.containsKey).toList();
  if (placed.isEmpty) {
    return null;
  }
  placed.sort((a, b) {
    final preferPlacedFree = placedFree.contains(a) == placedFree.contains(b)
        ? 0
        : placedFree.contains(a)
        ? 1
        : -1;
    if (preferPlacedFree != 0) {
      return preferPlacedFree;
    }
    final left = _baselineDistance(id, a, baselinePositions);
    final right = _baselineDistance(id, b, baselinePositions);
    final distance = left.compareTo(right);
    if (distance != 0) {
      return distance;
    }
    return a.compareTo(b);
  });
  return placed.first;
}

double _baselineDistance(
  String left,
  String right,
  Map<String, Offset> baselinePositions,
) {
  final a = _baselineCenter(baselinePositions[left]);
  final b = _baselineCenter(baselinePositions[right]);
  if (a == null || b == null) {
    return double.infinity;
  }
  return (a - b).distance;
}

Offset _clearFree({
  required String id,
  required Offset desired,
  required Map<String, Offset> centers,
  required Map<String, SecretaryObject> taskById,
}) {
  var center = desired;
  for (var step = 0; step < 48; step++) {
    final hit = _overlappingCenter(id, center, centers, taskById);
    if (hit == null) {
      return center;
    }
    center += _unit(center - hit, const Offset(1, 0)) * (24 + step * 8);
  }
  return center;
}

Offset? _overlappingCenter(
  String id,
  Offset center,
  Map<String, Offset> centers,
  Map<String, SecretaryObject> taskById,
) {
  final rect = taskPresentationRect(taskById[id]!, _topLeftForCenter(center)).inflate(1);
  final ids = centers.keys.toList()..sort();
  for (final other in ids) {
    if (other == id) {
      continue;
    }
    final otherRect = taskPresentationRect(
      taskById[other]!,
      _topLeftForCenter(centers[other]!),
    ).inflate(1);
    if (rect.overlaps(otherRect)) {
      return centers[other];
    }
  }
  return null;
}

bool _memberRectsOverlap(
  Set<String> left,
  Set<String> right,
  Map<String, Offset> centers,
  Map<String, SecretaryObject> taskById,
) {
  for (final a in left) {
    final leftRect = taskPresentationRect(
      taskById[a]!,
      _topLeftForCenter(centers[a]!),
    ).inflate(1);
    for (final b in right) {
      final rightRect = taskPresentationRect(
        taskById[b]!,
        _topLeftForCenter(centers[b]!),
      ).inflate(1);
      if (leftRect.overlaps(rightRect)) {
        return true;
      }
    }
  }
  return false;
}

Offset _unit(Offset vector, Offset fallback) {
  if (vector.distance < 1) {
    return fallback;
  }
  return vector / vector.distance;
}

Offset? _baselineCenter(Offset? topLeft) => centerFromTopLeft(topLeft);

class _PlacedComponent {
  const _PlacedComponent({
    required this.draft,
    required this.positions,
    required this.envelope,
    required this.row,
    required this.column,
  });

  final _DraftComponent draft;
  final Map<String, Offset> positions;
  final Rect envelope;
  final int row;
  final int column;
}

class _LocalTree {
  _LocalTree({
    required this.id,
    required this.relative,
    required this.extent,
    required this.slots,
  });

  final String id;

  /// Centers relative to this Task. This Task is at [Offset.zero].
  final Map<String, Offset> relative;
  final double extent;
  final List<_ChildSlot> slots;
}

class _ChildSlot {
  const _ChildSlot({
    required this.tree,
    required this.angle,
    required this.distance,
    required this.rotation,
    required this.sectorStart,
    required this.sectorEnd,
  });

  final _LocalTree tree;
  final double angle;
  final double distance;
  final double rotation;
  final double sectorStart;
  final double sectorEnd;

  Offset get center =>
      Offset(math.cos(angle) * distance, math.sin(angle) * distance);
}

void _placeLocalTree({
  required String id,
  required String? parentId,
  required String rootId,
  required int depth,
  required double sectorStart,
  required double sectorEnd,
  required Offset origin,
  required Map<String, SecretaryObject> taskById,
  required Map<String, List<String>> childrenOf,
  required List<SecretaryEdge> layoutEdges,
  required Map<String, Offset> baselinePositions,
  required Map<String, Offset> centers,
  required Map<String, TaskHierarchyPlacement> placements,
}) {
  final tree = _measureLocalTree(
    id: id,
    taskById: taskById,
    childrenOf: childrenOf,
    layoutEdges: layoutEdges,
    baselinePositions: baselinePositions,
    seen: <String>{},
  );
  _stampLocalTree(
    tree: tree,
    origin: origin,
    rotation: 0,
    parentId: parentId,
    rootId: rootId,
    depth: depth,
    sectorStart: sectorStart,
    sectorEnd: sectorEnd,
    centers: centers,
    placements: placements,
  );
}

void _stampLocalTree({
  required _LocalTree tree,
  required Offset origin,
  required double rotation,
  required String? parentId,
  required String rootId,
  required int depth,
  required double sectorStart,
  required double sectorEnd,
  required Map<String, Offset> centers,
  required Map<String, TaskHierarchyPlacement> placements,
}) {
  final parentCenter = parentId == null ? null : centers[parentId];
  final radius = parentCenter == null ? 0.0 : (origin - parentCenter).distance;
  final angle = parentCenter == null
      ? 0.0
      : math.atan2(origin.dy - parentCenter.dy, origin.dx - parentCenter.dx);
  centers[tree.id] = origin;
  placements[tree.id] = TaskHierarchyPlacement(
    id: tree.id,
    parentId: parentId,
    rootId: rootId,
    depth: depth,
    radius: radius,
    angle: angle,
    sectorStart: sectorStart,
    sectorEnd: sectorEnd,
  );
  for (final slot in tree.slots) {
    final local = _rotate(slot.center, rotation);
    _stampLocalTree(
      tree: slot.tree,
      origin: origin + local,
      rotation: rotation + slot.rotation,
      parentId: tree.id,
      rootId: rootId,
      depth: depth + 1,
      sectorStart: slot.sectorStart,
      sectorEnd: slot.sectorEnd,
      centers: centers,
      placements: placements,
    );
  }
}

_LocalTree _measureLocalTree({
  required String id,
  required Map<String, SecretaryObject> taskById,
  required Map<String, List<String>> childrenOf,
  required List<SecretaryEdge> layoutEdges,
  required Map<String, Offset> baselinePositions,
  required Set<String> seen,
}) {
  if (!seen.add(id)) {
    return _LocalTree(
      id: id,
      relative: {id: Offset.zero},
      extent: taskCircumradius(taskById[id]!),
      slots: const [],
    );
  }
  final children = List<String>.from(childrenOf[id] ?? const <String>[])
    ..sort(
      (a, b) => _siblingOrder(
        a,
        b,
        parentCenter: centerFromTopLeft(baselinePositions[id]),
        baselinePositions: baselinePositions,
      ),
    );
  if (children.isEmpty) {
    return _LocalTree(
      id: id,
      relative: {id: Offset.zero},
      extent: taskCircumradius(taskById[id]!),
      slots: const [],
    );
  }
  final childTrees = [
    for (final child in children)
      _measureLocalTree(
        id: child,
        taskById: taskById,
        childrenOf: childrenOf,
        layoutEdges: layoutEdges,
        baselinePositions: baselinePositions,
        seen: seen,
      ),
  ];
  final slots = _arrangeChildren(
    parentId: id,
    parentRadius: taskCircumradius(taskById[id]!),
    children: childTrees,
    layoutEdges: layoutEdges,
  );
  final relative = <String, Offset>{id: Offset.zero};
  for (final slot in slots) {
    for (final entry in slot.tree.relative.entries) {
      relative[entry.key] = slot.center + _rotate(entry.value, slot.rotation);
    }
  }
  return _LocalTree(
    id: id,
    relative: relative,
    extent: _moduleExtent(relative, taskById),
    slots: slots,
  );
}

const int _exactSiblingOrderLimit = 7;
const int _siblingOrderPasses = 6;

class _OrderChoice {
  const _OrderChoice({
    required this.slots,
    required this.score,
    required this.drift,
    required this.spin,
  });

  final List<_ChildSlot> slots;
  final double score;
  final int drift;
  final double spin;

  bool improvesOn(_OrderChoice other) {
    if (score < other.score - 1e-6) {
      return true;
    }
    if ((score - other.score).abs() > 1e-6) {
      return false;
    }
    if (drift != other.drift) {
      return drift < other.drift;
    }
    return spin < other.spin;
  }
}

List<_ChildSlot> _arrangeChildren({
  required String parentId,
  required double parentRadius,
  required List<_LocalTree> children,
  required List<SecretaryEdge> layoutEdges,
}) {
  final baseline = _orientOrder(
    parentId: parentId,
    parentRadius: parentRadius,
    order: children,
    baseline: children,
    baselineRing: double.infinity,
    layoutEdges: layoutEdges,
  );
  if (children.length < 2 ||
      !_frameHasSecondary(parentId, children, layoutEdges)) {
    return baseline.slots;
  }
  final baselineRing = baseline.slots.first.distance;
  _OrderChoice best = baseline;
  void consider(List<_LocalTree> order) {
    final choice = _orientOrder(
      parentId: parentId,
      parentRadius: parentRadius,
      order: order,
      baseline: children,
      baselineRing: baselineRing,
      layoutEdges: layoutEdges,
    );
    if (choice.improvesOn(best)) {
      best = choice;
    }
  }

  if (children.length <= _exactSiblingOrderLimit) {
    final working = [...children];
    _permute(working, 0, consider);
    return best.slots;
  }

  var current = [...children];
  consider(current);
  for (var pass = 0; pass < _siblingOrderPasses; pass++) {
    List<_LocalTree>? next;
    _OrderChoice? nextChoice;
    void offer(List<_LocalTree> order) {
      final choice = _orientOrder(
        parentId: parentId,
        parentRadius: parentRadius,
        order: order,
        baseline: children,
        baselineRing: baselineRing,
        layoutEdges: layoutEdges,
      );
      if (nextChoice == null || choice.improvesOn(nextChoice!)) {
        nextChoice = choice;
        next = [...order];
      }
    }

    for (var i = 0; i < current.length; i++) {
      for (var j = i + 1; j < current.length; j++) {
        final swapped = [...current];
        final held = swapped[i];
        swapped[i] = swapped[j];
        swapped[j] = held;
        offer(swapped);
      }
    }
    for (var start = 0; start < current.length; start++) {
      for (var length = 2; length < current.length; length++) {
        offer(_reverseSegment(current, start, length));
      }
    }
    if (next == null || nextChoice == null || !nextChoice!.improvesOn(best)) {
      break;
    }
    current = next!;
    best = nextChoice!;
  }
  return best.slots;
}

_OrderChoice _orientOrder({
  required String parentId,
  required double parentRadius,
  required List<_LocalTree> order,
  required List<_LocalTree> baseline,
  required double baselineRing,
  required List<SecretaryEdge> layoutEdges,
}) {
  final leafOnly = order.every((child) => child.relative.length < 2);
  final spins = leafOnly
      ? const <double>[0]
      : const <double>[0, math.pi / 2, math.pi, 3 * math.pi / 2];
  _OrderChoice? best;
  for (final spin in spins) {
    final slots = _tuneRotations(
      parentId: parentId,
      slots: _slotsFor(order, parentRadius, spin),
      layoutEdges: layoutEdges,
    );
    final ring = slots.first.distance;
    if (ring > baselineRing + 1) {
      continue;
    }
    final choice = _OrderChoice(
      slots: slots,
      score: _secondaryDistance(
        parentId: parentId,
        slots: slots,
        layoutEdges: layoutEdges,
      ),
      drift: _orderDrift(baseline, order),
      spin: spin,
    );
    if (best == null || choice.improvesOn(best)) {
      best = choice;
    }
  }
  return best ??
      _OrderChoice(
        slots: _slotsFor(order, parentRadius, 0),
        score: double.infinity,
        drift: _orderDrift(baseline, order),
        spin: 0,
      );
}

bool _frameHasSecondary(
  String parentId,
  List<_LocalTree> children,
  List<SecretaryEdge> layoutEdges,
) {
  final ids = <String>{parentId};
  for (final child in children) {
    ids.addAll(child.relative.keys);
  }
  for (final edge in layoutEdges) {
    if (edge.state != 'confirmed' || edge.type == 'part_of') {
      continue;
    }
    if (ids.contains(edge.sourceId) && ids.contains(edge.targetId)) {
      return true;
    }
  }
  return false;
}

int _orderDrift(List<_LocalTree> baseline, List<_LocalTree> order) {
  var drift = 0;
  for (var index = 0; index < baseline.length; index++) {
    if (baseline[index].id != order[index].id) {
      drift += 1;
    }
  }
  return drift;
}

void _permute(
  List<_LocalTree> items,
  int start,
  void Function(List<_LocalTree> order) visit,
) {
  if (start >= items.length) {
    visit(items);
    return;
  }
  for (var index = start; index < items.length; index++) {
    final held = items[start];
    items[start] = items[index];
    items[index] = held;
    _permute(items, start + 1, visit);
    items[index] = items[start];
    items[start] = held;
  }
}

List<_LocalTree> _reverseSegment(List<_LocalTree> order, int start, int length) {
  final copy = [...order];
  final count = copy.length;
  for (var step = 0; step < length ~/ 2; step++) {
    final left = (start + step) % count;
    final right = (start + length - 1 - step) % count;
    final held = copy[left];
    copy[left] = copy[right];
    copy[right] = held;
  }
  return copy;
}

List<_ChildSlot> _slotsFor(List<_LocalTree> children, double parentRadius, double spin) {
  final weights = [for (final child in children) math.max(child.extent, 1.0)];
  final total = weights.fold<double>(0, (sum, weight) => sum + weight);
  const sweep = math.pi * 2;
  const start = -math.pi;
  var cursor = start;
  final angles = <double>[];
  final sectors = <(double, double)>[];
  for (var index = 0; index < children.length; index++) {
    final childSweep = sweep * weights[index] / total;
    angles.add(cursor + childSweep / 2 + spin);
    sectors.add((cursor + spin, cursor + childSweep + spin));
    cursor += childSweep;
  }
  var ring = 0.0;
  for (final child in children) {
    ring = math.max(ring, parentRadius + kTaskMapHierarchyGap + child.extent);
  }
  if (children.length > 1) {
    for (var index = 0; index < children.length; index++) {
      final next = (index + 1) % children.length;
      final gap = _forwardAngle(angles[index], angles[next]);
      final separation =
          children[index].extent + kTaskMapHierarchyGap + children[next].extent;
      final half = gap / 2;
      final sine = math.sin(half);
      if (sine < 1e-4) {
        ring = math.max(ring, separation);
      } else {
        ring = math.max(ring, separation / (2 * sine));
      }
    }
  }
  return [
    for (var index = 0; index < children.length; index++)
      _ChildSlot(
        tree: children[index],
        angle: angles[index],
        distance: ring,
        rotation: 0,
        sectorStart: sectors[index].$1,
        sectorEnd: sectors[index].$2,
      ),
  ];
}

List<_ChildSlot> _tuneRotations({
  required String parentId,
  required List<_ChildSlot> slots,
  required List<SecretaryEdge> layoutEdges,
}) {
  final tuned = [...slots];
  const steps = 12;
  for (var index = 0; index < tuned.length; index++) {
    final slot = tuned[index];
    if (slot.tree.relative.length < 2) {
      continue;
    }
    var bestRotation = 0.0;
    var bestScore = double.infinity;
    for (var step = 0; step < steps; step++) {
      final rotation = step * math.pi * 2 / steps;
      tuned[index] = _ChildSlot(
        tree: slot.tree,
        angle: slot.angle,
        distance: slot.distance,
        rotation: rotation,
        sectorStart: slot.sectorStart,
        sectorEnd: slot.sectorEnd,
      );
      final score = _secondaryDistance(
        parentId: parentId,
        slots: tuned,
        layoutEdges: layoutEdges,
      );
      if (score < bestScore - 1e-6) {
        bestScore = score;
        bestRotation = rotation;
      }
    }
    tuned[index] = _ChildSlot(
      tree: slot.tree,
      angle: slot.angle,
      distance: slot.distance,
      rotation: bestRotation,
      sectorStart: slot.sectorStart,
      sectorEnd: slot.sectorEnd,
    );
  }
  return tuned;
}

double _secondaryDistance({
  required String parentId,
  required List<_ChildSlot> slots,
  required List<SecretaryEdge> layoutEdges,
}) {
  final frame = <String, Offset>{parentId: Offset.zero};
  for (final slot in slots) {
    for (final entry in slot.tree.relative.entries) {
      frame[entry.key] = slot.center + _rotate(entry.value, slot.rotation);
    }
  }
  final ids = frame.keys.toSet();
  var score = 0.0;
  var counted = 0;
  for (final edge in layoutEdges) {
    if (edge.state != 'confirmed' || edge.type == 'part_of') {
      continue;
    }
    if (!ids.contains(edge.sourceId) || !ids.contains(edge.targetId)) {
      continue;
    }
    score += (frame[edge.sourceId]! - frame[edge.targetId]!).distance;
    counted += 1;
  }
  if (counted == 0) {
    return 0;
  }
  return score;
}

double _moduleExtent(
  Map<String, Offset> relative,
  Map<String, SecretaryObject> taskById,
) {
  var extent = 0.0;
  for (final entry in relative.entries) {
    extent = math.max(
      extent,
      entry.value.distance + taskCircumradius(taskById[entry.key]!),
    );
  }
  return extent;
}

Offset _rotate(Offset point, double rotation) {
  if (rotation == 0) {
    return point;
  }
  final cos = math.cos(rotation);
  final sin = math.sin(rotation);
  return Offset(point.dx * cos - point.dy * sin, point.dx * sin + point.dy * cos);
}

double _forwardAngle(double from, double to) {
  var delta = to - from;
  while (delta <= 1e-9) {
    delta += math.pi * 2;
  }
  return delta;
}

int _siblingOrder(
  String a,
  String b, {
  required Offset? parentCenter,
  required Map<String, Offset> baselinePositions,
}) {
  final left = _baselineAngle(a, parentCenter, baselinePositions);
  final right = _baselineAngle(b, parentCenter, baselinePositions);
  if ((left - right).abs() > 1e-6) {
    return left.compareTo(right);
  }
  return a.compareTo(b);
}

double _baselineAngle(
  String id,
  Offset? parentCenter,
  Map<String, Offset> baselinePositions,
) {
  final child = centerFromTopLeft(baselinePositions[id]);
  if (parentCenter == null || child == null) {
    return 0;
  }
  return math.atan2(child.dy - parentCenter.dy, child.dx - parentCenter.dx);
}

Set<String> _treeMembers(
  String rootId,
  Map<String, List<String>> childrenOf,
  Set<String> known,
) {
  final members = <String>{};
  final stack = <String>[rootId];
  while (stack.isNotEmpty) {
    final current = stack.removeLast();
    if (!known.contains(current) || !members.add(current)) {
      continue;
    }
    stack.addAll(childrenOf[current] ?? const <String>[]);
  }
  return members;
}

int _maxDepth(Set<String> ids, Map<String, TaskHierarchyPlacement> placements) {
  var depth = 0;
  for (final id in ids) {
    depth = math.max(depth, placements[id]?.depth ?? 0);
  }
  return depth;
}

double taskCircumradius(SecretaryObject task) {
  if (task.isOngoingTask) {
    return kHybridOngoingSize / 2;
  }
  return math.sqrt(
        kGraphNodeWidth * kGraphNodeWidth + kGraphNodeHeight * kGraphNodeHeight,
      ) /
      2;
}

Offset _topLeftForCenter(Offset center) {
  return center - const Offset(kGraphNodeWidth / 2, kGraphNodeHeight / 2);
}

Offset? centerFromTopLeft(Offset? topLeft) {
  if (topLeft == null) {
    return null;
  }
  return topLeft + const Offset(kGraphNodeWidth / 2, kGraphNodeHeight / 2);
}

Rect taskPresentationRect(SecretaryObject task, Offset topLeft) {
  if (task.isOngoingTask) {
    return hybridOngoingRect(topLeft);
  }
  return GraphLayout.nodeRectAt(topLeft);
}

Rect _envelope(Map<String, Offset> positions, Map<String, SecretaryObject> taskById) {
  return _plainBounds(positions, taskById).inflate(kTaskMapHaloAllowance);
}

Rect _plainBounds(Map<String, Offset> positions, Map<String, SecretaryObject> taskById) {
  var minX = double.infinity;
  var minY = double.infinity;
  var maxX = -double.infinity;
  var maxY = -double.infinity;
  for (final entry in positions.entries) {
    final rect = taskPresentationRect(taskById[entry.key]!, entry.value);
    minX = math.min(minX, rect.left);
    minY = math.min(minY, rect.top);
    maxX = math.max(maxX, rect.right);
    maxY = math.max(maxY, rect.bottom);
  }
  if (minX == double.infinity) {
    return const Rect.fromLTWH(-100, -100, 200, 200);
  }
  return Rect.fromLTRB(minX, minY, maxX, maxY);
}

List<_PlacedComponent> _pack(List<_DraftComponent> drafts) {
  if (drafts.isEmpty) {
    return const [];
  }
  var totalArea = 0.0;
  for (final draft in drafts) {
    totalArea += draft.envelope.width * draft.envelope.height;
  }
  final rowWidth = math.sqrt(totalArea) * kTaskMapPackLandscape;
  final placed = <_PlacedComponent>[];
  var x = 0.0;
  var y = 0.0;
  var rowHeight = 0.0;
  var row = 0;
  var column = 0;
  for (final draft in drafts) {
    final width = draft.envelope.width;
    final height = draft.envelope.height;
    if (column > 0 && x + width > rowWidth) {
      y += rowHeight + kTaskMapComponentGap;
      x = 0;
      rowHeight = 0;
      row += 1;
      column = 0;
    }
    final delta = Offset(x, y) - draft.envelope.topLeft;
    final envelope = draft.envelope.shift(delta);
    placed.add(
      _PlacedComponent(
        draft: draft,
        positions: {
          for (final entry in draft.localPositions.entries) entry.key: entry.value + delta,
        },
        envelope: envelope,
        row: row,
        column: column,
      ),
    );
    x += width + kTaskMapComponentGap;
    rowHeight = math.max(rowHeight, height);
    column += 1;
  }
  return placed;
}

int _maxColumns(List<_PlacedComponent> placed) {
  final counts = <int, int>{};
  for (final item in placed) {
    counts[item.row] = (counts[item.row] ?? 0) + 1;
  }
  return counts.values.fold<int>(0, math.max);
}

int _rectOverlaps(Map<String, Offset> positions, Map<String, SecretaryObject> taskById) {
  final ids = positions.keys.toList()..sort();
  var overlaps = 0;
  for (var i = 0; i < ids.length; i++) {
    final left = taskPresentationRect(taskById[ids[i]]!, positions[ids[i]]!);
    for (var j = i + 1; j < ids.length; j++) {
      final right = taskPresentationRect(taskById[ids[j]]!, positions[ids[j]]!);
      if (left.overlaps(right)) {
        overlaps += 1;
      }
    }
  }
  return overlaps;
}

int _envelopeOverlaps(List<TaskMapComponent> components) {
  var overlaps = 0;
  for (var i = 0; i < components.length; i++) {
    for (var j = i + 1; j < components.length; j++) {
      if (components[i].envelope.overlaps(components[j].envelope)) {
        overlaps += 1;
      }
    }
  }
  return overlaps;
}

Map<String, Set<String>> _undirected(List<SecretaryEdge> edges, Set<String> ids) {
  final adjacency = <String, Set<String>>{for (final id in ids) id: <String>{}};
  for (final edge in edges) {
    if (!ids.contains(edge.sourceId) || !ids.contains(edge.targetId)) {
      continue;
    }
    adjacency[edge.sourceId]!.add(edge.targetId);
    adjacency[edge.targetId]!.add(edge.sourceId);
  }
  return adjacency;
}

List<Set<String>> _components(Set<String> ids, Map<String, Set<String>> adjacency) {
  final ordered = ids.toList()..sort();
  final seen = <String>{};
  final components = <Set<String>>[];
  for (final start in ordered) {
    if (!seen.add(start)) {
      continue;
    }
    final component = <String>{start};
    final stack = <String>[start];
    while (stack.isNotEmpty) {
      final current = stack.removeLast();
      final neighbors = (adjacency[current] ?? const <String>{}).toList()..sort();
      for (final neighbor in neighbors) {
        if (seen.add(neighbor)) {
          component.add(neighbor);
          stack.add(neighbor);
        }
      }
    }
    components.add(component);
  }
  return components;
}
