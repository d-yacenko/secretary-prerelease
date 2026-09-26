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
    required this.hierarchy,
    required this.depth,
    required this.taskIds,
    required this.envelope,
  });

  final String key;
  final bool hierarchy;
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
  int get hierarchyTreeCount =>
      components.where((component) => component.hierarchy).length;
  int get freeComponentCount =>
      components.where((component) => !component.hierarchy).length;
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
    if (edge.type == 'part_of') {
      if (edge.state == 'confirmed') {
        confirmedPartOf.add(edge);
      }
      continue;
    }
    layoutEdges.add(edge);
  }
  confirmedPartOf.sort((a, b) => a.id.compareTo(b.id));

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
  final drafted = <_DraftComponent>[];

  for (final rootId in roots) {
    final memberIds = _treeMembers(rootId, childrenOf, taskById.keys.toSet());
    final centers = <String, Offset>{};
    _placeRadial(
      id: rootId,
      parentId: null,
      rootId: rootId,
      depth: 0,
      radius: 0,
      sectorStart: -math.pi,
      sectorEnd: math.pi,
      origin: Offset.zero,
      taskById: taskById,
      childrenOf: childrenOf,
      baselinePositions: baselinePositions,
      centers: centers,
      placements: placements,
    );
    final positions = {
      for (final id in memberIds) id: _topLeftForCenter(centers[id]!),
    };
    final envelope = _envelope(positions, taskById);
    drafted.add(
      _DraftComponent(
        key: rootId,
        hierarchy: true,
        depth: _maxDepth(memberIds, placements),
        taskIds: memberIds.toList()..sort(),
        localPositions: positions,
        envelope: envelope,
      ),
    );
  }

  final freeIds = taskById.keys.where((id) => !hierarchyIds.contains(id)).toSet();
  final freeAdjacency = _undirected(layoutEdges, freeIds);
  for (final component in _components(freeIds, freeAdjacency)) {
    final componentTasks = [
      for (final id in component) taskById[id]!,
    ];
    final internalEdges = [
      for (final edge in layoutEdges)
        if (component.contains(edge.sourceId) && component.contains(edge.targetId))
          edge,
    ];
    final laid = GraphLayout.computePositions(
      nodes: componentTasks,
      edges: internalEdges,
      rootId: null,
      existing: const {},
      freshRoot: true,
    );
    final key = component.reduce((a, b) => a.compareTo(b) < 0 ? a : b);
    drafted.add(
      _DraftComponent(
        key: key,
        hierarchy: false,
        depth: 0,
        taskIds: component.toList()..sort(),
        localPositions: laid,
        envelope: _envelope(laid, taskById),
      ),
    );
  }

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
        hierarchy: placed.draft.hierarchy,
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
    required this.hierarchy,
    required this.depth,
    required this.taskIds,
    required this.localPositions,
    required this.envelope,
  });

  final String key;
  final bool hierarchy;
  final int depth;
  final List<String> taskIds;
  final Map<String, Offset> localPositions;
  final Rect envelope;
}

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

void _placeRadial({
  required String id,
  required String? parentId,
  required String rootId,
  required int depth,
  required double radius,
  required double sectorStart,
  required double sectorEnd,
  required Offset origin,
  required Map<String, SecretaryObject> taskById,
  required Map<String, List<String>> childrenOf,
  required Map<String, Offset> baselinePositions,
  required Map<String, Offset> centers,
  required Map<String, TaskHierarchyPlacement> placements,
}) {
  final sweep = sectorEnd - sectorStart;
  final angle = sectorStart + sweep / 2;
  final center = origin + Offset(math.cos(angle) * radius, math.sin(angle) * radius);
  centers[id] = center;
  placements[id] = TaskHierarchyPlacement(
    id: id,
    parentId: parentId,
    rootId: rootId,
    depth: depth,
    radius: radius,
    angle: angle,
    sectorStart: sectorStart,
    sectorEnd: sectorEnd,
  );
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
    return;
  }
  final weights = [
    for (final child in children) _subtreeWeight(child, childrenOf),
  ];
  final total = weights.fold<int>(0, (sum, weight) => sum + weight);
  var cursor = sectorStart;
  for (var index = 0; index < children.length; index++) {
    final child = children[index];
    final childSweep = sweep * weights[index] / total;
    final childRadius =
        radius +
        taskCircumradius(taskById[id]!) +
        kTaskMapHierarchyGap +
        taskCircumradius(taskById[child]!);
    _placeRadial(
      id: child,
      parentId: id,
      rootId: rootId,
      depth: depth + 1,
      radius: childRadius,
      sectorStart: cursor,
      sectorEnd: cursor + childSweep,
      origin: origin,
      taskById: taskById,
      childrenOf: childrenOf,
      baselinePositions: baselinePositions,
      centers: centers,
      placements: placements,
    );
    cursor += childSweep;
  }
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

int _subtreeWeight(
  String id,
  Map<String, List<String>> childrenOf, [
  Set<String>? seen,
]) {
  final guard = seen ?? <String>{};
  if (!guard.add(id)) {
    return 0;
  }
  var weight = 1;
  for (final child in childrenOf[id] ?? const <String>[]) {
    weight += _subtreeWeight(child, childrenOf, guard);
  }
  return weight;
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
