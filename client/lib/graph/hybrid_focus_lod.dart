import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../api/api_models.dart';
import '../ui/object_bookmark.dart';
import '../ui/object_dates.dart';
import '../ui/object_visuals.dart';
import 'focus_lod.dart';
import 'graph_geometry.dart';
import 'graph_layout.dart';
import 'graph_map_edge_presentation.dart';

/// Compact semantic glyph. Hybrid rings use this size, not the V4 24 px mark.
const double kHybridGlyphSize = 32;

const double kHybridKindGlyphSize = 24;

const double kHybridProviderMarkSize = 12;

const double kHybridBookmarkMarkSize = 8;

const double kHybridHairlineWidth = 1;

const double kHybridHairlineOpacity = 0.45;

/// Medium selected-flower card. Not the global 186×100 graph card.
const double kHybridFocusedCardWidth = 156;

const double kHybridFocusedCardHeight = 76;

/// Circular ongoing-task anchor. Centered on the canonical 186×100 Task center.
const double kHybridOngoingSize = 144;

Rect hybridOngoingRect(Offset canonicalTopLeft) {
  return Rect.fromCenter(
    center:
        canonicalTopLeft +
        const Offset(kGraphNodeWidth / 2, kGraphNodeHeight / 2),
    width: kHybridOngoingSize,
    height: kHybridOngoingSize,
  );
}

const double _focusedGap = 8;
const int _focusedSlots = 8;
const int kHybridCompactNominalSlots = 12;
const double kHybridCompactGap = 4;

/// Half of the 8-slot 45° focused reference.
const double kHybridFocusedOwnRayRadians = math.pi / 8;

/// Quarter of the 8-slot 45° focused reference.
const double kHybridFocusedMinSeparationRadians = math.pi / 16;

/// The 12-slot 30° compact reference.
const double kHybridCompactOwnRayRadians = math.pi / 6;

/// Synthetic geometry id for one halo's `+N` mark. Not an object id.
String hybridOverflowId(String anchorTaskId) => 'hybrid-overflow:$anchorTaskId';

class HybridHairline {
  const HybridHairline({
    required this.anchorTaskId,
    required this.markId,
    required this.start,
    required this.end,
    this.directed = false,
    this.arrowAtMark = false,
    this.proposed = false,
    this.dashed = false,
  });

  final String anchorTaskId;
  final String markId;
  final Offset start;
  final Offset end;

  /// Canonical source -> target arrow. Overflow marks stay undirected.
  final bool directed;

  /// When directed, the arrow sits on the Flow mark. Otherwise it sits on the Task.
  final bool arrowAtMark;

  /// Review state. Does not change direction or dash.
  final bool proposed;

  /// `depends_on` stays dashed when collapsed.
  final bool dashed;
}

class HybridFocusPresentation {
  const HybridFocusPresentation({
    required this.lod,
    required this.scene,
    required this.result,
    required this.displayTopLeft,
    required this.hairlines,
    this.warning,
    this.topologyNote,
  });

  final FocusLodProjection lod;
  final GraphGeometryScene scene;
  final GraphGeometryResult result;

  /// Drawn top-lefts. Tasks and other fixed cards stay on [GraphLayout].
  final Map<String, Offset> displayTopLeft;
  final List<HybridHairline> hairlines;

  /// Genuine refinement failure. Ordinary topology fallback is [topologyNote].
  final String? warning;
  final String? topologyNote;

  Offset topLeftFor(String id, Map<String, Offset> graphPositions) {
    return displayTopLeft[id] ?? graphPositions[id] ?? Offset.zero;
  }
}

/// V4 halo starts for compact marks. Focused Flow starts on a local ring.
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
  final selected = selectedObjectId == null
      ? null
      : nodes.where((node) => node.id == selectedObjectId).firstOrNull;
  final lod = projectFocusLod(
    nodes: nodes,
    edges: edges,
    positions: positions,
    selectedObjectId: selectedObjectId,
    isBookmarked: isBookmarked,
    expandSelectedFlow: selected == null || !selected.isOngoingTask,
    taskObstacleRects: {
      for (final node in nodes)
        if (node.kind == 'task' && positions.containsKey(node.id))
          node.id: node.isOngoingTask
              ? hybridOngoingRect(positions[node.id]!)
              : GraphLayout.nodeRectAt(positions[node.id]!),
    },
  );
  final scene = buildHybridGeometryScene(
    nodes: nodes,
    edges: edges,
    lod: lod,
    positions: positions,
    selectedObjectId: selectedObjectId,
    isBookmarked: isBookmarked,
  );
  final display = _startTopLefts(scene);
  final merged = <String, Rect>{};
  String? warning;
  String? topologyNote;

  final focused = [
    for (final node in scene.nodes)
      if (node.width == kHybridFocusedCardWidth) node,
  ];
  if (focused.isNotEmpty) {
    final pass = GraphGeometryScene(
      nodes: [
        for (final node in scene.nodes)
          if (node.fixed || node.width == kHybridFocusedCardWidth) node,
      ],
      edges: [
        for (final edge in scene.edges)
          if (edge.id.startsWith('hybrid-focus-')) edge,
      ],
    );
    final result = refiner.refine(pass);
    if (!result.completed) {
      return _fallback(lod, scene, result, nodes, edges);
    }
    merged.addAll(result.nodes);
    if (_focusedPassAccepted(
      taskId: selectedObjectId,
      scene: scene,
      focused: focused,
      result: result,
    )) {
      for (final node in focused) {
        display[node.id] = result.nodes[node.id]!.topLeft;
      }
    } else if (focused.any((node) => result.nodes[node.id] == null)) {
      return _fallback(
        lod,
        scene,
        const GraphGeometryResult.failure('fCoSE omitted a focused Flow card'),
        nodes,
        edges,
      );
    } else {
      topologyNote = 'Локальное соцветие оставлено на стартовых позициях';
    }
  }

  final compact = [
    for (final node in scene.nodes)
      if (node.width == kHybridGlyphSize) node,
  ];
  if (compact.isNotEmpty) {
    final pass = GraphGeometryScene(
      nodes: [
        for (final node in scene.nodes)
          if (node.width != kHybridGlyphSize)
            GraphGeometryNode(
              id: node.id,
              width: node.width,
              height: node.height,
              topLeft: display[node.id] ?? node.topLeft,
              fixed: true,
            )
          else
            node,
      ],
      edges: [
        for (final edge in scene.edges)
          if (!edge.id.startsWith('hybrid-focus-')) edge,
      ],
    );
    final result = refiner.refine(pass);
    if (!result.completed) {
      warning ??= result.error ?? 'Не удалось уточнить компактные гало';
    } else if (_compactPassAccepted(
      scene: scene,
      compact: compact,
      result: result,
      display: display,
    )) {
      merged.addAll(result.nodes);
      for (final node in compact) {
        display[node.id] = result.nodes[node.id]!.topLeft;
      }
    } else {
      topologyNote ??= 'Компактные гало оставлены на сбалансированных позициях';
    }
  }

  return HybridFocusPresentation(
    lod: lod,
    scene: scene,
    result: GraphGeometryResult.success(nodes: merged),
    displayTopLeft: display,
    hairlines: _semanticHairlines(scene, display, nodes, edges),
    warning: warning,
    topologyNote: topologyNote,
  );
}

HybridFocusPresentation _fallback(
  FocusLodProjection lod,
  GraphGeometryScene scene,
  GraphGeometryResult result,
  List<SecretaryObject> nodes,
  List<SecretaryEdge> edges,
) {
  final starts = _startTopLefts(scene);
  return HybridFocusPresentation(
    lod: lod,
    scene: scene,
    result: result,
    displayTopLeft: starts,
    hairlines: _semanticHairlines(scene, starts, nodes, edges),
    warning: result.error ?? 'Не удалось уточнить гибридную карту fCoSE',
  );
}

GraphGeometryScene buildHybridGeometryScene({
  required List<SecretaryObject> nodes,
  required List<SecretaryEdge> edges,
  required FocusLodProjection lod,
  required Map<String, Offset> positions,
  required String? selectedObjectId,
  bool Function(String objectId)? isBookmarked,
}) {
  final byId = {for (final node in nodes) node.id: node};
  final satellites = {for (final item in lod.satellites) item.objectId: item};
  final bookmarked = isBookmarked ?? (_) => false;
  final focusedStarts = _focusedStarts(
    nodes: nodes,
    lod: lod,
    positions: positions,
    selectedObjectId: selectedObjectId,
    bookmarked: bookmarked,
  );
  final compactStarts = _balancedCompactStarts(
    nodes: nodes,
    edges: edges,
    lod: lod,
    positions: positions,
    bookmarked: bookmarked,
    focusedStarts: focusedStarts,
  );
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
          topLeft:
              compactStarts[node.id] ??
              (satellite.rect.center -
                  const Offset(kHybridGlyphSize / 2, kHybridGlyphSize / 2)),
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
    final ongoing = node.isOngoingTask;
    final focusedTopLeft = focusedStarts[node.id];
    geometryNodes.add(
      GraphGeometryNode(
        id: node.id,
        width: expandedFlow
            ? kHybridFocusedCardWidth
            : ongoing
            ? kHybridOngoingSize
            : kGraphNodeWidth,
        height: expandedFlow
            ? kHybridFocusedCardHeight
            : ongoing
            ? kHybridOngoingSize
            : kGraphNodeHeight,
        topLeft: expandedFlow
            ? (focusedTopLeft ?? positions[node.id]!)
            : ongoing
            ? hybridOngoingRect(positions[node.id]!).topLeft
            : positions[node.id]!,
        fixed: !expandedFlow,
      ),
    );
    if (expandedFlow &&
        selectedObjectId != null &&
        byId[selectedObjectId]?.kind == 'task') {
      // Presentation spring from the selected Task to its local Flow card.
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
        topLeft:
            compactStarts[id] ??
            (overflow.rect.center -
                const Offset(kHybridGlyphSize / 2, kHybridGlyphSize / 2)),
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

/// Center distance past which the whole focused flower returns to its rings.
double hybridFocusedLocalityLimit(int count) {
  if (count <= 0) {
    return 0;
  }
  final lastRing = (count - 1) ~/ _focusedSlots;
  final onRing = math.min(count, _focusedSlots);
  final span = _markSpan(
    kHybridFocusedCardWidth,
    kHybridFocusedCardHeight,
    _focusedGap,
  );
  final angular = onRing <= 1 ? 0.0 : span / (2 * math.sin(math.pi / onRing));
  return math.max(_focusedBaseRadius(), angular) + (lastRing + 1) * span;
}

double _markSpan(double width, double height, double gap) {
  return math.sqrt(width * width + height * height) + gap;
}

Rect hybridPresentationBounds(HybridFocusPresentation presentation) {
  if (presentation.scene.nodes.isEmpty) {
    return const Rect.fromLTWH(-100, -100, 200, 200);
  }
  var minX = double.infinity;
  var minY = double.infinity;
  var maxX = -double.infinity;
  var maxY = -double.infinity;
  for (final node in presentation.scene.nodes) {
    final top = presentation.displayTopLeft[node.id] ?? node.topLeft;
    minX = math.min(minX, top.dx);
    minY = math.min(minY, top.dy);
    maxX = math.max(maxX, top.dx + node.width);
    maxY = math.max(maxY, top.dy + node.height);
  }
  return Rect.fromLTRB(minX, minY, maxX, maxY);
}

Matrix4 hybridFitTransform({
  required Rect graphBounds,
  required Size viewportSize,
  double padding = kGraphCanvasPadding,
}) {
  if (viewportSize.isEmpty ||
      graphBounds.width <= 0 ||
      graphBounds.height <= 0) {
    return Matrix4.identity();
  }
  final scaleX = (viewportSize.width - padding * 2) / graphBounds.width;
  final scaleY = (viewportSize.height - padding * 2) / graphBounds.height;
  final scale = math.min(scaleX, scaleY).clamp(kGraphMinScale, kGraphMaxScale);
  final centerX = padding + graphBounds.width / 2;
  final centerY = padding + graphBounds.height / 2;
  return Matrix4.identity()
    ..translateByDouble(viewportSize.width / 2, viewportSize.height / 2, 0, 1)
    ..scaleByDouble(scale, scale, 1, 1)
    ..translateByDouble(-centerX, -centerY, 0, 1);
}

class HybridHairlinePainter extends CustomPainter {
  HybridHairlinePainter({
    required this.hairlines,
    required this.bounds,
    required this.padding,
    required this.color,
    required this.dimmed,
    this.proposalColor,
  });

  final List<HybridHairline> hairlines;
  final Rect bounds;
  final double padding;
  final Color color;
  final Color? proposalColor;
  final bool dimmed;

  @override
  void paint(Canvas canvas, Size size) {
    for (final hairline in hairlines) {
      final proposed = hairline.proposed;
      final paint = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = proposed ? kProposedHairlineStroke : kHybridHairlineWidth
        ..color = proposed
            ? (proposalColor ?? color).withValues(
                alpha: proposedRelationOpacity(dimmed: dimmed),
              )
            : color.withValues(
                alpha: kHybridHairlineOpacity * (dimmed ? 0.35 : 1),
              );
      final start = _canvas(hairline.start);
      final end = _canvas(hairline.end);
      if (hairline.dashed) {
        _drawDashed(canvas, start, end, paint);
      } else {
        canvas.drawLine(start, end, paint);
      }
      if (proposed) {
        paintRelationDiamond(
          canvas,
          relationSegmentMidpoint(start, end),
          kProposedHairlineDiamond,
          paint,
        );
      }
      if (!hairline.directed) {
        continue;
      }
      final tip = hairline.arrowAtMark ? end : start;
      final from = hairline.arrowAtMark ? start : end;
      _drawHairlineArrow(canvas, tip, from, paint);
    }
  }

  void _drawDashed(Canvas canvas, Offset start, Offset end, Paint paint) {
    const dash = 5.0;
    const gap = 3.0;
    final delta = end - start;
    final length = delta.distance;
    if (length == 0) {
      return;
    }
    final direction = delta / length;
    var drawn = 0.0;
    while (drawn < length) {
      final next = math.min(drawn + dash, length);
      canvas.drawLine(start + direction * drawn, start + direction * next, paint);
      drawn = next + gap;
    }
  }

  void _drawHairlineArrow(Canvas canvas, Offset tip, Offset from, Paint paint) {
    final angle = math.atan2(tip.dy - from.dy, tip.dx - from.dx);
    const arrow = 6.0;
    final left = Offset(
      tip.dx - arrow * math.cos(angle - 0.45),
      tip.dy - arrow * math.sin(angle - 0.45),
    );
    final right = Offset(
      tip.dx - arrow * math.cos(angle + 0.45),
      tip.dy - arrow * math.sin(angle + 0.45),
    );
    final path = Path()
      ..moveTo(tip.dx, tip.dy)
      ..lineTo(left.dx, left.dy)
      ..lineTo(right.dx, right.dy)
      ..close();
    canvas.drawPath(path, Paint.from(paint)..style = PaintingStyle.fill);
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

class HybridFocusedFlowCard extends StatelessWidget {
  const HybridFocusedFlowCard({
    super.key,
    required this.object,
    required this.selected,
    required this.focusDimmed,
    required this.bookmarkColor,
    required this.onTap,
  });

  final SecretaryObject object;
  final bool selected;
  final bool focusDimmed;
  final String? bookmarkColor;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final date = objectPrimaryDateLabel(object);
    final card = Material(
      elevation: selected ? 3 : 1,
      color: selected ? scheme.primaryContainer : scheme.surface,
      borderRadius: BorderRadius.circular(10),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(10),
        child: Container(
          width: kHybridFocusedCardWidth,
          height: kHybridFocusedCardHeight,
          padding: const EdgeInsets.fromLTRB(8, 6, 8, 6),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(10),
            border: Border.all(
              color: selected ? scheme.primary : scheme.outlineVariant,
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(iconForKind(object.kind), size: 16),
                  const SizedBox(width: 4),
                  if (providerHasIdentity(object.provider))
                    providerBadge(context, object.provider),
                  const Spacer(),
                  if (bookmarkColor != null)
                    Container(
                      key: ValueKey('hybrid-focus-bookmark-${object.id}'),
                      width: kHybridBookmarkMarkSize,
                      height: kHybridBookmarkMarkSize,
                      decoration: BoxDecoration(
                        color: bookmarkTokenColor(bookmarkColor!, scheme),
                        shape: BoxShape.circle,
                      ),
                    ),
                ],
              ),
              Expanded(
                child: Text(
                  object.title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ),
              if (date.isNotEmpty)
                Text(
                  date,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.labelSmall,
                ),
            ],
          ),
        ),
      ),
    );
    if (!focusDimmed) {
      return card;
    }
    return Opacity(opacity: 0.35, child: card);
  }
}

class HybridOngoingTaskNode extends StatelessWidget {
  const HybridOngoingTaskNode({
    super.key,
    required this.object,
    required this.selected,
    required this.focusDimmed,
    required this.bookmarkColor,
    required this.onTap,
  });

  final SecretaryObject object;
  final bool selected;
  final bool focusDimmed;
  final String? bookmarkColor;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final node = Material(
      color: selected ? scheme.primaryContainer : scheme.secondaryContainer,
      elevation: selected ? 4 : 2,
      shape: CircleBorder(
        side: BorderSide(
          color: selected ? scheme.primary : scheme.outline,
          width: selected ? 2.5 : 2,
        ),
      ),
      child: InkWell(
        customBorder: const CircleBorder(),
        onTap: onTap,
        child: SizedBox(
          width: kHybridOngoingSize,
          height: kHybridOngoingSize,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(
                  Icons.all_inclusive,
                  key: ValueKey('hybrid-ongoing-${object.id}'),
                ),
                Text(
                  'Направление',
                  style: Theme.of(context).textTheme.labelSmall,
                ),
                Text(
                  object.title,
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                if (bookmarkColor != null)
                  Container(
                    key: ValueKey('hybrid-ongoing-bookmark-${object.id}'),
                    width: kHybridBookmarkMarkSize,
                    height: kHybridBookmarkMarkSize,
                    decoration: BoxDecoration(
                      color: bookmarkTokenColor(bookmarkColor!, scheme),
                      shape: BoxShape.circle,
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
    if (!focusDimmed) {
      return node;
    }
    return Opacity(opacity: 0.35, child: node);
  }
}

Map<String, Offset> _focusedStarts({
  required List<SecretaryObject> nodes,
  required FocusLodProjection lod,
  required Map<String, Offset> positions,
  required String? selectedObjectId,
  required bool Function(String objectId) bookmarked,
}) {
  if (selectedObjectId == null || !positions.containsKey(selectedObjectId)) {
    return const {};
  }
  final selected = nodes
      .where((node) => node.id == selectedObjectId)
      .firstOrNull;
  if (selected == null || selected.kind != 'task') {
    return const {};
  }
  final focused = [
    for (final node in nodes)
      if (lod.fullCardIds.contains(node.id) &&
          focusLodKindIsCompactable(node.kind) &&
          !lod.satellites.any((item) => item.objectId == node.id))
        node,
  ]..sort((left, right) => _focusOrder(left, right, bookmarked));
  final occupied = <Rect>[
    for (final node in nodes)
      if (node.kind == 'task' && positions.containsKey(node.id))
        node.isOngoingTask
            ? hybridOngoingRect(positions[node.id]!)
            : GraphLayout.nodeRectAt(positions[node.id]!),
  ];
  final anchor = positions[selectedObjectId]!;
  final anchorCenter = Offset(
    anchor.dx + kGraphNodeWidth / 2,
    anchor.dy + kGraphNodeHeight / 2,
  );
  final placed = _placeBalanced(
    anchorCenter: anchorCenter,
    anchorHalfWidth: kGraphNodeWidth / 2,
    anchorHalfHeight: kGraphNodeHeight / 2,
    count: focused.length,
    markWidth: kHybridFocusedCardWidth,
    markHeight: kHybridFocusedCardHeight,
    gap: _focusedGap,
    nominalSlots: _focusedSlots,
    blocked: occupied,
  );
  return {
    for (var index = 0; index < focused.length; index++)
      focused[index].id: placed[index].topLeft,
  };
}

Map<String, Offset> _balancedCompactStarts({
  required List<SecretaryObject> nodes,
  required List<SecretaryEdge> edges,
  required FocusLodProjection lod,
  required Map<String, Offset> positions,
  required bool Function(String objectId) bookmarked,
  required Map<String, Offset> focusedStarts,
}) {
  final byId = {for (final node in nodes) node.id: node};
  final grouped = <String, List<SecretaryObject>>{};
  for (final satellite in lod.satellites) {
    final object = byId[satellite.objectId];
    if (object == null) {
      continue;
    }
    grouped.putIfAbsent(satellite.anchorTaskId, () => []).add(object);
  }
  final anchors = grouped.keys.toList()..sort();
  for (final overflow in lod.overflows) {
    anchors.add(overflow.anchorTaskId);
  }
  final orderedAnchors = anchors.toSet().toList()..sort();
  final blocked = <Rect>[
    for (final node in nodes)
      if (node.kind == 'task' && positions.containsKey(node.id))
        node.isOngoingTask
            ? hybridOngoingRect(positions[node.id]!)
            : GraphLayout.nodeRectAt(positions[node.id]!),
    for (final entry in focusedStarts.entries)
      Rect.fromLTWH(
        entry.value.dx,
        entry.value.dy,
        kHybridFocusedCardWidth,
        kHybridFocusedCardHeight,
      ),
  ];
  final starts = <String, Offset>{};
  for (final anchorId in orderedAnchors) {
    final task = byId[anchorId];
    final topLeft = positions[anchorId];
    if (task == null || topLeft == null) {
      continue;
    }
    final members = [...?grouped[anchorId]]
      ..sort((left, right) => _focusOrder(left, right, bookmarked));
    final overflow = lod.overflows
        .where((item) => item.anchorTaskId == anchorId)
        .firstOrNull;
    final count = members.length + (overflow == null ? 0 : 1);
    final anchorRect = task.isOngoingTask
        ? hybridOngoingRect(topLeft)
        : GraphLayout.nodeRectAt(topLeft);
    final placed = _placeBalanced(
      anchorCenter: anchorRect.center,
      anchorHalfWidth: anchorRect.width / 2,
      anchorHalfHeight: anchorRect.height / 2,
      count: count,
      markWidth: kHybridGlyphSize,
      markHeight: kHybridGlyphSize,
      gap: kHybridCompactGap,
      nominalSlots: kHybridCompactNominalSlots,
      blocked: blocked,
      reservedRays: _visibleTaskRays(
        anchorId: anchorId,
        anchorCenter: anchorRect.center,
        edges: edges,
        byId: byId,
        positions: positions,
      ),
    );
    for (var index = 0; index < members.length; index++) {
      starts[members[index].id] = placed[index].topLeft;
      blocked.add(placed[index]);
    }
    if (overflow != null) {
      final rect = placed[members.length];
      starts[hybridOverflowId(anchorId)] = rect.topLeft;
      blocked.add(rect);
    }
  }
  return starts;
}

class _PlannedSlot {
  const _PlannedSlot(this.ring, this.angle, this.slotAngle);

  final int ring;
  final double angle;
  final double slotAngle;
}

List<Rect> _placeBalanced({
  required Offset anchorCenter,
  required double anchorHalfWidth,
  required double anchorHalfHeight,
  required int count,
  required double markWidth,
  required double markHeight,
  required double gap,
  required int nominalSlots,
  required List<Rect> blocked,
  List<double> reservedRays = const [],
}) {
  if (count <= 0) {
    return const [];
  }
  final base = math.sqrt(
    math.pow(anchorHalfWidth + markWidth / 2 + gap, 2) +
        math.pow(anchorHalfHeight + markHeight / 2 + gap, 2),
  );
  final step = _markSpan(markWidth, markHeight, gap);
  final reserved = [...blocked];
  final placed = <Rect>[];
  for (final slot in _balancedPlan(count, nominalSlots)) {
    final rect = _resolveBalancedSlot(
      slot: slot,
      nominalSlots: nominalSlots,
      anchorCenter: anchorCenter,
      base: base,
      step: step,
      gap: gap,
      markWidth: markWidth,
      markHeight: markHeight,
      blocked: reserved,
      reservedRays: reservedRays,
    );
    placed.add(rect);
    reserved.add(rect);
  }
  return placed;
}

List<_PlannedSlot> _balancedPlan(int count, int nominalSlots) {
  if (count <= nominalSlots) {
    final slotAngle = 2 * math.pi / count;
    return [
      for (var index = 0; index < count; index++)
        _PlannedSlot(0, -math.pi / 2 + index * slotAngle, slotAngle),
    ];
  }
  final slotAngle = 2 * math.pi / nominalSlots;
  final plan = <_PlannedSlot>[];
  var phase = -math.pi / 2;
  var left = count;
  var ring = 0;
  while (left > 0) {
    final onRing = math.min(left, nominalSlots);
    for (var index = 0; index < onRing; index++) {
      plan.add(_PlannedSlot(ring, phase + index * slotAngle, slotAngle));
    }
    phase += slotAngle / 2;
    left -= onRing;
    ring += 1;
  }
  return plan;
}

Rect _resolveBalancedSlot({
  required _PlannedSlot slot,
  required int nominalSlots,
  required Offset anchorCenter,
  required double base,
  required double step,
  required double gap,
  required double markWidth,
  required double markHeight,
  required List<Rect> blocked,
  List<double> reservedRays = const [],
}) {
  final nominal = 2 * math.pi / nominalSlots;
  final onRing = math.max(1, (2 * math.pi / slot.slotAngle).round());
  final neighbor = _markSpan(markWidth, markHeight, gap);
  final angular = onRing <= 1
      ? 0.0
      : neighbor / (2 * math.sin(math.pi / onRing));
  for (var extra = 0; extra < 12; extra++) {
    final radius = math.max(base, angular) + (slot.ring + extra) * step;
    final shift = extra * (nominal / 2);
    for (final angle in _ringSweep(slot.angle + shift, slot.slotAngle)) {
      final rect = Rect.fromCenter(
        center: Offset(
          anchorCenter.dx + math.cos(angle) * radius,
          anchorCenter.dy + math.sin(angle) * radius,
        ),
        width: markWidth,
        height: markHeight,
      );
      if (!_hits(rect, blocked) && !_inReservedRay(angle, reservedRays)) {
        return rect;
      }
    }
  }
  final fallbackRadius = math.max(base, angular) + (slot.ring + 12) * step;
  return Rect.fromCenter(
    center: Offset(
      anchorCenter.dx + math.cos(slot.angle) * fallbackRadius,
      anchorCenter.dy + math.sin(slot.angle) * fallbackRadius,
    ),
    width: markWidth,
    height: markHeight,
  );
}

List<double> _ringSweep(double preferred, double slotAngle) {
  final step = math.max(slotAngle / 12, 2 * math.pi / 96);
  final turns = (2 * math.pi / step).ceil();
  final angles = <double>[preferred];
  for (var k = 1; k <= turns; k++) {
    angles.add(preferred + step * k);
    angles.add(preferred - step * k);
  }
  return angles;
}

int _focusOrder(
  SecretaryObject left,
  SecretaryObject right,
  bool Function(String objectId) bookmarked,
) {
  final leftMark = bookmarked(left.id);
  final rightMark = bookmarked(right.id);
  if (leftMark != rightMark) {
    return leftMark ? -1 : 1;
  }
  final recency = right.updatedAt.compareTo(left.updatedAt);
  if (recency != 0) {
    return recency;
  }
  return left.id.compareTo(right.id);
}

bool _hits(Rect rect, List<Rect> others) {
  for (final other in others) {
    final left = math.max(rect.left, other.left);
    final right = math.min(rect.right, other.right);
    final top = math.max(rect.top, other.top);
    final bottom = math.min(rect.bottom, other.bottom);
    if (right - left > 0.5 && bottom - top > 0.5) {
      return true;
    }
  }
  return false;
}

double _focusedBaseRadius() {
  return math.sqrt(
    math.pow(
          kGraphNodeWidth / 2 + kHybridFocusedCardWidth / 2 + _focusedGap,
          2,
        ) +
        math.pow(
          kGraphNodeHeight / 2 + kHybridFocusedCardHeight / 2 + _focusedGap,
          2,
        ),
  );
}

bool _focusedPassAccepted({
  required String? taskId,
  required GraphGeometryScene scene,
  required List<GraphGeometryNode> focused,
  required GraphGeometryResult result,
}) {
  if (taskId == null || focused.isEmpty) {
    return true;
  }
  final task = scene.nodeById(taskId);
  if (task == null) {
    return false;
  }
  final refined = <Rect>[];
  final starts = <Rect>[];
  final limit = hybridFocusedLocalityLimit(focused.length);
  for (final node in focused) {
    final next = result.nodes[node.id];
    if (next == null) {
      return false;
    }
    if ((next.center - task.center).distance > limit) {
      return false;
    }
    final drift = _angleDelta(
      _rayAngle(task.center, node.center),
      _rayAngle(task.center, next.center),
    );
    if (drift > kHybridFocusedOwnRayRadians + 1e-6) {
      return false;
    }
    refined.add(next);
    starts.add(node.rect);
  }
  if (focused.length > 1 &&
      _minAngularGap(task.center, refined) + 1e-6 <
          kHybridFocusedMinSeparationRadians) {
    return false;
  }
  final obstacles = [
    for (final node in scene.nodes)
      if (node.fixed) node.rect,
  ];
  return _overlapCount(refined, refined) <= _overlapCount(starts, starts) &&
      _overlapCount(refined, obstacles) <= _overlapCount(starts, obstacles);
}

bool _compactPassAccepted({
  required GraphGeometryScene scene,
  required List<GraphGeometryNode> compact,
  required GraphGeometryResult result,
  required Map<String, Offset> display,
}) {
  final anchors = <String, String>{};
  for (final edge in scene.edges) {
    if (edge.id.startsWith('hybrid-anchor-') ||
        edge.id.startsWith('hybrid-overflow-edge-')) {
      anchors[edge.targetId] = edge.sourceId;
    }
  }
  final byAnchor = <String, List<GraphGeometryNode>>{};
  final refined = <Rect>[];
  final starts = <Rect>[];
  for (final node in compact) {
    final next = result.nodes[node.id];
    final anchorId = anchors[node.id];
    final anchor = anchorId == null ? null : scene.nodeById(anchorId);
    if (next == null || anchor == null) {
      return false;
    }
    final drift = _angleDelta(
      _rayAngle(anchor.center, node.center),
      _rayAngle(anchor.center, next.center),
    );
    if (drift > kHybridCompactOwnRayRadians + 1e-6) {
      return false;
    }
    byAnchor.putIfAbsent(anchorId!, () => []).add(node);
    refined.add(next);
    starts.add(node.rect);
  }
  for (final entry in byAnchor.entries) {
    final anchor = scene.nodeById(entry.key);
    if (anchor == null) {
      return false;
    }
    final centers = [
      for (final node in entry.value) result.nodes[node.id]!.center,
    ];
    final quadrants = centers
        .map((center) => _quadrant(anchor.center, center))
        .toSet();
    if (entry.value.length >= 6 && quadrants.length < 4) {
      return false;
    }
    if (entry.value.length >= 4 && quadrants.length < 3) {
      return false;
    }
  }
  final obstacles = [
    for (final node in scene.nodes)
      if (node.width != kHybridGlyphSize)
        Rect.fromLTWH(
          (display[node.id] ?? node.topLeft).dx,
          (display[node.id] ?? node.topLeft).dy,
          node.width,
          node.height,
        ),
  ];
  return _overlapCount(refined, refined) <= _overlapCount(starts, starts) &&
      _overlapCount(refined, obstacles) <= _overlapCount(starts, obstacles);
}

double _rayAngle(Offset origin, Offset point) {
  return math.atan2(point.dy - origin.dy, point.dx - origin.dx);
}

double _angleDelta(double left, double right) {
  var delta = (left - right) % (2 * math.pi);
  if (delta > math.pi) {
    delta -= 2 * math.pi;
  }
  if (delta < -math.pi) {
    delta += 2 * math.pi;
  }
  return delta.abs();
}

int _quadrant(Offset origin, Offset point) {
  var angle = _rayAngle(origin, point) % (2 * math.pi);
  if (angle < 0) {
    angle += 2 * math.pi;
  }
  return (angle * 2 / math.pi).floor().clamp(0, 3);
}

double _minAngularGap(Offset origin, List<Rect> rects) {
  final angles = [for (final rect in rects) _rayAngle(origin, rect.center)]
    ..sort();
  var minGap = double.infinity;
  for (var index = 0; index < angles.length; index++) {
    final next = index + 1 == angles.length
        ? angles.first + 2 * math.pi
        : angles[index + 1];
    minGap = math.min(minGap, next - angles[index]);
  }
  return minGap;
}

int _overlapCount(List<Rect> left, List<Rect> right) {
  var count = 0;
  for (var i = 0; i < left.length; i++) {
    for (var j = 0; j < right.length; j++) {
      if (identical(left, right) && j <= i) {
        continue;
      }
      if (_hits(left[i], [right[j]])) {
        count += 1;
      }
    }
  }
  return count;
}

Map<String, Offset> _startTopLefts(GraphGeometryScene scene) {
  return {for (final node in scene.nodes) node.id: node.topLeft};
}

const double kHybridTaskRayCorridor = 15 * math.pi / 180;

List<double> _visibleTaskRays({
  required String anchorId,
  required Offset anchorCenter,
  required List<SecretaryEdge> edges,
  required Map<String, SecretaryObject> byId,
  required Map<String, Offset> positions,
}) {
  final rays = <double>[];
  for (final edge in edges) {
    final source = byId[edge.sourceId];
    final target = byId[edge.targetId];
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
    final otherId = edge.sourceId == anchorId
        ? edge.targetId
        : edge.targetId == anchorId
        ? edge.sourceId
        : null;
    final other = otherId == null ? null : byId[otherId];
    final otherTop = otherId == null ? null : positions[otherId];
    if (other == null || other.kind != 'task' || otherTop == null) {
      continue;
    }
    final otherCenter = other.isOngoingTask
        ? hybridOngoingRect(otherTop).center
        : GraphLayout.nodeRectAt(otherTop).center;
    rays.add(_rayAngle(anchorCenter, otherCenter));
  }
  return rays;
}

bool _inReservedRay(double angle, List<double> rays) {
  for (final ray in rays) {
    if (_angleDelta(angle, ray) <= kHybridTaskRayCorridor + 1e-9) {
      return true;
    }
  }
  return false;
}

List<HybridHairline> _semanticHairlines(
  GraphGeometryScene scene,
  Map<String, Offset> topLefts,
  List<SecretaryObject> nodes,
  List<SecretaryEdge> edges,
) {
  final byId = {for (final node in nodes) node.id: node};
  return [
    for (final line in _hairlines(scene, topLefts))
      _withCanonicalArrow(line, edges, byId),
  ];
}

HybridHairline _withCanonicalArrow(
  HybridHairline line,
  List<SecretaryEdge> edges,
  Map<String, SecretaryObject> byId,
) {
  if (line.markId.startsWith('hybrid-overflow:')) {
    return line;
  }
  final edge = graphMapAnchorEdge(
    edges: edges,
    taskId: line.anchorTaskId,
    flowId: line.markId,
  );
  if (edge == null) {
    return line;
  }
  final presentation = presentGraphMapEdge(
    edge: edge,
    sourceKind: byId[edge.sourceId]?.kind,
    targetKind: byId[edge.targetId]?.kind,
  );
  if (!presentation.visibleOnTasksMap) {
    return line;
  }
  return HybridHairline(
    anchorTaskId: line.anchorTaskId,
    markId: line.markId,
    start: line.start,
    end: line.end,
    directed: presentation.directed,
    arrowAtMark: presentation.directed && edge.targetId == line.markId,
    proposed: presentation.proposed,
    dashed: presentation.dashed,
  );
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
  return (
    _shapeBorder(source, target.center),
    _shapeBorder(target, source.center),
  );
}

Offset _shapeBorder(Rect rect, Offset toward) {
  if (rect.width == kHybridOngoingSize && rect.height == kHybridOngoingSize) {
    final dx = toward.dx - rect.center.dx;
    final dy = toward.dy - rect.center.dy;
    final length = math.sqrt(dx * dx + dy * dy);
    if (length == 0) {
      return rect.center;
    }
    final radius = kHybridOngoingSize / 2;
    return Offset(
      rect.center.dx + dx / length * radius,
      rect.center.dy + dy / length * radius,
    );
  }
  return _borderPoint(rect.center, toward, rect.width, rect.height);
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
