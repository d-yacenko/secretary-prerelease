import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../api/api_models.dart';
import '../ui/object_bookmark.dart';
import '../ui/object_visuals.dart';
import 'focus_lod.dart';
import 'graph_geometry.dart';
import 'graph_layout.dart';

/// Compact semantic glyph. Rings stay the V4 start; fCoSE may move the glyph.
const double kHybridGlyphSize = 32;

const double kHybridKindGlyphSize = 24;

const double kHybridProviderMarkSize = 12;

const double kHybridBookmarkMarkSize = 8;

const double kHybridHairlineWidth = 1;

const double kHybridHairlineOpacity = 0.45;

/// Synthetic geometry id for one halo's `+N` mark. Not an object id.
String hybridOverflowId(String anchorTaskId) => 'hybrid-overflow:$anchorTaskId';

class HybridHairline {
  const HybridHairline({
    required this.anchorTaskId,
    required this.markId,
    required this.start,
    required this.end,
  });

  final String anchorTaskId;
  final String markId;
  final Offset start;
  final Offset end;
}

class HybridFocusPresentation {
  const HybridFocusPresentation({
    required this.lod,
    required this.scene,
    required this.result,
    required this.displayTopLeft,
    required this.hairlines,
    this.warning,
  });

  final FocusLodProjection lod;
  final GraphGeometryScene scene;
  final GraphGeometryResult result;

  /// Drawn top-lefts. Tasks and other fixed cards stay on [GraphLayout].
  final Map<String, Offset> displayTopLeft;
  final List<HybridHairline> hairlines;
  final String? warning;

  Offset topLeftFor(String id, Map<String, Offset> graphPositions) {
    return displayTopLeft[id] ?? graphPositions[id] ?? Offset.zero;
  }
}

/// V4 supplies the deterministic start. fCoSE may pack Flow marks only.
///
/// Anchor edges in the geometry scene are presentation springs. They are not
/// ownership and they are not canonical relations.
HybridFocusPresentation presentHybridFocus({
  required List<SecretaryObject> nodes,
  required List<SecretaryEdge> edges,
  required Map<String, Offset> positions,
  required String? selectedObjectId,
  required GraphGeometryRefiner refiner,
  bool Function(String objectId)? isBookmarked,
}) {
  final lod = projectFocusLod(
    nodes: nodes,
    edges: edges,
    positions: positions,
    selectedObjectId: selectedObjectId,
    isBookmarked: isBookmarked,
  );
  final scene = buildHybridGeometryScene(
    nodes: nodes,
    lod: lod,
    positions: positions,
    selectedObjectId: selectedObjectId,
  );
  final result = scene.nodes.isEmpty
      ? const GraphGeometryResult.success(nodes: {})
      : refiner.refine(scene);
  if (!result.completed) {
    return HybridFocusPresentation(
      lod: lod,
      scene: scene,
      result: result,
      displayTopLeft: _startTopLefts(scene),
      hairlines: _hairlines(scene, _startTopLefts(scene)),
      warning: result.error ?? 'Не удалось уточнить гибридную карту fCoSE',
    );
  }
  final display = _startTopLefts(scene);
  for (final node in scene.nodes) {
    if (node.fixed) {
      continue;
    }
    final refined = result.nodes[node.id];
    if (refined == null) {
      return HybridFocusPresentation(
        lod: lod,
        scene: scene,
        result: const GraphGeometryResult.failure('fCoSE omitted a Flow mark'),
        displayTopLeft: _startTopLefts(scene),
        hairlines: _hairlines(scene, _startTopLefts(scene)),
        warning: 'Не удалось уточнить гибридную карту fCoSE',
      );
    }
    display[node.id] = refined.topLeft;
  }
  return HybridFocusPresentation(
    lod: lod,
    scene: scene,
    result: result,
    displayTopLeft: display,
    hairlines: _hairlines(scene, display),
  );
}

GraphGeometryScene buildHybridGeometryScene({
  required List<SecretaryObject> nodes,
  required FocusLodProjection lod,
  required Map<String, Offset> positions,
  required String? selectedObjectId,
}) {
  final byId = {for (final node in nodes) node.id: node};
  final satellites = {for (final item in lod.satellites) item.objectId: item};
  final geometryNodes = <GraphGeometryNode>[];
  final geometryEdges = <GraphGeometryEdge>[];

  for (final node in nodes) {
    final satellite = satellites[node.id];
    if (satellite != null) {
      geometryNodes.add(
        GraphGeometryNode(
          id: node.id,
          width: kHybridGlyphSize,
          height: kHybridGlyphSize,
          topLeft: _glyphTopLeft(satellite.rect.center),
          fixed: false,
        ),
      );
      // Presentation spring only. Not a canonical relation.
      geometryEdges.add(
        GraphGeometryEdge(
          id: 'hybrid-anchor-${node.id}',
          sourceId: satellite.anchorTaskId,
          targetId: node.id,
        ),
      );
      continue;
    }
    if (!lod.fullCardIds.contains(node.id) || !positions.containsKey(node.id)) {
      continue;
    }
    final expandedFlow =
        focusLodKindIsCompactable(node.kind) && node.kind != 'task';
    geometryNodes.add(
      GraphGeometryNode(
        id: node.id,
        width: kGraphNodeWidth,
        height: kGraphNodeHeight,
        topLeft: positions[node.id]!,
        fixed: !expandedFlow,
      ),
    );
    if (expandedFlow &&
        selectedObjectId != null &&
        byId[selectedObjectId]?.kind == 'task') {
      // Presentation spring from the selected Task to its expanded Flow card.
      geometryEdges.add(
        GraphGeometryEdge(
          id: 'hybrid-focus-${node.id}',
          sourceId: selectedObjectId,
          targetId: node.id,
        ),
      );
    }
  }

  for (final overflow in lod.overflows) {
    final id = hybridOverflowId(overflow.anchorTaskId);
    geometryNodes.add(
      GraphGeometryNode(
        id: id,
        width: kHybridGlyphSize,
        height: kHybridGlyphSize,
        topLeft: _glyphTopLeft(overflow.rect.center),
        fixed: false,
      ),
    );
    geometryEdges.add(
      GraphGeometryEdge(
        id: 'hybrid-overflow-edge-${overflow.anchorTaskId}',
        sourceId: overflow.anchorTaskId,
        targetId: id,
      ),
    );
  }

  return GraphGeometryScene(nodes: geometryNodes, edges: geometryEdges);
}

double hybridFixedDrift(HybridFocusPresentation presentation) {
  var maxDrift = 0.0;
  for (final node in presentation.scene.nodes) {
    if (!node.fixed) {
      continue;
    }
    final refined = presentation.result.nodes[node.id];
    if (refined == null) {
      continue;
    }
    final drift = (refined.topLeft - node.topLeft).distance;
    if (drift > maxDrift) {
      maxDrift = drift;
    }
  }
  return maxDrift;
}

class HybridHairlinePainter extends CustomPainter {
  HybridHairlinePainter({
    required this.hairlines,
    required this.bounds,
    required this.padding,
    required this.color,
    required this.dimmed,
  });

  final List<HybridHairline> hairlines;
  final Rect bounds;
  final double padding;
  final Color color;
  final bool dimmed;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = kHybridHairlineWidth
      ..color = color.withValues(
        alpha: kHybridHairlineOpacity * (dimmed ? 0.35 : 1),
      );
    for (final hairline in hairlines) {
      canvas.drawLine(_canvas(hairline.start), _canvas(hairline.end), paint);
    }
  }

  Offset _canvas(Offset graph) {
    return Offset(
      graph.dx - bounds.left + padding,
      graph.dy - bounds.top + padding,
    );
  }

  @override
  bool shouldRepaint(covariant HybridHairlinePainter oldDelegate) => true;
}

class HybridFlowGlyph extends StatelessWidget {
  const HybridFlowGlyph({
    super.key,
    required this.objectId,
    required this.kind,
    required this.title,
    required this.provider,
    required this.bookmarkColor,
    required this.onTap,
  });

  final String objectId;
  final String kind;
  final String title;
  final String? provider;
  final String? bookmarkColor;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final tooltip = [
      title,
      if (provider != null && provider!.trim().isNotEmpty) provider,
    ].join(' · ');
    return Semantics(
      button: true,
      label: title,
      child: Tooltip(
        message: tooltip,
        child: GestureDetector(
          onTap: onTap,
          child: SizedBox(
            width: kHybridGlyphSize,
            height: kHybridGlyphSize,
            child: Stack(
              clipBehavior: Clip.none,
              children: [
                Center(
                  child: Icon(
                    iconForKind(kind),
                    size: kHybridKindGlyphSize,
                    color: scheme.onSurface,
                  ),
                ),
                if (providerHasIdentity(provider))
                  Positioned(
                    right: 0,
                    top: 0,
                    child: ProviderSourceIcon(
                      provider: provider,
                      size: kHybridProviderMarkSize,
                    ),
                  ),
                if (bookmarkColor != null)
                  Positioned(
                    left: 0,
                    bottom: 0,
                    child: Container(
                      key: ValueKey('hybrid-bookmark-$objectId'),
                      width: kHybridBookmarkMarkSize,
                      height: kHybridBookmarkMarkSize,
                      decoration: BoxDecoration(
                        color: bookmarkTokenColor(bookmarkColor!, scheme),
                        shape: BoxShape.circle,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class HybridOverflowGlyph extends StatelessWidget {
  const HybridOverflowGlyph({
    super.key,
    required this.remainder,
    required this.onTap,
  });

  final int remainder;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: SizedBox(
        width: kHybridGlyphSize,
        height: kHybridGlyphSize,
        child: Center(
          child: Text(
            '+$remainder',
            style: Theme.of(context).textTheme.labelSmall,
          ),
        ),
      ),
    );
  }
}

Map<String, Offset> _startTopLefts(GraphGeometryScene scene) {
  return {for (final node in scene.nodes) node.id: node.topLeft};
}

Offset _glyphTopLeft(Offset v4Center) {
  return v4Center - const Offset(kHybridGlyphSize / 2, kHybridGlyphSize / 2);
}

List<HybridHairline> _hairlines(
  GraphGeometryScene scene,
  Map<String, Offset> topLefts,
) {
  final byId = {for (final node in scene.nodes) node.id: node};
  final lines = <HybridHairline>[];
  for (final edge in scene.edges) {
    if (!edge.id.startsWith('hybrid-anchor-') &&
        !edge.id.startsWith('hybrid-overflow-edge-')) {
      continue;
    }
    final anchor = byId[edge.sourceId];
    final mark = byId[edge.targetId];
    final anchorTop = topLefts[edge.sourceId];
    final markTop = topLefts[edge.targetId];
    if (anchor == null ||
        mark == null ||
        anchorTop == null ||
        markTop == null) {
      continue;
    }
    final anchorRect = Rect.fromLTWH(
      anchorTop.dx,
      anchorTop.dy,
      anchor.width,
      anchor.height,
    );
    final markRect = Rect.fromLTWH(
      markTop.dx,
      markTop.dy,
      mark.width,
      mark.height,
    );
    final ends = _borderToBorder(anchorRect, markRect);
    lines.add(
      HybridHairline(
        anchorTaskId: edge.sourceId,
        markId: edge.targetId,
        start: ends.$1,
        end: ends.$2,
      ),
    );
  }
  return lines;
}

(Offset, Offset) _borderToBorder(Rect source, Rect target) {
  final sourceCenter = source.center;
  final targetCenter = target.center;
  return (
    _borderPoint(sourceCenter, targetCenter, source.width, source.height),
    _borderPoint(targetCenter, sourceCenter, target.width, target.height),
  );
}

Offset _borderPoint(Offset center, Offset toward, double width, double height) {
  final dx = toward.dx - center.dx;
  final dy = toward.dy - center.dy;
  if (dx == 0 && dy == 0) {
    return center;
  }
  final scaleX = dx.abs() > 0 ? (width / 2) / dx.abs() : double.infinity;
  final scaleY = dy.abs() > 0 ? (height / 2) / dy.abs() : double.infinity;
  final scale = math.min(scaleX, scaleY);
  return Offset(center.dx + dx * scale, center.dy + dy * scale);
}
