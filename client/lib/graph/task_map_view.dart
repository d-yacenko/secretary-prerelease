import 'package:flutter/material.dart';
import 'package:graphview/GraphView.dart';

import '../api/api_models.dart';
import 'task_map.dart';

class TaskMapNodeCard extends StatelessWidget {
  const TaskMapNodeCard({
    super.key,
    required this.object,
    required this.density,
    required this.selected,
    required this.dimmed,
    required this.onTap,
  });

  final SecretaryObject object;
  final TaskMapDensity density;
  final bool selected;
  final bool dimmed;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final presentation = presentTaskMapNode(object, density);
    final scheme = Theme.of(context).colorScheme;
    final card = Material(
      color: presentation.context
          ? scheme.surfaceContainerHighest
          : scheme.surface,
      elevation: selected ? 3 : 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(8),
        side: BorderSide(
          color: selected ? scheme.primary : scheme.outlineVariant,
          width: selected ? 2 : 1,
        ),
      ),
      child: InkWell(
        key: ValueKey('task-map-node-${object.id}'),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                presentation.title,
                key: const ValueKey('task-map-title'),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
              if (presentation.cue != null)
                Text(
                  presentation.cue!,
                  key: const ValueKey('task-map-cue'),
                  style: Theme.of(context).textTheme.labelSmall,
                ),
              if (presentation.dueLabel != null)
                Text(
                  presentation.dueLabel!,
                  key: const ValueKey('task-map-due'),
                  style: Theme.of(context).textTheme.labelSmall,
                ),
            ],
          ),
        ),
      ),
    );
    if (!dimmed) {
      return card;
    }
    return Opacity(opacity: 0.35, child: card);
  }
}

class TaskMapExperiment extends StatefulWidget {
  const TaskMapExperiment({
    super.key,
    required this.nodes,
    required this.edges,
    required this.selectedObjectId,
    required this.layout,
    required this.showContext,
    required this.onSelect,
    this.onZoomToFit,
  });

  final List<SecretaryObject> nodes;
  final List<SecretaryEdge> edges;
  final String? selectedObjectId;
  final TaskMapLayout layout;
  final bool showContext;
  final ValueChanged<String> onSelect;
  final void Function(VoidCallback zoomToFit)? onZoomToFit;

  @override
  State<TaskMapExperiment> createState() => _TaskMapExperimentState();
}

class _TaskMapExperimentState extends State<TaskMapExperiment> {
  final TransformationController _transform = TransformationController();
  late final GraphViewController _viewController = GraphViewController(
    transformationController: _transform,
  );
  TaskMapDensity _density = TaskMapDensity.middle;

  @override
  void initState() {
    super.initState();
    _transform.addListener(_onTransform);
    widget.onZoomToFit?.call(_viewController.zoomToFit);
  }

  @override
  void didUpdateWidget(covariant TaskMapExperiment oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.onZoomToFit != widget.onZoomToFit) {
      widget.onZoomToFit?.call(_viewController.zoomToFit);
    }
  }

  @override
  void dispose() {
    _transform.removeListener(_onTransform);
    // GraphView disposes the TransformationController it was given.
    super.dispose();
  }

  void _onTransform() {
    final next = taskMapDensityForScale(_transform.value.getMaxScaleOnAxis());
    if (next != _density && mounted) {
      setState(() => _density = next);
    }
  }

  @override
  Widget build(BuildContext context) {
    final projection = projectTaskMap(
      nodes: widget.nodes,
      edges: widget.edges,
      selectedObjectId: widget.selectedObjectId,
      showContext: widget.showContext,
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 4, 12, 4),
          child: Text(
            'Экспериментальная карта',
            key: const ValueKey('task-map-experimental-label'),
            style: Theme.of(context).textTheme.labelLarge,
          ),
        ),
        Expanded(child: _body(projection)),
      ],
    );
  }

  Widget _body(TaskMapProjection projection) {
    if (projection.nodes.isEmpty) {
      return const Center(child: Text('Нет задач в рабочей области'));
    }
    final preview = layoutTaskMap(
      layout: widget.layout,
      nodes: projection.nodes,
      edges: projection.edges,
    );
    if (!preview.completed) {
      return _fallback(projection, preview.error);
    }
    final graph = _graph(projection);
    final neighborIds = _neighborIds(projection);
    return GraphView.builder(
      graph: graph,
      algorithm: taskMapAlgorithm(widget.layout),
      controller: _viewController,
      animated: false,
      centerGraph: false,
      builder: (node) {
        final id = node.key!.value as String;
        final object = projection.nodes.firstWhere((item) => item.id == id);
        final selected = id == widget.selectedObjectId;
        final focused = widget.selectedObjectId != null;
        final related = selected || neighborIds.contains(id);
        return TaskMapNodeCard(
          object: object,
          density: _density,
          selected: selected,
          dimmed: focused && !related,
          onTap: () => widget.onSelect(id),
        );
      },
    );
  }

  Widget _fallback(TaskMapProjection projection, String? error) {
    return ListView(
      key: const ValueKey('task-map-layout-fallback'),
      padding: const EdgeInsets.all(12),
      children: [
        const Text(
          'Этот layout не смог разместить текущий граф. Данные рабочей области не изменены.',
        ),
        if (error != null) Text(error),
        const SizedBox(height: 8),
        for (final node in projection.nodes)
          ListTile(
            dense: true,
            title: Text(node.title),
            onTap: () => widget.onSelect(node.id),
          ),
      ],
    );
  }

  Graph _graph(TaskMapProjection projection) {
    final graph = Graph();
    final byId = <String, Node>{};
    for (final object in projection.nodes) {
      final node = Node.Id(object.id);
      byId[object.id] = node;
      graph.addNode(node);
    }
    final selected = widget.selectedObjectId;
    for (final edge in projection.edges) {
      final source = byId[edge.sourceId];
      final target = byId[edge.targetId];
      if (source == null || target == null || identical(source, target)) {
        continue;
      }
      final related = selected == null ||
          edge.sourceId == selected ||
          edge.targetId == selected;
      graph.addEdge(
        source,
        target,
        paint: Paint()
          ..color = related
              ? Theme.of(context).colorScheme.primary
              : Theme.of(context).colorScheme.outline.withValues(alpha: 0.35)
          ..strokeWidth = related ? 2 : 1
          ..style = PaintingStyle.stroke,
      );
    }
    return graph;
  }

  Set<String> _neighborIds(TaskMapProjection projection) {
    final selected = widget.selectedObjectId;
    if (selected == null) {
      return const {};
    }
    final ids = <String>{};
    for (final edge in projection.edges) {
      if (edge.sourceId == selected) {
        ids.add(edge.targetId);
      } else if (edge.targetId == selected) {
        ids.add(edge.sourceId);
      }
    }
    return ids;
  }
}
