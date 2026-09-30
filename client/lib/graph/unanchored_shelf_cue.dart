import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'people_landscape.dart';

/// Narrow edge tab. Much smaller than the 128×56 Person marker.
const double kUnanchoredShelfCueWidth = 36;
const double kUnanchoredShelfCueHeight = 40;

/// World bounds of the real unanchored shelf, or null when there is nothing to track.
Rect? unanchoredShelfWorldBounds(PeopleLandscapeOverview overview) {
  if (!overview.usable || overview.unanchoredPersonIds.isEmpty) {
    return null;
  }
  Rect? bounds;
  for (final id in overview.unanchoredPersonIds) {
    final topLeft = overview.positions[id];
    if (topLeft == null) {
      return null;
    }
    final marker = Rect.fromLTWH(
      topLeft.dx,
      topLeft.dy,
      kPeopleLandscapeOverviewCardWidth,
      kPeopleLandscapeOverviewCardHeight,
    );
    bounds = bounds == null ? marker : bounds.expandToInclude(marker);
  }
  return bounds;
}

/// Maps a world rectangle through the same canvas frame the People markers use.
Rect worldRectToViewport({
  required Rect world,
  required Offset paintOrigin,
  required double canvasPadding,
  required Matrix4 transform,
}) {
  Offset canvasPoint(Offset worldPoint) {
    return Offset(
      worldPoint.dx - paintOrigin.dx + canvasPadding,
      worldPoint.dy - paintOrigin.dy + canvasPadding,
    );
  }

  final corners = [
    canvasPoint(world.topLeft),
    canvasPoint(world.topRight),
    canvasPoint(world.bottomRight),
    canvasPoint(world.bottomLeft),
  ].map((point) => MatrixUtils.transformPoint(transform, point));
  var minX = double.infinity;
  var minY = double.infinity;
  var maxX = double.negativeInfinity;
  var maxY = double.negativeInfinity;
  for (final corner in corners) {
    minX = math.min(minX, corner.dx);
    minY = math.min(minY, corner.dy);
    maxX = math.max(maxX, corner.dx);
    maxY = math.max(maxY, corner.dy);
  }
  return Rect.fromLTRB(minX, minY, maxX, maxY);
}

class UnanchoredShelfCuePlacement {
  const UnanchoredShelfCuePlacement({
    required this.onLeft,
    required this.top,
    required this.count,
  });

  final bool onLeft;
  final double top;
  final int count;
}

/// Null when any part of the shelf already intersects the graph viewport.
UnanchoredShelfCuePlacement? placeUnanchoredShelfCue({
  required Rect shelfViewport,
  required Size viewportSize,
  required int count,
  double handleHeight = kUnanchoredShelfCueHeight,
}) {
  if (count <= 0 || viewportSize.isEmpty || shelfViewport.isEmpty) {
    return null;
  }
  final viewport = Offset.zero & viewportSize;
  if (shelfViewport.overlaps(viewport)) {
    return null;
  }
  final onLeft = shelfViewport.right <= viewport.left ||
      (shelfViewport.left < viewport.right && shelfViewport.center.dx < viewport.center.dx);
  final rawTop = shelfViewport.center.dy - handleHeight / 2;
  final maxTop = math.max(0.0, viewportSize.height - handleHeight);
  return UnanchoredShelfCuePlacement(
    onLeft: onLeft,
    top: rawTop.clamp(0.0, maxTop),
    count: count,
  );
}

/// Centers [world] in the viewport while keeping the current uniform scale.
Matrix4 panToCenterWorldRect({
  required Matrix4 current,
  required Rect world,
  required Offset paintOrigin,
  required double canvasPadding,
  required Size viewportSize,
}) {
  final scale = current.getMaxScaleOnAxis();
  final canvas = Rect.fromLTWH(
    world.left - paintOrigin.dx + canvasPadding,
    world.top - paintOrigin.dy + canvasPadding,
    world.width,
    world.height,
  );
  final center = canvas.center;
  return Matrix4.identity()
    ..translateByDouble(
      viewportSize.width / 2 - scale * center.dx,
      viewportSize.height / 2 - scale * center.dy,
      0,
      1,
    )
    ..scaleByDouble(scale, scale, 1, 1);
}
