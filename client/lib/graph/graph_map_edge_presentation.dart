import '../api/api_models.dart';
import '../ui/domain_labels.dart';
import 'focus_lod.dart';

/// Future `part_of` means child/source -> parent/target.
/// It is not implemented. Legacy `contains` keeps its own source -> target
/// arrow and is not reversed to imitate `part_of`.

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
    required this.proposed,
    required this.label,
  });

  final bool visibleOnTasksMap;
  final bool directed;
  final bool dashed;
  final bool light;
  final bool secondary;
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
    proposed: edge.state == 'proposed',
    label: relationTypeLabel(edge.type),
  );
}

bool _isFlow(String? kind) {
  if (kind == null || kind == 'task') {
    return false;
  }
  return focusLodKindIsCompactable(kind);
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
