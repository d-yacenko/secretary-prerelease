import 'package:flutter/material.dart';

import '../api/api_models.dart';
import '../ui/domain_labels.dart';
import 'focus_lod.dart';

/// Full proposed edge. Stroke stays at least 2.5 px. Diamond is hollow.
const double kProposedFullStroke = 2.8;
const double kProposedFullDiamond = 8;
const double kProposedUnderExtra = 3.2;

/// Compact proposed hairline. Stroke stays in the 1.8–2.0 px band.
const double kProposedHairlineStroke = 1.9;
const double kProposedHairlineDiamond = 6;

/// Undimmed proposal ink. Dimmed focus keeps the cue above 0.65.
const double kProposedOpacity = 0.95;
const double kProposedDimmedOpacity = 0.72;

double proposedRelationOpacity({required bool dimmed}) {
  return dimmed ? kProposedDimmedOpacity : kProposedOpacity;
}

Offset relationSegmentMidpoint(Offset start, Offset end) {
  return Offset((start.dx + end.dx) / 2, (start.dy + end.dy) / 2);
}

void paintRelationDiamond(Canvas canvas, Offset center, double size, Paint paint) {
  final half = size / 2;
  final diamond = Path()
    ..moveTo(center.dx, center.dy - half)
    ..lineTo(center.dx + half, center.dy)
    ..lineTo(center.dx, center.dy + half)
    ..lineTo(center.dx - half, center.dy)
    ..close();
  canvas.drawPath(
    diamond,
    Paint.from(paint)..style = PaintingStyle.stroke,
  );
}

/// `part_of` means child/source -> parent/target. It is a structural solid
/// arrow, stronger than `references` and not dashed like `depends_on`.
/// Legacy `contains` keeps its own source -> target arrow and is not reversed.

const Set<String> kGraphMapHiddenRelationTypes = {
  'requested_by',
  'delegated_to',
  'waiting_on',
  'involves',
  'labeled_with',
  'temporal_evidence',
  'temporal_confirmation',
};

class GraphMapEdgePresentation {
  const GraphMapEdgePresentation({
    required this.visibleOnTasksMap,
    required this.directed,
    required this.dashed,
    required this.light,
    required this.secondary,
    required this.structural,
    required this.proposed,
    required this.label,
  });

  final bool visibleOnTasksMap;
  final bool directed;
  final bool dashed;
  final bool light;
  final bool secondary;
  final bool structural;
  final bool proposed;
  final String label;
}

GraphMapEdgePresentation presentGraphMapEdge({
  required SecretaryEdge edge,
  String? sourceKind,
  String? targetKind,
}) {
  final flowToFlow = _isFlow(sourceKind) && _isFlow(targetKind);
  final hidden = kGraphMapHiddenRelationTypes.contains(edge.type) || flowToFlow;
  final directed = edge.type != 'related_to';
  return GraphMapEdgePresentation(
    visibleOnTasksMap: !hidden,
    directed: directed,
    dashed: edge.type == 'depends_on',
    light: edge.type == 'references',
    secondary: edge.type == 'depends_on',
    structural: edge.type == 'part_of',
    proposed: edge.state == 'proposed',
    label: relationTypeLabel(edge.type),
  );
}

/// Task↔Task relation that the Tasks map already draws.
/// Flow evidence and person/label edges stay outside this predicate.
bool taskToTaskRelationVisibleOnTasksMap({
  required String type,
  required String? sourceKind,
  required String? targetKind,
}) {
  if (sourceKind != 'task' || targetKind != 'task') {
    return false;
  }
  return !kGraphMapHiddenRelationTypes.contains(type);
}

bool _isFlow(String? kind) {
  if (kind == null || kind == 'task') {
    return false;
  }
  return focusLodKindIsCompactable(kind);
}

/// Compact chooser line. Stroke, dash, and arrow come from [presentGraphMapEdge].
class GraphRelationMiniPreview extends StatelessWidget {
  const GraphRelationMiniPreview({super.key, required this.type});

  final String type;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      container: true,
      label: graphRelationMiniPreviewSemantics(type),
      child: CustomPaint(
        size: const Size(36, 12),
        painter: _GraphRelationMiniPreviewPainter(
          presentGraphMapEdge(
            edge: _previewEdge(type),
            sourceKind: 'task',
            targetKind: 'task',
          ),
        ),
      ),
    );
  }
}

class GraphRelationChoiceLabel extends StatelessWidget {
  const GraphRelationChoiceLabel({
    super.key,
    required this.name,
    required this.type,
    required this.meaning,
  });

  final String name;
  final String type;
  final String meaning;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Text(name),
        const SizedBox(width: 8),
        GraphRelationMiniPreview(type: type),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            meaning,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ),
      ],
    );
  }
}

String graphRelationMiniPreviewSemantics(String type) {
  final presentation = presentGraphMapEdge(
    edge: _previewEdge(type),
    sourceKind: 'task',
    targetKind: 'task',
  );
  return [
    presentation.directed ? 'directed' : 'undirected',
    presentation.dashed ? 'dashed' : 'solid',
    if (presentation.light) 'light',
    if (presentation.structural) 'structural',
    presentation.label,
  ].join(' ');
}

SecretaryEdge _previewEdge(String type) {
  return SecretaryEdge(
    id: 'preview-$type',
    sourceId: 'source',
    targetId: 'target',
    type: type,
    origin: 'user',
    state: 'confirmed',
    metadata: const {},
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  );
}

class _GraphRelationMiniPreviewPainter extends CustomPainter {
  _GraphRelationMiniPreviewPainter(this.presentation);

  final GraphMapEdgePresentation presentation;

  @override
  void paint(Canvas canvas, Size size) {
    final color = presentation.light
        ? const Color(0xFF9AA0A6)
        : const Color(0xFF202124);
    final paint = Paint()
      ..color = color
      ..strokeWidth = presentation.structural ? 2.5 : 1.5
      ..style = PaintingStyle.stroke;
    final start = Offset(1, size.height / 2);
    final end = Offset(size.width - (presentation.directed ? 6 : 1), size.height / 2);
    if (presentation.dashed) {
      const dash = 4.0;
      const gap = 3.0;
      var x = start.dx;
      while (x < end.dx) {
        final next = (x + dash).clamp(start.dx, end.dx);
        canvas.drawLine(Offset(x, start.dy), Offset(next, start.dy), paint);
        x += dash + gap;
      }
    } else {
      canvas.drawLine(start, end, paint);
    }
    if (presentation.directed) {
      final tip = Offset(size.width - 1, size.height / 2);
      final arrow = Path()
        ..moveTo(tip.dx, tip.dy)
        ..lineTo(tip.dx - 5, tip.dy - 3.5)
        ..lineTo(tip.dx - 5, tip.dy + 3.5)
        ..close();
      canvas.drawPath(arrow, Paint()..color = color);
    }
  }

  @override
  bool shouldRepaint(covariant _GraphRelationMiniPreviewPainter oldDelegate) {
    return oldDelegate.presentation != presentation;
  }
}

String graphRelationAuditText({
  required SecretaryEdge edge,
  required String sourceTitle,
  required String targetTitle,
  String? selectedObjectId,
}) {
  final source = edge.sourceId == selectedObjectId
      ? 'Этот объект'
      : sourceTitle;
  final target = edge.targetId == selectedObjectId
      ? 'Этот объект'
      : targetTitle;
  final presentation = presentGraphMapEdge(edge: edge);
  if (!presentation.directed) {
    return '$source — $target';
  }
  return '$source —[${presentation.label}]→ $target';
}

/// The canonical edge drawn as one compact hairline for a presentation anchor.
SecretaryEdge? graphMapAnchorEdge({
  required List<SecretaryEdge> edges,
  required String taskId,
  required String flowId,
}) {
  final matches =
      [
        for (final edge in edges)
          if ((edge.sourceId == taskId && edge.targetId == flowId) ||
              (edge.sourceId == flowId && edge.targetId == taskId))
            edge,
      ]..sort((left, right) {
        final rank = _anchorRank(left.type).compareTo(_anchorRank(right.type));
        if (rank != 0) {
          return rank;
        }
        return left.id.compareTo(right.id);
      });
  if (matches.isEmpty) {
    return null;
  }
  return matches.first;
}

/// Active proposed Tasks-map edge inside one collapsed Task↔Flow pair.
bool graphMapPairHasProposedRelation({
  required List<SecretaryEdge> edges,
  required String taskId,
  required String flowId,
  String? sourceKind,
  String? flowKind,
}) {
  for (final edge in edges) {
    final pair =
        (edge.sourceId == taskId && edge.targetId == flowId) ||
        (edge.sourceId == flowId && edge.targetId == taskId);
    if (!pair || edge.state != 'proposed') {
      continue;
    }
    final edgeSourceKind = edge.sourceId == taskId ? sourceKind : flowKind;
    final edgeTargetKind = edge.targetId == taskId ? sourceKind : flowKind;
    if (presentGraphMapEdge(
      edge: edge,
      sourceKind: edgeSourceKind,
      targetKind: edgeTargetKind,
    ).visibleOnTasksMap) {
      return true;
    }
  }
  return false;
}

int _anchorRank(String type) {
  switch (type) {
    case 'references':
      return 0;
    case 'depends_on':
      return 1;
    case 'contains':
      return 2;
    case 'related_to':
      return 3;
    default:
      return 4;
  }
}
