import 'package:flutter/material.dart';

import '../api/api_models.dart';
import 'graph_layout.dart';
import 'hybrid_focus_lod.dart';
import 'task_map_hierarchy.dart';

const String taskLayoutResolutionWarning =
    'Каноническая карта задач не сохранилась. Показан временный обзор этого окна.';

/// Center stored for a Task whose top-left came from [projectTaskMapHierarchy].
/// Hierarchy top-lefts already use the canonical 186×100 card, including ongoing Tasks.
Offset taskLayoutCenterFromTopLeft(Offset topLeft) {
  return topLeft + const Offset(kGraphNodeWidth / 2, kGraphNodeHeight / 2);
}

/// Canonical 186×100 top-left. Hybrid turns an ongoing Task into its circle
/// from this same top-left, so the circle stays centered on the stored center.
Offset taskLayoutCardTopLeft(Offset center) {
  return center - const Offset(kGraphNodeWidth / 2, kGraphNodeHeight / 2);
}

/// Top-left of the widget that is actually drawn for this Task.
Offset taskLayoutDrawnTopLeft(SecretaryObject task, Offset center) {
  final cardTopLeft = taskLayoutCardTopLeft(center);
  if (task.isOngoingTask) {
    return hybridOngoingRect(cardTopLeft).topLeft;
  }
  return cardTopLeft;
}

/// One hierarchy pass over the complete topology. Returns null when a Task
/// has no top-left, so the caller can fail closed instead of persisting a subset.
List<TaskLayoutCenter>? taskLayoutCentersFromTopology(TaskLayoutTopology topology) {
  final projected = projectTaskMapHierarchy(
    nodes: topology.tasks,
    edges: topology.edges,
  );
  if (projected.positions.length != topology.tasks.length) {
    return null;
  }
  final centers = <TaskLayoutCenter>[];
  for (final task in topology.tasks) {
    final topLeft = projected.positions[task.id];
    if (topLeft == null) {
      return null;
    }
    final center = taskLayoutCenterFromTopLeft(topLeft);
    centers.add(
      TaskLayoutCenter(
        taskId: task.id,
        worldX: center.dx,
        worldY: center.dy,
      ),
    );
  }
  return centers;
}

bool taskLayoutSnapshotCovers(TaskLayoutSnapshot snapshot, Iterable<String> taskIds) {
  final covered = snapshot.centers.map((center) => center.taskId).toSet();
  for (final taskId in taskIds) {
    if (!covered.contains(taskId)) {
      return false;
    }
  }
  return snapshot.usable && snapshot.matchesCurrentAlgorithm;
}
