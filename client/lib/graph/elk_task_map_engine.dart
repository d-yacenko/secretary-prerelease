import 'package:elk/elk.dart';
import 'package:flutter/material.dart';

import 'task_map_scene.dart';

/// ELK layered geometry behind [TaskMapLayoutEngine].
///
/// [usePriorPositions] copies scene priors into [ElkNode.x] and [ElkNode.y]
/// and selects [ElkCycleBreaking.interactive]. That public API orders cycle
/// breaking from a previous drawing. It is not a fixed-node constraint.
class ElkTaskMapEngine implements TaskMapLayoutEngine {
  const ElkTaskMapEngine({this.usePriorPositions = false});

  final bool usePriorPositions;

  @override
  TaskMapSceneLayout layout(TaskMapScene scene) {
    try {
      final result = const ElkLayered().layout(_graph(scene));
      final nodes = result.nodesById;
      final routed = <TaskMapRoutedEdge>[];
      for (final edge in scene.edges) {
        ElkPositionedEdge? match;
        for (final candidate in result.edges) {
          if (candidate.id == edge.id) {
            match = candidate;
            break;
          }
        }
        routed.add(
          TaskMapRoutedEdge(
            id: edge.id,
            sourceId: edge.sourceId,
            targetId: edge.targetId,
            sections: [
              if (match != null)
                for (final section in match.sections)
                  [
                    for (final point in section.points) Offset(point.x, point.y),
                  ],
            ],
          ),
        );
      }
      return TaskMapSceneLayout.success(
        nodes: {
          for (final node in scene.nodes)
            if (nodes[node.id] != null)
              node.id: Rect.fromLTWH(
                nodes[node.id]!.x,
                nodes[node.id]!.y,
                nodes[node.id]!.width,
                nodes[node.id]!.height,
              ),
        },
        edges: routed,
      );
    } catch (error) {
      return TaskMapSceneLayout.failure('$error');
    }
  }

  ElkGraph _graph(TaskMapScene scene) {
    final usePriors = usePriorPositions && scene.nodes.any((node) => node.prior != null);
    return ElkGraph(
      layoutOptions: ElkLayoutOptions(
        direction: ElkDirection.down,
        cycleBreaking: usePriors ? ElkCycleBreaking.interactive : ElkCycleBreaking.greedy,
      ),
      children: [
        for (final node in scene.nodes)
          ElkNode(
            id: node.id,
            width: node.width,
            height: node.height,
            x: usePriors ? node.prior?.dx : null,
            y: usePriors ? node.prior?.dy : null,
          ),
      ],
      edges: [
        for (final edge in scene.edges)
          ElkEdge(
            id: edge.id,
            sources: [edge.sourceId],
            targets: [edge.targetId],
          ),
      ],
    );
  }
}
