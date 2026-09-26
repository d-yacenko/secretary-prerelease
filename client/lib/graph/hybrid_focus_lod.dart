import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../api/api_models.dart';
import '../ui/object_bookmark.dart';
import '../ui/object_dates.dart';
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

/// Medium selected-flower card. Not the global 186×100 graph card.
const double kHybridFocusedCardWidth = 156;

const double kHybridFocusedCardHeight = 76;

const double _focusedGap = 8;
const int _focusedSlots = 8;
const int _focusedMaxRings = 24;

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
    isBookmarked: isBookmarked,
  );
  final display = _startTopLefts(scene);
  final merged = <String, Rect>{};
  String? warning;

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
      return _fallback(lod, scene, result);
    }
    merged.addAll(result.nodes);
    if (_focusedStaysLocal(
      taskId: selectedObjectId,
      scene: scene,
      focused: focused,
      result: result,
    )) {
      for (final node in focused) {
        final refined = result.nodes[node.id];
        if (refined == null) {
          return _fallback(
            lod,
            scene,
            const GraphGeometryResult.failure('fCoSE omitted a focused Flow card'),
          );
        }
        display[node.id] = refined.topLeft;
      }
    } else {
      warning = 'Локальное соцветие оставлено на стартовых позициях';
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
    } else {
      merged.addAll(result.nodes);
      for (final node in compact) {
        final refined = result.nodes[node.id];
        if (refined == null) {
          warning ??= 'Не удалось уточнить компактные гало';
          break;
        }
        display[node.id] = refined.topLeft;
      }
    }
  }

  return HybridFocusPresentation(
    lod: lod,
    scene: scene,
    result: GraphGeometryResult.success(nodes: merged),
    displayTopLeft: display,
    hairlines: _hairlines(scene, display),
    warning: warning,
  );
}

HybridFocusPresentation _fallback(
  FocusLodProjection lod,
  GraphGeometryScene scene,
  GraphGeometryResult result,
) {
  final starts = _startTopLefts(scene);
  return HybridFocusPresentation(
    lod: lod,
    scene: scene,
    result: result,
    displayTopLeft: starts,
    hairlines: _hairlines(scene, starts),
    warning: result.error ?? 'Не удалось уточнить гибридную карту fCoSE',
  );
}

GraphGeometryScene buildHybridGeometryScene({
  required List<SecretaryObject> nodes,
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
    final focusedTopLeft = focusedStarts[node.id];
    geometryNodes.add(
      GraphGeometryNode(
        id: node.id,
        width: expandedFlow ? kHybridFocusedCardWidth : kGraphNodeWidth,
        height: expandedFlow ? kHybridFocusedCardHeight : kGraphNodeHeight,
        topLeft: expandedFlow
            ? (focusedTopLeft ?? positions[node.id]!)
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

/// Center distance past which the whole focused flower returns to its rings.
double hybridFocusedLocalityLimit(int count) {
  if (count <= 0) {
    return 0;
  }
  final lastRing = (count - 1) ~/ _focusedSlots;
  return _focusedBaseRadius() + (lastRing + 1) * _focusedStep();
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
  if (viewportSize.isEmpty || graphBounds.width <= 0 || graphBounds.height <= 0) {
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
  final selected = nodes.where((node) => node.id == selectedObjectId).firstOrNull;
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
        GraphLayout.nodeRectAt(positions[node.id]!),
  ];
  final placed = <Rect>[];
  final starts = <String, Offset>{};
  final anchor = positions[selectedObjectId]!;
  for (var index = 0; index < focused.length; index++) {
    final slot =
        _nextFocusedSlot(anchor: anchor, blocked: [...occupied, ...placed]) ??
        _forcedFocusedSlot(anchor, index);
    placed.add(slot);
    starts[focused[index].id] = slot.topLeft;
  }
  return starts;
}

Rect _forcedFocusedSlot(Offset anchor, int index) {
  final anchorCenter = Offset(
    anchor.dx + kGraphNodeWidth / 2,
    anchor.dy + kGraphNodeHeight / 2,
  );
  final ring = index ~/ _focusedSlots;
  final slot = index % _focusedSlots;
  final radius = _focusedBaseRadius() + ring * _focusedStep();
  final angle = (2 * math.pi) * slot / _focusedSlots - math.pi / 2;
  return Rect.fromCenter(
    center: Offset(
      anchorCenter.dx + math.cos(angle) * radius,
      anchorCenter.dy + math.sin(angle) * radius,
    ),
    width: kHybridFocusedCardWidth,
    height: kHybridFocusedCardHeight,
  );
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

Rect? _nextFocusedSlot({
  required Offset anchor,
  required List<Rect> blocked,
}) {
  final anchorCenter = Offset(
    anchor.dx + kGraphNodeWidth / 2,
    anchor.dy + kGraphNodeHeight / 2,
  );
  final angleStep = (2 * math.pi) / _focusedSlots;
  for (var ring = 0; ring < _focusedMaxRings; ring++) {
    final radius = _focusedBaseRadius() + ring * _focusedStep();
    for (var slot = 0; slot < _focusedSlots; slot++) {
      final angle = angleStep * slot - math.pi / 2;
      final center = Offset(
        anchorCenter.dx + math.cos(angle) * radius,
        anchorCenter.dy + math.sin(angle) * radius,
      );
      final rect = Rect.fromCenter(
        center: center,
        width: kHybridFocusedCardWidth,
        height: kHybridFocusedCardHeight,
      );
      if (_hits(rect, blocked)) {
        continue;
      }
      return rect;
    }
  }
  return null;
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

double _focusedStep() {
  return math.min(kHybridFocusedCardWidth, kHybridFocusedCardHeight) + _focusedGap;
}

bool _focusedStaysLocal({
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
  final limit = hybridFocusedLocalityLimit(focused.length);
  for (final node in focused) {
    final refined = result.nodes[node.id];
    if (refined == null) {
      return false;
    }
    if ((refined.center - task.center).distance > limit) {
      return false;
    }
  }
  return true;
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
