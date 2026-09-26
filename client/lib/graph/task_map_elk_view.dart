import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../api/api_models.dart';
import 'elk_task_map_engine.dart';
import 'task_map.dart';
import 'task_map_scene.dart';
import 'task_map_view.dart';

class TaskMapElkView extends StatefulWidget {
  const TaskMapElkView({
    super.key,
    required this.nodes,
    required this.edges,
    required this.selectedObjectId,
    required this.onSelect,
    this.engine = const ElkTaskMapEngine(),
    this.onZoomToFit,
  });

  final List<SecretaryObject> nodes;
  final List<SecretaryEdge> edges;
  final String? selectedObjectId;
  final ValueChanged<String> onSelect;
  final TaskMapLayoutEngine engine;
  final void Function(VoidCallback zoomToFit)? onZoomToFit;

  @override
  State<TaskMapElkView> createState() => _TaskMapElkViewState();
}

class _TaskMapElkViewState extends State<TaskMapElkView> {
  final TransformationController _transform = TransformationController();
  TaskMapDensity _density = TaskMapDensity.middle;
  Size? _viewportSize;
  Size? _canvasSize;

  @override
  void initState() {
    super.initState();
    _transform.addListener(_onTransform);
    widget.onZoomToFit?.call(_zoomToFit);
  }

  @override
  void didUpdateWidget(covariant TaskMapElkView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.onZoomToFit != widget.onZoomToFit) {
      widget.onZoomToFit?.call(_zoomToFit);
    }
  }

  @override
  void dispose() {
    _transform.removeListener(_onTransform);
    _transform.dispose();
    super.dispose();
  }

  void _onTransform() {
    final next = taskMapDensityForScale(_transform.value.getMaxScaleOnAxis());
    if (next != _density && mounted) {
      setState(() => _density = next);
    }
  }

  void _zoomToFit() {
    final viewport = _viewportSize;
    final canvas = _canvasSize;
    if (viewport == null || canvas == null || canvas.width <= 0 || canvas.height <= 0) {
      _transform.value = Matrix4.identity();
      return;
    }
    final scale = math.min(viewport.width / canvas.width, viewport.height / canvas.height);
    final fitted = scale.clamp(0.05, 1.0);
    _transform.value = Matrix4.identity()..scaleByDouble(fitted, fitted, 1, 1);
  }

  @override
  Widget build(BuildContext context) {
    final scene = buildTaskMapScene(
      nodes: widget.nodes,
      edges: widget.edges,
      selectedObjectId: widget.selectedObjectId,
    );
    final layout = scene.nodes.isEmpty
        ? const TaskMapSceneLayout.success(nodes: {}, edges: [])
        : widget.engine.layout(scene);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 4, 12, 4),
          child: Text(
            'Карта ELK',
            key: const ValueKey('task-map-elk-label'),
            style: Theme.of(context).textTheme.labelLarge,
          ),
        ),
        Expanded(child: _body(scene, layout)),
      ],
    );
  }

  Widget _body(TaskMapScene scene, TaskMapSceneLayout layout) {
    if (scene.nodes.isEmpty) {
      return const Center(child: Text('Нет задач в рабочей области'));
    }
    if (!layout.completed) {
      return _fallback(layout.error);
    }
    final objects = {for (final node in widget.nodes) node.id: node};
    final canvas = _bounds(layout);
    _canvasSize = canvas;
    final neighborIds = <String>{
      for (final edge in scene.edges) ...[edge.sourceId, edge.targetId],
    };
    return LayoutBuilder(
      builder: (context, constraints) {
        _viewportSize = Size(constraints.maxWidth, constraints.maxHeight);
        return InteractiveViewer(
          transformationController: _transform,
          constrained: false,
          boundaryMargin: const EdgeInsets.all(240),
          minScale: 0.2,
          maxScale: 2.5,
          child: SizedBox(
            width: canvas.width,
            height: canvas.height,
            child: Stack(
              children: [
                CustomPaint(
                  size: canvas,
                  painter: _TaskMapEdgePainter(layout.edges),
                ),
                for (final entry in layout.nodes.entries)
                  if (objects[entry.key] != null)
                    Positioned(
                      key: ValueKey('task-map-elk-pos-${entry.key}'),
                      left: entry.value.left,
                      top: entry.value.top,
                      width: entry.value.width,
                      height: entry.value.height,
                      child: TaskMapNodeCard(
                        object: objects[entry.key]!,
                        density: _density,
                        selected: entry.key == widget.selectedObjectId,
                        dimmed: widget.selectedObjectId != null &&
                            entry.key != widget.selectedObjectId &&
                            !neighborIds.contains(entry.key),
                        onTap: () => widget.onSelect(entry.key),
                      ),
                    ),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _fallback(String? error) {
    return ListView(
      key: const ValueKey('task-map-elk-fallback'),
      padding: const EdgeInsets.all(16),
      children: [
        Text(error ?? 'Не удалось построить карту ELK'),
        const SizedBox(height: 8),
        const Text('Данные рабочей области не изменены.'),
      ],
    );
  }

  Size _bounds(TaskMapSceneLayout layout) {
    var maxX = 1.0;
    var maxY = 1.0;
    for (final rect in layout.nodes.values) {
      maxX = math.max(maxX, rect.right);
      maxY = math.max(maxY, rect.bottom);
    }
    for (final edge in layout.edges) {
      for (final section in edge.sections) {
        for (final point in section) {
          maxX = math.max(maxX, point.dx);
          maxY = math.max(maxY, point.dy);
        }
      }
    }
    return Size(maxX + 24, maxY + 24);
  }
}

class _TaskMapEdgePainter extends CustomPainter {
  const _TaskMapEdgePainter(this.edges);

  final List<TaskMapRoutedEdge> edges;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = const Color(0xFF6B7280)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5;
    for (final edge in edges) {
      for (final section in edge.sections) {
        if (section.length < 2) {
          continue;
        }
        final path = Path()..moveTo(section.first.dx, section.first.dy);
        for (final point in section.skip(1)) {
          path.lineTo(point.dx, point.dy);
        }
        canvas.drawPath(path, paint);
      }
    }
  }

  @override
  bool shouldRepaint(covariant _TaskMapEdgePainter oldDelegate) {
    return oldDelegate.edges != edges;
  }
}
