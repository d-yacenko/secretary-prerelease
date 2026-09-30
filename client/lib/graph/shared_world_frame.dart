import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'graph_layout.dart';

/// One unrooted world frame shared by Tasks and People.
///
/// [origin] is the top-left of the full canonical Task world. Both layers map
/// a world point through that origin, so a layer's own bounds can change the
/// canvas extent and manual Fit without giving the world a new origin.
class SharedWorldFrame {
  const SharedWorldFrame({
    required this.origin,
    required this.paintBounds,
    required this.layerBounds,
  });

  final Offset origin;
  final Rect paintBounds;
  final Rect layerBounds;

  static SharedWorldFrame around({
    required Rect canonicalBounds,
    required Rect layerBounds,
  }) {
    final origin = canonicalBounds.topLeft;
    return SharedWorldFrame(
      origin: origin,
      layerBounds: layerBounds,
      paintBounds: Rect.fromLTRB(
        origin.dx,
        origin.dy,
        math.max(canonicalBounds.right, layerBounds.right),
        math.max(canonicalBounds.bottom, layerBounds.bottom),
      ),
    );
  }

  /// Current layer rectangle in canvas-local coordinates.
  Rect canvasLayerRect({double padding = kGraphCanvasPadding}) {
    return Rect.fromLTRB(
      layerBounds.left - origin.dx + padding,
      layerBounds.top - origin.dy + padding,
      layerBounds.right - origin.dx + padding,
      layerBounds.bottom - origin.dy + padding,
    );
  }
}

Matrix4 fitSharedLayer({
  required SharedWorldFrame frame,
  required Size viewportSize,
  double padding = kGraphCanvasPadding,
}) {
  final rect = frame.canvasLayerRect(padding: padding);
  if (viewportSize.isEmpty || rect.width <= 0 || rect.height <= 0) {
    return Matrix4.identity();
  }
  final scaleX = (viewportSize.width - padding * 2) / rect.width;
  final scaleY = (viewportSize.height - padding * 2) / rect.height;
  final scale = math.min(scaleX, scaleY).clamp(kGraphMinScale, kGraphMaxScale);
  return Matrix4.identity()
    ..translateByDouble(viewportSize.width / 2, viewportSize.height / 2, 0, 1)
    ..scaleByDouble(scale, scale, 1, 1)
    ..translateByDouble(-rect.center.dx, -rect.center.dy, 0, 1);
}
