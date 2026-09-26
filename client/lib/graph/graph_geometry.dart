import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../api/api_models.dart';
import 'graph_layout.dart';

/// Extra space around the current focus neighborhood. Geometry only.
const double kGraphGeometryGuardBand = kGraphNodeWidth;

/// Engine-neutral local refinement input. A later Graphviz adapter can consume
/// the same scene without Secretary models knowing about a layout package.
class GraphGeometryScene {
  const GraphGeometryScene({
    required this.nodes,
    required this.edges,
  });

  final List<GraphGeometryNode> nodes;
  final List<GraphGeometryEdge> edges;

  GraphGeometryNode? nodeById(String id) {
    for (final node in nodes) {
      if (node.id == id) {
        return node;
      }
    }
    return null;
  }
}

class GraphGeometryNode {
  const GraphGeometryNode({
    required this.id,
    required this.width,
    required this.height,
    required this.topLeft,
    required this.fixed,
  });

  final String id;
  final double width;
  final double height;

  /// Current global top-left from [GraphLayout].
  final Offset topLeft;
  final bool fixed;

  Rect get rect => Rect.fromLTWH(topLeft.dx, topLeft.dy, width, height);

  Offset get center => rect.center;
}

class GraphGeometryEdge {
  const GraphGeometryEdge({
    required this.id,
    required this.sourceId,
    required this.targetId,
  });

  final String id;
  final String sourceId;
  final String targetId;
}

class GraphGeometryRoute {
  const GraphGeometryRoute({
    required this.edgeId,
    required this.points,
  });

  final String edgeId;
  final List<Offset> points;
}

/// Normalized refinement. [routes] stays empty when the engine does not route.
class GraphGeometryResult {
  const GraphGeometryResult._({
    required this.completed,
    required this.nodes,
    required this.routes,
    this.error,
  });

  const GraphGeometryResult.success({
    required Map<String, Rect> nodes,
    List<GraphGeometryRoute> routes = const [],
  }) : this._(completed: true, nodes: nodes, routes: routes);

  const GraphGeometryResult.failure(String error)
      : this._(completed: false, nodes: const {}, routes: const [], error: error);

  final bool completed;
  final String? error;
  final Map<String, Rect> nodes;
  final List<GraphGeometryRoute> routes;
}

abstract class GraphGeometryRefiner {
  GraphGeometryResult refine(GraphGeometryScene scene);
}

/// Selected Task, its loaded direct neighbors, and nearby fixed obstacles.
///
/// Returns null when nothing is selected, so the current map stays unchanged.
GraphGeometryScene? buildGraphGeometryScene({
  required List<SecretaryObject> nodes,
  required List<SecretaryEdge> edges,
  required Map<String, Offset> positions,
  required String? selectedObjectId,
  double nodeWidth = kGraphNodeWidth,
  double nodeHeight = kGraphNodeHeight,
  double guardBand = kGraphGeometryGuardBand,
}) {
  if (selectedObjectId == null || !positions.containsKey(selectedObjectId)) {
    return null;
  }
  final byId = {for (final node in nodes) node.id: node};
  final selected = byId[selectedObjectId];
  if (selected == null || selected.kind != 'task') {
    return null;
  }

  final semantic = <String>{selected.id};
  for (final edge in edges) {
    final String? other;
    if (edge.sourceId == selected.id) {
      other = edge.targetId;
    } else if (edge.targetId == selected.id) {
      other = edge.sourceId;
    } else {
      other = null;
    }
    if (other != null && byId.containsKey(other) && positions.containsKey(other)) {
      semantic.add(other);
    }
  }

  Rect rectFor(String id) {
    final topLeft = positions[id]!;
    return Rect.fromLTWH(topLeft.dx, topLeft.dy, nodeWidth, nodeHeight);
  }

  var band = rectFor(selected.id);
  for (final id in semantic) {
    band = band.expandToInclude(rectFor(id));
  }
  band = band.inflate(guardBand);

  final obstacles = <String>[
    for (final node in nodes)
      if (!semantic.contains(node.id) &&
          positions.containsKey(node.id) &&
          rectFor(node.id).overlaps(band))
        node.id,
  ];
  final obstacleIds = obstacles.toSet();
  final sceneIds = <String>{...semantic, ...obstacleIds};
  return GraphGeometryScene(
    nodes: [
      for (final node in nodes)
        if (sceneIds.contains(node.id))
          GraphGeometryNode(
            id: node.id,
            width: nodeWidth,
            height: nodeHeight,
            topLeft: positions[node.id]!,
            fixed: node.id == selected.id || obstacleIds.contains(node.id),
          ),
    ],
    edges: [
      for (final edge in edges)
        if (semantic.contains(edge.sourceId) && semantic.contains(edge.targetId))
          GraphGeometryEdge(
            id: edge.id,
            sourceId: edge.sourceId,
            targetId: edge.targetId,
          ),
    ],
  );
}

/// Copies current positions and replaces only nodes present in a successful result.
Map<String, Offset> applyGraphGeometry({
  required Map<String, Offset> positions,
  required GraphGeometryScene? scene,
  required GraphGeometryRefiner refiner,
}) {
  if (scene == null) {
    return positions;
  }
  final result = refiner.refine(scene);
  if (!result.completed) {
    return positions;
  }
  final display = Map<String, Offset>.from(positions);
  for (final entry in result.nodes.entries) {
    display[entry.key] = entry.value.topLeft;
  }
  return display;
}

({int count, double maxArea}) graphGeometryOverlaps(Iterable<Rect> rects) {
  final items = rects.toList();
  var count = 0;
  var maxArea = 0.0;
  for (var i = 0; i < items.length; i++) {
    for (var j = i + 1; j < items.length; j++) {
      final area = _overlapArea(items[i], items[j]);
      if (area > 0.5) {
        count += 1;
        maxArea = math.max(maxArea, area);
      }
    }
  }
  return (count: count, maxArea: maxArea);
}

/// Straight border-to-border segments, matching the current graph edge painter.
int graphGeometryStraightIntersections({
  required Map<String, Rect> rects,
  required List<GraphGeometryEdge> edges,
}) {
  var count = 0;
  for (final edge in edges) {
    final source = rects[edge.sourceId];
    final target = rects[edge.targetId];
    if (source == null || target == null) {
      continue;
    }
    final ends = GraphLayout.computeEdgeEndpoints(
      sourceCenter: source.center,
      targetCenter: target.center,
      nodeWidth: source.width,
      nodeHeight: source.height,
    );
    for (final entry in rects.entries) {
      if (entry.key == edge.sourceId || entry.key == edge.targetId) {
        continue;
      }
      if (_segmentHitsRect(ends.start, ends.end, entry.value)) {
        count += 1;
      }
    }
  }
  return count;
}

double graphGeometryMaxDisplacement(
  Map<String, Offset> before,
  Map<String, Offset> after,
  Iterable<String> ids,
) {
  var maxDistance = 0.0;
  for (final id in ids) {
    final start = before[id];
    final end = after[id];
    if (start == null || end == null) {
      continue;
    }
    maxDistance = math.max(maxDistance, (end - start).distance);
  }
  return maxDistance;
}

int graphGeometryChangedCount(
  Map<String, Offset> before,
  Map<String, Offset> after,
  Iterable<String> ids, {
  double epsilon = 1,
}) {
  var count = 0;
  for (final id in ids) {
    final start = before[id];
    final end = after[id];
    if (start == null || end == null || (end - start).distance > epsilon) {
      count += 1;
    }
  }
  return count;
}

Map<String, Offset> graphGeometryTopLefts(GraphGeometryResult result) {
  return {for (final entry in result.nodes.entries) entry.key: entry.value.topLeft};
}

Map<String, Offset> graphGeometryInputTopLefts(GraphGeometryScene scene) {
  return {for (final node in scene.nodes) node.id: node.topLeft};
}

double _overlapArea(Rect a, Rect b) {
  final left = math.max(a.left, b.left);
  final right = math.min(a.right, b.right);
  final top = math.max(a.top, b.top);
  final bottom = math.min(a.bottom, b.bottom);
  if (right - left <= 0.5 || bottom - top <= 0.5) {
    return 0;
  }
  return (right - left) * (bottom - top);
}

bool _segmentHitsRect(Offset a, Offset b, Rect rect) {
  if (rect.contains(a) || rect.contains(b)) {
    return true;
  }
  final corners = [rect.topLeft, rect.topRight, rect.bottomRight, rect.bottomLeft];
  for (var index = 0; index < corners.length; index++) {
    if (_segmentsCross(a, b, corners[index], corners[(index + 1) % corners.length])) {
      return true;
    }
  }
  return false;
}

bool _segmentsCross(Offset a, Offset b, Offset c, Offset d) {
  double cross(Offset p, Offset q, Offset r) {
    return (q.dx - p.dx) * (r.dy - p.dy) - (q.dy - p.dy) * (r.dx - p.dx);
  }

  final d1 = cross(c, d, a);
  final d2 = cross(c, d, b);
  final d3 = cross(a, b, c);
  final d4 = cross(a, b, d);
  return ((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) &&
      ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0));
}
