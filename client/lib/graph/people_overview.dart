import 'dart:ui';

import '../api/api_models.dart';
import 'graph_layout.dart';

/// Drawn People overview order. Does not write controller positions.
///
/// Ranked seeds stay in backend order. A visible Person missing from
/// [seedIds] follows, sorted by title then id. A rooted workspace returns
/// an empty overlay so the generic hub layout remains the drawn geometry.
Map<String, Offset> projectPeopleOverview({
  required List<SecretaryObject> nodes,
  required List<String> seedIds,
  required String? rootId,
}) {
  if (rootId != null) {
    return const {};
  }
  final byId = {for (final node in nodes) node.id: node};
  final ranked = <SecretaryObject>[];
  final seen = <String>{};
  for (final id in seedIds) {
    final node = byId[id];
    if (node == null || node.kind != 'person' || !seen.add(id)) {
      continue;
    }
    ranked.add(node);
  }
  final unranked = nodes
      .where((node) => node.kind == 'person' && !seen.contains(node.id))
      .toList()
    ..sort((a, b) {
      final byTitle = a.title.compareTo(b.title);
      if (byTitle != 0) {
        return byTitle;
      }
      return a.id.compareTo(b.id);
    });
  final ordered = [...ranked, ...unranked];
  final positions = <String, Offset>{};
  for (var index = 0; index < ordered.length; index++) {
    final column = index % kGraphOverviewColumns;
    final row = index ~/ kGraphOverviewColumns;
    positions[ordered[index].id] = Offset(
      column * GraphLayout.overviewColumnStep,
      row * GraphLayout.overviewRowStep,
    );
  }
  return positions;
}
