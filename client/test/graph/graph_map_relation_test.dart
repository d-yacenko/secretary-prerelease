import 'dart:math' as math;

import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/graph/graph_geometry.dart';
import 'package:personal_secretary/graph/graph_map_edge_presentation.dart';
import 'package:personal_secretary/graph/hybrid_focus_lod.dart';

void main() {
  test('relation grammar keeps canonical direction', () {
    final related = _present('related_to');
    expect(related.directed, isFalse);
    expect(related.dashed, isFalse);
    expect(related.visibleOnTasksMap, isTrue);

    final references = _present('references');
    expect(references.directed, isTrue);
    expect(references.light, isTrue);
    expect(references.dashed, isFalse);

    final depends = _present('depends_on');
    expect(depends.directed, isTrue);
    expect(depends.dashed, isTrue);
    expect(depends.secondary, isTrue);

    final contains = _present('contains');
    expect(contains.directed, isTrue);
    expect(contains.dashed, isFalse);

    final partOf = _present('part_of', sourceKind: 'task', targetKind: 'task');
    expect(partOf.visibleOnTasksMap, isTrue);
    expect(partOf.directed, isTrue);
    expect(partOf.dashed, isFalse);
    expect(partOf.light, isFalse);
    expect(partOf.secondary, isFalse);
    expect(partOf.structural, isTrue);
    expect(partOf.label, 'входит в');

    final proposed = _present('references', state: 'proposed');
    expect(proposed.directed, isTrue);
    expect(proposed.proposed, isTrue);
    expect(proposed.dashed, isFalse);

    final proposedRelated = _present('related_to', state: 'proposed');
    expect(proposedRelated.directed, isFalse);
    expect(proposedRelated.proposed, isTrue);

    for (final type in kGraphMapHiddenRelationTypes) {
      expect(_present(type).visibleOnTasksMap, isFalse, reason: type);
    }
    expect(
      _present(
        'references',
        sourceKind: 'email',
        targetKind: 'file',
      ).visibleOnTasksMap,
      isFalse,
    );
  });

  test(
    'detail audit keeps source and target when the selection is either end',
    () {
      final edge = _edge('task', 'mail', 'references');
      expect(
        graphRelationAuditText(
          edge: edge,
          sourceTitle: 'Задача',
          targetTitle: 'Письмо',
          selectedObjectId: 'task',
        ),
        'Этот объект —[Ссылается на]→ Письмо',
      );
      expect(
        graphRelationAuditText(
          edge: edge,
          sourceTitle: 'Задача',
          targetTitle: 'Письмо',
          selectedObjectId: 'mail',
        ),
        'Задача —[Ссылается на]→ Этот объект',
      );
      expect(
        graphRelationAuditText(
          edge: _edge('child', 'parent', 'part_of'),
          sourceTitle: 'Часть',
          targetTitle: 'Целое',
          selectedObjectId: 'child',
        ),
        'Этот объект —[входит в]→ Целое',
      );
      expect(
        graphRelationAuditText(
          edge: _edge('child', 'parent', 'part_of'),
          sourceTitle: 'Часть',
          targetTitle: 'Целое',
          selectedObjectId: 'parent',
        ),
        'Часть —[входит в]→ Этот объект',
      );
      expect(
        graphRelationAuditText(
          edge: _edge('task', 'note', 'related_to'),
          sourceTitle: 'Задача',
          targetTitle: 'Заметка',
          selectedObjectId: 'note',
        ),
        'Задача — Этот объект',
      );
      expect(
        graphRelationAuditText(
          edge: _edge('person', 'task', 'requested_by'),
          sourceTitle: 'Анна',
          targetTitle: 'Задача',
          selectedObjectId: 'task',
        ),
        'Анна —[Запросил]→ Этот объект',
      );
    },
  );

  test('compact hairline follows the chosen canonical edge', () {
    final forward = _show(edges: [_edge('task', 'mail', 'references')]);
    final line = forward.hairlines.single;
    expect(line.directed, isTrue);
    expect(line.arrowAtMark, isTrue);

    final reverse = _show(
      edges: [_edge('mail', 'task', 'references', id: 'mail-task')],
    );
    final back = reverse.hairlines.single;
    expect(back.directed, isTrue);
    expect(back.arrowAtMark, isFalse);
    expect(forward.hairlines.single.arrowAtMark, isTrue);

    final symmetric = _show(edges: [_edge('task', 'mail', 'related_to')]);
    expect(symmetric.hairlines.single.directed, isFalse);

    final again = _show(edges: [_edge('task', 'mail', 'references')]);
    expect(again.hairlines.single.arrowAtMark, line.arrowAtMark);
  });

  test('multi-task hairline uses the anchor edge, not the other task', () {
    final shown = _show(
      nodes: [
        _object('near', 'Ближняя'),
        _object('far', 'Дальняя'),
        _object('mail', 'Письмо', kind: 'email'),
      ],
      edges: [
        _edge('near', 'mail', 'references', id: 'near-mail'),
        _edge('mail', 'far', 'depends_on', id: 'mail-far'),
      ],
      positions: {
        'near': Offset.zero,
        'far': const Offset(900, 0),
        'mail': const Offset(40, 20),
      },
    );
    final line = shown.hairlines.single;
    expect(line.anchorTaskId, 'near');
    expect(line.directed, isTrue);
    expect(line.arrowAtMark, isTrue);
  });

  test('compact starts leave the visible task-edge corridor', () {
    final shown = _show(
      nodes: [
        _object('left', 'Левая'),
        _object('right', 'Правая'),
        for (var index = 0; index < 4; index++)
          _object('mail-$index', 'Письмо $index', kind: 'email'),
      ],
      edges: [
        _edge('left', 'right', 'depends_on', id: 'tasks'),
        for (var index = 0; index < 4; index++)
          _edge('left', 'mail-$index', 'references', id: 'mail-$index'),
      ],
      positions: {
        'left': Offset.zero,
        'right': const Offset(420, 0),
        for (var index = 0; index < 4; index++)
          'mail-$index': Offset(20, 5000.0 + index * 20),
      },
    );
    final anchor = shown.scene.nodeById('left')!.center;
    final other = shown.scene.nodeById('right')!.center;
    final ray = math.atan2(other.dy - anchor.dy, other.dx - anchor.dx);
    for (final line in shown.hairlines.where(
      (item) => item.anchorTaskId == 'left',
    )) {
      final mark = shown.displayTopLeft[line.markId]!;
      final center =
          mark + const Offset(kHybridGlyphSize / 2, kHybridGlyphSize / 2);
      final angle = math.atan2(center.dy - anchor.dy, center.dx - anchor.dx);
      expect(_delta(angle, ray), greaterThan(15 * math.pi / 180));
    }
    expect(_taskDrift(shown), 0);
  });
}

GraphMapEdgePresentation _present(
  String type, {
  String state = 'confirmed',
  String sourceKind = 'task',
  String targetKind = 'email',
}) {
  return presentGraphMapEdge(
    edge: _edge('a', 'b', type, state: state),
    sourceKind: sourceKind,
    targetKind: targetKind,
  );
}

HybridFocusPresentation _show({
  List<SecretaryObject>? nodes,
  required List<SecretaryEdge> edges,
  Map<String, Offset>? positions,
}) {
  final objects =
      nodes ??
      [_object('task', 'Задача'), _object('mail', 'Письмо', kind: 'email')];
  return presentHybridFocus(
    nodes: objects,
    edges: edges,
    positions:
        positions ??
        {
          for (final node in objects) node.id: const Offset(4000, 4000),
          'task': Offset.zero,
        },
    selectedObjectId: null,
    refiner: _IdentityRefiner(),
  );
}

class _IdentityRefiner implements GraphGeometryRefiner {
  @override
  GraphGeometryResult refine(GraphGeometryScene scene) {
    return GraphGeometryResult.success(
      nodes: {for (final node in scene.nodes) node.id: node.rect},
    );
  }
}

SecretaryObject _object(String id, String title, {String kind = 'task'}) {
  return SecretaryObject(
    id: id,
    kind: kind,
    title: title,
    metadata: const {},
    origin: 'user',
    state: 'confirmed',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  );
}

SecretaryEdge _edge(
  String sourceId,
  String targetId,
  String type, {
  String? id,
  String state = 'confirmed',
}) {
  return SecretaryEdge(
    id: id ?? '$sourceId-$targetId-$type',
    sourceId: sourceId,
    targetId: targetId,
    type: type,
    origin: 'user',
    state: state,
    metadata: const {},
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  );
}

double _delta(double left, double right) {
  var delta = (left - right) % (2 * math.pi);
  if (delta > math.pi) {
    delta -= 2 * math.pi;
  }
  if (delta < -math.pi) {
    delta += 2 * math.pi;
  }
  return delta.abs();
}

double _taskDrift(HybridFocusPresentation shown) {
  var drift = 0.0;
  for (final node in shown.scene.nodes.where((item) => item.fixed)) {
    final shownTop = shown.displayTopLeft[node.id];
    if (shownTop == null) {
      continue;
    }
    drift = math.max(drift, (shownTop - node.topLeft).distance);
  }
  return drift;
}
