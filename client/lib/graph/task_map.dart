import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:graphview/GraphView.dart';

import '../api/api_models.dart';
import '../ui/domain_labels.dart';
import '../ui/object_dates.dart';

/// Experimental Task Map presentation. The current Graph renderer stays default.
enum TaskMapRenderer { current, experiment, elk, fcose, focusLod, hybrid }

/// GraphView 1.5.1 algorithms used by the V1 spike.
///
/// Mind map is [MindmapAlgorithm]. Radial is [RadialTreeLayoutAlgorithm].
/// Force-directed is [FruchtermanReingoldAlgorithm].
enum TaskMapLayout { mindmap, radial, force }

enum TaskMapDensity { near, middle, far }

const double _nearScale = 1.35;
const double _middleScale = 0.55;

/// Viewport scale only. Membership and Task semantics do not change with zoom.
TaskMapDensity taskMapDensityForScale(double scale) {
  if (scale >= _nearScale) {
    return TaskMapDensity.near;
  }
  if (scale >= _middleScale) {
    return TaskMapDensity.middle;
  }
  return TaskMapDensity.far;
}

class TaskMapProjection {
  const TaskMapProjection({required this.nodes, required this.edges});

  final List<SecretaryObject> nodes;
  final List<SecretaryEdge> edges;
}

/// Task skeleton plus optional already-loaded neighbors of the selected Task.
///
/// Does not invent edges. An edge is kept only when both endpoints stay visible.
TaskMapProjection projectTaskMap({
  required List<SecretaryObject> nodes,
  required List<SecretaryEdge> edges,
  required String? selectedObjectId,
  required bool showContext,
}) {
  final byId = {for (final node in nodes) node.id: node};
  final visible = <String>{
    for (final node in nodes)
      if (node.kind == 'task') node.id,
  };
  final selected = selectedObjectId == null ? null : byId[selectedObjectId];
  if (showContext && selected != null && selected.kind == 'task') {
    for (final edge in edges) {
      final String? other;
      if (edge.sourceId == selected.id) {
        other = edge.targetId;
      } else if (edge.targetId == selected.id) {
        other = edge.sourceId;
      } else {
        other = null;
      }
      final neighbor = other == null ? null : byId[other];
      if (neighbor != null && neighbor.kind != 'task') {
        visible.add(neighbor.id);
      }
    }
  }
  return TaskMapProjection(
    nodes: [
      for (final node in nodes)
        if (visible.contains(node.id)) node,
    ],
    edges: [
      for (final edge in edges)
        if (visible.contains(edge.sourceId) && visible.contains(edge.targetId))
          edge,
    ],
  );
}

class TaskMapNodePresentation {
  const TaskMapNodePresentation({
    required this.title,
    required this.context,
    this.cue,
    this.dueLabel,
  });

  final String title;
  final bool context;
  final String? cue;
  final String? dueLabel;
}

String _clip(String title, int maxChars) {
  final trimmed = title.trim();
  if (trimmed.length <= maxChars) {
    return trimmed;
  }
  return '${trimmed.substring(0, maxChars)}…';
}

String _lifecycleCue(SecretaryObject object) {
  final operational = object.metadata['operational_state'];
  if (operational is String) {
    final label = operationalStateLabel(operational);
    if (label.isNotEmpty) {
      return label;
    }
  }
  return taskStatusLabel(object.status);
}

String _dueCue(SecretaryObject object) {
  final due = object.dueAt;
  if (due == null || due.trim().isEmpty) {
    return '';
  }
  return objectPrimaryDateLabel(object);
}

/// Semantic zoom is presentation only. Context nodes drop detail before Tasks.
TaskMapNodePresentation presentTaskMapNode(
  SecretaryObject object,
  TaskMapDensity density,
) {
  if (object.kind != 'task') {
    switch (density) {
      case TaskMapDensity.near:
        return TaskMapNodePresentation(
          title: _clip(object.title, 32),
          cue: objectKindLabel(object.kind),
          context: true,
        );
      case TaskMapDensity.middle:
        return TaskMapNodePresentation(
          title: _clip(object.title, 18),
          context: true,
        );
      case TaskMapDensity.far:
        return TaskMapNodePresentation(
          title: _clip(object.title, 8),
          context: true,
        );
    }
  }
  final lifecycle = _lifecycleCue(object);
  final due = _dueCue(object);
  switch (density) {
    case TaskMapDensity.near:
      return TaskMapNodePresentation(
        title: object.title,
        cue: lifecycle,
        dueLabel: due.isEmpty ? null : due,
        context: false,
      );
    case TaskMapDensity.middle:
      return TaskMapNodePresentation(
        title: object.title,
        cue: due.isNotEmpty ? due : lifecycle,
        context: false,
      );
    case TaskMapDensity.far:
      return TaskMapNodePresentation(
        title: _clip(object.title, 18),
        context: false,
      );
  }
}

class TaskMapLayoutResult {
  const TaskMapLayoutResult({
    required this.completed,
    required this.positions,
    this.error,
  });

  final bool completed;
  final String? error;
  final Map<String, Offset> positions;
}

const Size kTaskMapProbeNodeSize = Size(160, 64);

/// Runs one GraphView 1.5.1 algorithm on the given nodes and edges.
///
/// Coordinates exist only for this pass. They are not written back to the
/// workspace and are not persisted. A later stable-position strategy can key
/// stored coordinates by object id and seed the next pass from them.
///
/// Mind map and radial layouts recompute a tree from a package-chosen root.
/// Mind map requires an acyclic graph. Nodes outside the chosen tree stay at
/// depth zero and pile onto the root; a new leaf on an existing chain can
/// leave earlier nodes in place, while revealed context or a reversed root
/// moves the field. Radial keeps every supplied node, including cycles via
/// its internal spanning structure, and usually moves the field when
/// membership or root direction changes. Force-directed layout would otherwise
/// start every node at the origin; [_SeededFruchtermanReingoldAlgorithm]
/// places a deterministic ring first. The same membership repeats. Adding a
/// node or revealing context moves that field. Reversing edge direction does
/// not, because this force step treats the seeded ring and attraction as
/// effectively undirected. Coordinates are still discarded after the pass.
TaskMapLayoutResult layoutTaskMap({
  required TaskMapLayout layout,
  required List<SecretaryObject> nodes,
  required List<SecretaryEdge> edges,
}) {
  if (nodes.isEmpty) {
    return const TaskMapLayoutResult(completed: true, positions: {});
  }
  final graph = Graph();
  final byId = <String, Node>{};
  for (final object in nodes) {
    final node = Node.Id(object.id)..size = kTaskMapProbeNodeSize;
    byId[object.id] = node;
    graph.addNode(node);
  }
  for (final edge in edges) {
    final source = byId[edge.sourceId];
    final target = byId[edge.targetId];
    if (source == null || target == null || identical(source, target)) {
      continue;
    }
    graph.addEdge(source, target);
  }
  try {
    final algorithm = taskMapAlgorithm(layout);
    algorithm.setDimensions(1800, 1400);
    algorithm.run(graph, 0, 0);
    return TaskMapLayoutResult(
      completed: true,
      positions: {
        for (final object in nodes) object.id: byId[object.id]!.position,
      },
    );
  } catch (error) {
    return TaskMapLayoutResult(
      completed: false,
      error: error.toString(),
      positions: const {},
    );
  }
}

Algorithm taskMapAlgorithm(TaskMapLayout layout) {
  switch (layout) {
    case TaskMapLayout.mindmap:
      final config = BuchheimWalkerConfiguration()
        ..siblingSeparation = 28
        ..levelSeparation = 64
        ..subtreeSeparation = 36
        ..orientation = BuchheimWalkerConfiguration.ORIENTATION_LEFT_RIGHT;
      return MindmapAlgorithm(config, MindmapEdgeRenderer(config));
    case TaskMapLayout.radial:
      final config = BuchheimWalkerConfiguration()
        ..siblingSeparation = 28
        ..levelSeparation = 72
        ..subtreeSeparation = 36;
      return RadialTreeLayoutAlgorithm(config, null);
    case TaskMapLayout.force:
      return _SeededFruchtermanReingoldAlgorithm(
        FruchtermanReingoldConfiguration(iterations: 40, shuffleNodes: false),
      );
  }
}

/// GraphView starts every node at the origin and only separates them when
/// [FruchtermanReingoldConfiguration.shuffleNodes] is on. That shuffle is
/// unseeded. This subclass places nodes on a deterministic ring first so the
/// same membership lays out the same way, without forking the package.
class _SeededFruchtermanReingoldAlgorithm extends FruchtermanReingoldAlgorithm {
  _SeededFruchtermanReingoldAlgorithm(super.configuration);

  @override
  void init(Graph? graph) {
    final nodes = graph?.nodes ?? const <Node>[];
    final count = nodes.length;
    final radius = math.max(graphWidth, graphHeight) * 0.35;
    for (var index = 0; index < count; index++) {
      final angle = (2 * math.pi * index) / math.max(count, 1);
      nodes[index].position = Offset(
        graphWidth / 2 + math.cos(angle) * radius,
        graphHeight / 2 + math.sin(angle) * radius,
      );
    }
    super.init(graph);
  }
}

int taskMapMovedNodeCount(
  Map<String, Offset> before,
  Map<String, Offset> after, {
  double epsilon = 1,
}) {
  var moved = 0;
  for (final entry in before.entries) {
    final next = after[entry.key];
    if (next != null && (next - entry.value).distance > epsilon) {
      moved += 1;
    }
  }
  return moved;
}
