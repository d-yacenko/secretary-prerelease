import 'package:fcose/fcose.dart' as fcose;
import 'package:flutter/material.dart';

import 'graph_geometry.dart';

/// Local fCoSE configurations. Both are incremental and pin fixed scene nodes.
///
/// Preserve uses the package defaults except the incremental requirements:
/// `randomize: false`, `quality: proof`, and `seed: 1`. Upstream fCoSE
/// documents that a non-random start uses proof quality. Relax changes only
/// `idealEdgeLength` from the default 50 to 90 so movable neighbors can sit
/// farther apart on the same pins. No other force is searched.
enum FcoseRefinementMode { preserve, relax }

class FcoseGraphRefiner implements GraphGeometryRefiner {
  const FcoseGraphRefiner({this.mode = FcoseRefinementMode.preserve});

  final FcoseRefinementMode mode;

  @override
  GraphGeometryResult refine(GraphGeometryScene scene) {
    try {
      final graph = fcose.FcoseGraph(
        nodes: [
          for (final node in scene.nodes)
            fcose.FcoseNode(
              id: node.id,
              width: node.width,
              height: node.height,
              position: fcose.Offset(node.center.dx, node.center.dy),
            ),
        ],
        edges: [
          for (final edge in scene.edges)
            fcose.FcoseEdge(
              id: edge.id,
              source: edge.sourceId,
              target: edge.targetId,
            ),
        ],
      );
      final result = fcose.FcoseLayout(options: _options(scene)).run(graph);
      final rects = <String, Rect>{};
      for (final node in scene.nodes) {
        final center = result.positions[node.id];
        if (center == null) {
          return GraphGeometryResult.failure('fCoSE omitted ${node.id}');
        }
        rects[node.id] = Rect.fromCenter(
          center: Offset(center.x, center.y),
          width: node.width,
          height: node.height,
        );
      }
      return GraphGeometryResult.success(nodes: rects);
    } catch (error) {
      return GraphGeometryResult.failure('$error');
    }
  }

  fcose.FcoseOptions _options(GraphGeometryScene scene) {
    return fcose.FcoseOptions(
      randomize: false,
      quality: fcose.LayoutQuality.proof,
      seed: 1,
      idealEdgeLength: mode == FcoseRefinementMode.relax ? 90 : 50,
      fixedNodes: [
        for (final node in scene.nodes)
          if (node.fixed)
            fcose.FixedNodeConstraint(
              node.id,
              fcose.Offset(node.center.dx, node.center.dy),
            ),
      ],
    );
  }
}
