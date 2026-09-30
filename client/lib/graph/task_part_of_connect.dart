import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';

const double kPartOfHandleDiameter = 14;
const double kPartOfHandleRadius = kPartOfHandleDiameter / 2;

/// Four mid-edge handles for the existing `part_of` gesture.
///
/// The wrapper keeps the card's layout size. Handles paint and hit-test
/// slightly outside that size.
class TaskPartOfFrame extends StatefulWidget {
  const TaskPartOfFrame({
    super.key,
    required this.taskId,
    required this.cardSize,
    required this.handlesVisible,
    required this.highlighted,
    required this.enabled,
    required this.onDragStart,
    required this.onDragUpdate,
    required this.onDragEnd,
    required this.onDragCancel,
    required this.child,
  });

  final String taskId;
  final Size cardSize;
  final bool handlesVisible;
  final bool highlighted;
  final bool enabled;
  final void Function(Offset handleGlobal, Offset pointerGlobal) onDragStart;
  final ValueChanged<Offset> onDragUpdate;
  final VoidCallback onDragEnd;
  final VoidCallback onDragCancel;
  final Widget child;

  @override
  State<TaskPartOfFrame> createState() => _TaskPartOfFrameState();
}

class _TaskPartOfFrameState extends State<TaskPartOfFrame> {
  bool _hover = false;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final showHandles = widget.handlesVisible || _hover;
    final pad = kPartOfHandleRadius;
    return Stack(
      clipBehavior: Clip.none,
      children: [
        SizedBox(
          width: widget.cardSize.width + pad * 2,
          height: widget.cardSize.height + pad * 2,
        ),
        Positioned(
          left: pad,
          top: pad,
          width: widget.cardSize.width,
          height: widget.cardSize.height,
          child: MouseRegion(
            onEnter: (_) => setState(() => _hover = true),
            onExit: (_) => setState(() => _hover = false),
            child: widget.child,
          ),
        ),
        if (widget.highlighted)
          Positioned(
            left: pad,
            top: pad,
            width: widget.cardSize.width,
            height: widget.cardSize.height,
            child: IgnorePointer(
              child: DecoratedBox(
                key: ValueKey('part-of-target-${widget.taskId}'),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: scheme.primary, width: 3),
                ),
              ),
            ),
          ),
        if (showHandles)
          for (final edge in _PartOfHandleEdge.values) _handle(scheme, edge),
      ],
    );
  }

  Widget _handle(ColorScheme scheme, _PartOfHandleEdge edge) {
    final radius = kPartOfHandleRadius;
    final pad = radius;
    final width = widget.cardSize.width;
    final height = widget.cardSize.height;
    final left = switch (edge) {
      _PartOfHandleEdge.left => 0.0,
      _PartOfHandleEdge.right => pad + width - radius,
      _PartOfHandleEdge.top ||
      _PartOfHandleEdge.bottom => pad + width / 2 - radius,
    };
    final top = switch (edge) {
      _PartOfHandleEdge.top => 0.0,
      _PartOfHandleEdge.bottom => pad + height - radius,
      _PartOfHandleEdge.left ||
      _PartOfHandleEdge.right => pad + height / 2 - radius,
    };
    return Positioned(
      left: left,
      top: top,
      child: MouseRegion(
        onEnter: (_) => setState(() => _hover = true),
        onExit: (_) => setState(() => _hover = false),
        child: RawGestureDetector(
          behavior: HitTestBehavior.opaque,
          gestures: {
            _EagerPanRecognizer:
                GestureRecognizerFactoryWithHandlers<_EagerPanRecognizer>(
                  () => _EagerPanRecognizer(),
                  (instance) {
                    instance
                      ..onStart = widget.enabled
                          ? (details) {
                              final box =
                                  context.findRenderObject() as RenderBox?;
                              if (box == null || !box.hasSize) {
                                return;
                              }
                              final handleGlobal = box.localToGlobal(
                                Offset(left + radius, top + radius),
                              );
                              widget.onDragStart(
                                handleGlobal,
                                details.globalPosition,
                              );
                            }
                          : null
                      ..onUpdate = widget.enabled
                          ? (details) =>
                                widget.onDragUpdate(details.globalPosition)
                          : null
                      ..onEnd = widget.enabled
                          ? (_) => widget.onDragEnd()
                          : null
                      ..onCancel = widget.enabled ? widget.onDragCancel : null;
                  },
                ),
          },
          child: Container(
            key: ValueKey('part-of-handle-${widget.taskId}-${edge.name}'),
            width: kPartOfHandleDiameter,
            height: kPartOfHandleDiameter,
            decoration: BoxDecoration(
              color: scheme.surface,
              shape: BoxShape.circle,
              border: Border.all(color: scheme.onSurface, width: 1.5),
            ),
          ),
        ),
      ),
    );
  }
}

enum _PartOfHandleEdge { top, right, bottom, left }

class _EagerPanRecognizer extends PanGestureRecognizer {
  @override
  void addAllowedPointer(PointerDownEvent event) {
    super.addAllowedPointer(event);
    resolve(GestureDisposition.accepted);
  }
}

class PartOfDragPreview extends StatelessWidget {
  const PartOfDragPreview({super.key, required this.from, required this.to});

  final Offset from;
  final Offset to;

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: Semantics(
        label: 'part_of drag preview',
        child: CustomPaint(
          painter: PartOfDragPreviewPainter(
            from: from,
            to: to,
            color: Theme.of(context).colorScheme.primary,
          ),
          child: const SizedBox.expand(),
        ),
      ),
    );
  }
}

/// Temporary solid arrow from the source handle toward the pointer.
class PartOfDragPreviewPainter extends CustomPainter {
  PartOfDragPreviewPainter({
    required this.from,
    required this.to,
    required this.color,
  });

  final Offset from;
  final Offset to;
  final Color color;

  bool get solidDirected => true;

  @override
  void paint(Canvas canvas, Size size) {
    final stroke = Paint()
      ..color = color
      ..strokeWidth = 2.5
      ..style = PaintingStyle.stroke;
    canvas.drawLine(from, to, stroke);
    final delta = to - from;
    if (delta.distance < 1) {
      return;
    }
    final direction = delta / delta.distance;
    final normal = Offset(-direction.dy, direction.dx);
    const length = 12.0;
    const halfWidth = 6.0;
    final base = to - direction * length;
    final arrow = Path()
      ..moveTo(to.dx, to.dy)
      ..lineTo(base.dx + normal.dx * halfWidth, base.dy + normal.dy * halfWidth)
      ..lineTo(base.dx - normal.dx * halfWidth, base.dy - normal.dy * halfWidth)
      ..close();
    canvas.drawPath(
      arrow,
      Paint()
        ..color = color
        ..style = PaintingStyle.fill,
    );
  }

  @override
  bool shouldRepaint(PartOfDragPreviewPainter oldDelegate) {
    return oldDelegate.from != from ||
        oldDelegate.to != to ||
        oldDelegate.color != color;
  }
}
