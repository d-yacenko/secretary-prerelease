import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/graph/fcose_graph_refiner.dart';
import 'package:personal_secretary/graph/focus_lod.dart';
import 'package:personal_secretary/graph/graph_geometry.dart';
import 'package:personal_secretary/graph/graph_layout.dart';
import 'package:personal_secretary/graph/hybrid_focus_lod.dart';

void main() {
  test('small compact halos use the full circumference', () {
    for (final count in [2, 3, 4, 6]) {
      final fixture = _halo('task', count);
      final raw = _present(fixture, null, _IdentityRefiner());
      final marks = _compact(raw, 'task');
      expect(marks, hasLength(count));
      expect(marks.every((rect) => rect.width == kHybridGlyphSize), isTrue);
      final angles = _angles(_center(raw, 'task'), marks);
      final expected = 2 * math.pi / count;
      expect(_minGap(angles), closeTo(expected, 0.2));
      expect(_maxGap(angles), closeTo(expected, 0.2));
      expect(
        _quadrants(angles).length,
        greaterThanOrEqualTo(count == 2 ? 2 : 3),
      );
      // ignore: avoid_print
      print(
        'V7B_small_$count quads=${_quadrants(angles).length} '
        'min=${_deg(_minGap(angles))} maxGap=${_deg(_maxGap(angles))}',
      );
    }
  });

  test('ongoing dandelion stays compact around the circle', () {
    final fixture = _halo('direction', 8, ongoing: true);
    final selected = _present(fixture, 'direction', _IdentityRefiner());
    expect(
      selected.scene.nodes.where(
        (node) => node.width == kHybridFocusedCardWidth,
      ),
      isEmpty,
    );
    final marks = _compact(selected, 'direction');
    expect(marks, hasLength(8));
    expect(
      _quadrants(_angles(_center(selected, 'direction'), marks)).length,
      4,
    );
    final anchor = hybridOngoingRect(fixture.positions['direction']!);
    expect(selected.scene.nodeById('direction')!.rect, anchor);
    for (final line in selected.hairlines) {
      expect(
        (line.start - anchor.center).distance,
        closeTo(kHybridOngoingSize / 2, 0.05),
      );
      final mark = selected.scene.nodeById(line.markId)!;
      expect(mark.rect.inflate(1).contains(line.end), isTrue);
    }
    expect(_taskCenterDrift(selected, fixture), 0);
  });

  test('compact multi-ring phases stagger', () {
    final fixture = _halo('task', 21);
    final raw = _present(fixture, null, _IdentityRefiner());
    expect(raw.lod.overflows, hasLength(1));
    final marks = _compact(raw, 'task');
    expect(marks, hasLength(21));
    final origin = _center(raw, 'task');
    final radii = [for (final mark in marks) (mark.center - origin).distance]
      ..sort();
    final inner = <Rect>[];
    final outer = <Rect>[];
    final split = (radii.first + radii.last) / 2;
    for (final mark in marks) {
      if ((mark.center - origin).distance < split) {
        inner.add(mark);
      } else {
        outer.add(mark);
      }
    }
    expect(inner.length, 12);
    expect(outer.length, 9);
    final innerAngles = _angles(origin, inner);
    for (final angle in _angles(origin, outer)) {
      var nearest = double.infinity;
      for (final innerAngle in innerAngles) {
        nearest = math.min(nearest, _delta(angle, innerAngle));
      }
      expect(nearest, greaterThan(_rad(10)));
    }
    expect(_selfOverlaps(marks), 0);
    // ignore: avoid_print
    print(
      'V7B_multiring inner=${inner.length} outer=${outer.length} '
      'min=${_deg(_minGap(_angles(origin, marks)))}',
    );
  });

  test('close halos reserve space deterministically', () {
    final left = _halo('left', 8, origin: const Offset(0, 0));
    final right = _halo('right', 8, origin: const Offset(260, 20));
    final fixture = _merge(left, right);
    final first = _present(fixture, null, _IdentityRefiner());
    final second = _present(fixture, null, _IdentityRefiner());
    final marks = [..._compact(first, 'left'), ..._compact(first, 'right')];
    expect(marks, hasLength(16));
    expect(_selfOverlaps(marks), 0);
    expect(_same(first, second), isTrue);
    // ignore: avoid_print
    print(
      'V7B_close leftQuads=${_quadrants(_angles(_center(first, 'left'), _compact(first, 'left'))).length} '
      'rightQuads=${_quadrants(_angles(_center(first, 'right'), _compact(first, 'right'))).length}',
    );
  });

  test('focused flowers use phased full-circle rings', () {
    final four = _present(_halo('task', 4), 'task', _IdentityRefiner());
    final fourMarks = _focused(four);
    expect(fourMarks, hasLength(4));
    expect(
      _minGap(_angles(_center(four, 'task'), fourMarks)),
      closeTo(math.pi / 2, 0.25),
    );
    expect(_selfOverlaps(fourMarks), 0);

    final twelve = _present(_halo('task', 12), 'task', _IdentityRefiner());
    final marks = _focused(twelve);
    final origin = _center(twelve, 'task');
    final radii = [for (final mark in marks) (mark.center - origin).distance]
      ..sort();
    final split = (radii.first + radii.last) / 2;
    final inner = marks
        .where((mark) => (mark.center - origin).distance < split)
        .toList();
    final outer = marks
        .where((mark) => (mark.center - origin).distance >= split)
        .toList();
    expect(inner.length, 8);
    expect(outer.length, 4);
    for (final angle in _angles(origin, outer)) {
      var nearest = double.infinity;
      for (final innerAngle in _angles(origin, inner)) {
        nearest = math.min(nearest, _delta(angle, innerAngle));
      }
      expect(nearest, greaterThan(_rad(10)));
    }
    expect(
      _minGap(_angles(origin, marks)),
      greaterThanOrEqualTo(kHybridFocusedMinSeparationRadians),
    );
    expect(_pairOverlaps(marks, [twelve.scene.nodeById('task')!.rect]), 0);
    // ignore: avoid_print
    print(
      'V7B_flower4 min=${_deg(_minGap(_angles(_center(four, 'task'), fourMarks)))} '
      'V7B_flower12 min=${_deg(_minGap(_angles(origin, marks)))} '
      'rings=${inner.isEmpty ? 1 : 2}',
    );
  });

  test('focused starts avoid a nearby ongoing obstacle', () {
    final finite = _halo('finite', 4, origin: const Offset(0, 0));
    final ongoing = _halo(
      'direction',
      1,
      origin: const Offset(280, 0),
      ongoing: true,
    );
    final fixture = _merge(finite, ongoing);
    final shown = _present(fixture, 'finite', _IdentityRefiner());
    final cards = _focused(shown);
    expect(cards, hasLength(4));
    expect(
      _pairOverlaps(cards, [
        hybridOngoingRect(fixture.positions['direction']!),
      ]),
      0,
    );
    expect(
      _pairOverlaps(cards, [
        GraphLayout.nodeRectAt(fixture.positions['finite']!),
      ]),
      0,
    );
    expect(_taskCenterDrift(shown, fixture), 0);
    expect(
      shown.lod.satellites.map((item) => item.objectId),
      contains('direction-mail-0'),
    );
  });

  test('topology guards revert an entire pass', () {
    final fixture = _halo('task', 4);
    final rotated = _present(fixture, 'task', _RotateRefiner(40));
    final starts = _present(fixture, 'task', _IdentityRefiner());
    expect(
      rotated.topologyNote,
      'Локальное соцветие оставлено на стартовых позициях',
    );
    expect(_same(rotated, starts), isTrue);

    final gentle = _present(fixture, 'task', _RotateRefiner(10));
    expect(gentle.topologyNote, isNull);
    expect(gentle.warning, isNull);
    expect(_same(gentle, starts), isFalse);
    expect(
      _minGap(_angles(_center(gentle, 'task'), _focused(gentle))),
      greaterThanOrEqualTo(kHybridFocusedMinSeparationRadians),
    );

    final mixed = _halo('left', 4, origin: Offset.zero);
    final other = _halo('right', 4, origin: const Offset(900, 0));
    final pair = _merge(mixed, other);
    final partial = _present(
      pair,
      null,
      _RotateRefiner(
        40,
        only: {'left-mail-0', 'left-mail-1', 'left-mail-2', 'left-mail-3'},
      ),
    );
    final compactStarts = _present(pair, null, _IdentityRefiner());
    expect(
      partial.topologyNote,
      'Компактные гало оставлены на сбалансированных позициях',
    );
    expect(_same(partial, compactStarts), isTrue);
  });

  test('preserve and relax record angular acceptance', () {
    final fixtures = {
      'small4': _halo('task', 4),
      'ongoing8': _halo('direction', 8, ongoing: true),
      'multi21': _halo('task', 21),
      'close': _merge(
        _halo('left', 8),
        _halo('right', 8, origin: const Offset(260, 20)),
      ),
      'flower4': _halo('task', 4),
      'flower12': _halo('task', 12),
    };
    for (final mode in FcoseRefinementMode.values) {
      var compactAccepted = 0;
      var focusedAccepted = 0;
      var compactFallback = 0;
      var focusedFallback = 0;
      for (final entry in fixtures.entries) {
        final selected = entry.key.startsWith('flower') ? 'task' : null;
        final shown = _present(
          entry.value,
          selected,
          FcoseGraphRefiner(mode: mode),
        );
        final raw = _present(entry.value, selected, _IdentityRefiner());
        final focusedMoved = !_sameFocused(shown, raw);
        final compactMoved = !_sameCompact(shown, raw);
        if (shown.lod.satellites.isNotEmpty || shown.lod.overflows.isNotEmpty) {
          if (compactMoved) {
            compactAccepted += 1;
          } else if ((shown.topologyNote ?? '').contains('Компактные')) {
            compactFallback += 1;
          }
        }
        if (shown.scene.nodes.any(
          (node) => node.width == kHybridFocusedCardWidth,
        )) {
          if (focusedMoved) {
            focusedAccepted += 1;
          } else if ((shown.topologyNote ?? '').contains('соцветие')) {
            focusedFallback += 1;
          }
        }
        expect(_taskCenterDrift(shown, entry.value), 0);
        expect(_duplicates(entry.value, shown), 0);
        // ignore: avoid_print
        print(
          'V7B_${mode.name}_${entry.key} warning=${shown.topologyNote} '
          'focusedMoved=$focusedMoved compactMoved=$compactMoved '
          'bounds=${hybridPresentationBounds(shown).size}',
        );
      }
      // ignore: avoid_print
      print(
        'V7B_${mode.name}_summary compactAccepted=$compactAccepted '
        'compactFallback=$compactFallback focusedAccepted=$focusedAccepted '
        'focusedFallback=$focusedFallback',
      );
    }
  });
}

class _IdentityRefiner implements GraphGeometryRefiner {
  @override
  GraphGeometryResult refine(GraphGeometryScene scene) {
    return GraphGeometryResult.success(
      nodes: {for (final node in scene.nodes) node.id: node.rect},
    );
  }
}

class _RotateRefiner implements GraphGeometryRefiner {
  _RotateRefiner(this.degrees, {this.only});

  final double degrees;
  final Set<String>? only;

  @override
  GraphGeometryResult refine(GraphGeometryScene scene) {
    final nodes = <String, Rect>{};
    for (final node in scene.nodes) {
      final shift = !node.fixed && (only == null || only!.contains(node.id));
      nodes[node.id] = shift ? _rotate(scene, node, _rad(degrees)) : node.rect;
    }
    return GraphGeometryResult.success(nodes: nodes);
  }
}

Rect _rotate(GraphGeometryScene scene, GraphGeometryNode node, double radians) {
  GraphGeometryNode? anchor;
  for (final edge in scene.edges) {
    if (edge.targetId == node.id) {
      anchor = scene.nodeById(edge.sourceId);
    }
  }
  final origin = anchor?.center ?? node.center;
  final delta = node.center - origin;
  final next = Offset(
    origin.dx + delta.dx * math.cos(radians) - delta.dy * math.sin(radians),
    origin.dy + delta.dx * math.sin(radians) + delta.dy * math.cos(radians),
  );
  return Rect.fromCenter(center: next, width: node.width, height: node.height);
}

HybridFocusPresentation _present(
  _Fixture fixture,
  String? selected,
  GraphGeometryRefiner refiner,
) {
  final before = Map<String, Offset>.from(fixture.positions);
  final shown = presentHybridFocus(
    nodes: fixture.nodes,
    edges: fixture.edges,
    positions: fixture.positions,
    selectedObjectId: selected,
    refiner: refiner,
  );
  expect(fixture.positions, before);
  return shown;
}

class _Fixture {
  const _Fixture(this.nodes, this.edges, this.positions);
  final List<SecretaryObject> nodes;
  final List<SecretaryEdge> edges;
  final Map<String, Offset> positions;
}

_Fixture _merge(_Fixture left, _Fixture right) {
  return _Fixture(
    [...left.nodes, ...right.nodes],
    [...left.edges, ...right.edges],
    {...left.positions, ...right.positions},
  );
}

_Fixture _halo(
  String taskId,
  int count, {
  Offset origin = Offset.zero,
  bool ongoing = false,
}) {
  final nodes = <SecretaryObject>[
    _object(
      taskId,
      ongoing ? 'Направление' : 'Задача',
      completionMode: ongoing ? 'ongoing' : 'finite',
    ),
  ];
  final edges = <SecretaryEdge>[];
  final positions = <String, Offset>{taskId: origin};
  for (var index = 0; index < count; index++) {
    final id = '$taskId-mail-$index';
    nodes.add(
      _object(
        id,
        'Письмо $index',
        kind: 'email',
        updatedAt:
            '2026-02-${(index + 1).toString().padLeft(2, '0')}T00:00:00Z',
      ),
    );
    edges.add(_edge(taskId, id));
    positions[id] = Offset(8000 + index * 40, 9000);
  }
  return _Fixture(nodes, edges, positions);
}

SecretaryObject _object(
  String id,
  String title, {
  String kind = 'task',
  String? completionMode,
  String updatedAt = '2026-01-01T00:00:00Z',
}) {
  return SecretaryObject(
    id: id,
    kind: kind,
    title: title,
    completionMode: completionMode,
    metadata: const {},
    origin: 'user',
    state: 'confirmed',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: updatedAt,
  );
}

SecretaryEdge _edge(String sourceId, String targetId) {
  return SecretaryEdge(
    id: '$sourceId-$targetId',
    sourceId: sourceId,
    targetId: targetId,
    type: 'references',
    origin: 'user',
    state: 'confirmed',
    metadata: const {},
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  );
}

Offset _center(HybridFocusPresentation shown, String id) {
  return shown.scene.nodeById(id)!.center;
}

List<Rect> _compact(HybridFocusPresentation shown, String anchorId) {
  final ids = {
    ...shown.lod.satellites
        .where((item) => item.anchorTaskId == anchorId)
        .map((item) => item.objectId),
    if (shown.lod.overflows.any((item) => item.anchorTaskId == anchorId))
      hybridOverflowId(anchorId),
  };
  return [for (final id in ids) _shownRect(shown, id)];
}

List<Rect> _focused(HybridFocusPresentation shown) {
  return [
    for (final node in shown.scene.nodes)
      if (node.width == kHybridFocusedCardWidth) _shownRect(shown, node.id),
  ];
}

Rect _shownRect(HybridFocusPresentation shown, String id) {
  final node = shown.scene.nodeById(id)!;
  final topLeft = shown.displayTopLeft[id]!;
  return Rect.fromLTWH(topLeft.dx, topLeft.dy, node.width, node.height);
}

List<double> _angles(Offset origin, List<Rect> marks) {
  return [
    for (final mark in marks)
      math.atan2(mark.center.dy - origin.dy, mark.center.dx - origin.dx),
  ];
}

double _minGap(List<double> angles) => _gaps(angles).reduce(math.min);

double _maxGap(List<double> angles) => _gaps(angles).reduce(math.max);

List<double> _gaps(List<double> angles) {
  final sorted = [...angles]..sort();
  return [
    for (var index = 0; index < sorted.length; index++)
      (index + 1 == sorted.length
              ? sorted.first + 2 * math.pi
              : sorted[index + 1]) -
          sorted[index],
  ];
}

Set<int> _quadrants(List<double> angles) {
  return {
    for (final angle in angles)
      () {
        var value = angle % (2 * math.pi);
        if (value < 0) {
          value += 2 * math.pi;
        }
        return (value * 2 / math.pi).floor().clamp(0, 3);
      }(),
  };
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

double _deg(double radians) => radians * 180 / math.pi;

double _rad(double degrees) => degrees * math.pi / 180;

int _selfOverlaps(List<Rect> rects) {
  var count = 0;
  for (var i = 0; i < rects.length; i++) {
    for (var j = i + 1; j < rects.length; j++) {
      if (rects[i].overlaps(rects[j]) &&
          rects[i].intersect(rects[j]).width > 0.5) {
        count += 1;
      }
    }
  }
  return count;
}

int _pairOverlaps(List<Rect> left, List<Rect> right) {
  var count = 0;
  for (final a in left) {
    for (final b in right) {
      final hit = a.intersect(b);
      if (hit.width > 0.5 && hit.height > 0.5) {
        count += 1;
      }
    }
  }
  return count;
}

double _taskCenterDrift(HybridFocusPresentation shown, _Fixture fixture) {
  var drift = 0.0;
  for (final node in fixture.nodes.where((item) => item.kind == 'task')) {
    final canonical =
        fixture.positions[node.id]! +
        const Offset(kGraphNodeWidth / 2, kGraphNodeHeight / 2);
    drift = math.max(
      drift,
      (shown.scene.nodeById(node.id)!.center - canonical).distance,
    );
    drift = math.max(
      drift,
      (_shownRect(shown, node.id).center - canonical).distance,
    );
  }
  return drift;
}

bool _same(HybridFocusPresentation left, HybridFocusPresentation right) {
  for (final entry in left.displayTopLeft.entries) {
    final other = right.displayTopLeft[entry.key];
    if (other == null || (other - entry.value).distance > 0.01) {
      return false;
    }
  }
  return true;
}

bool _sameFocused(HybridFocusPresentation left, HybridFocusPresentation right) {
  for (final node in left.scene.nodes.where(
    (item) => item.width == kHybridFocusedCardWidth,
  )) {
    final a = left.displayTopLeft[node.id]!;
    final b = right.displayTopLeft[node.id]!;
    if ((a - b).distance > 0.5) {
      return false;
    }
  }
  return true;
}

bool _sameCompact(HybridFocusPresentation left, HybridFocusPresentation right) {
  for (final node in left.scene.nodes.where(
    (item) => item.width == kHybridGlyphSize,
  )) {
    final a = left.displayTopLeft[node.id]!;
    final b = right.displayTopLeft[node.id]!;
    if ((a - b).distance > 0.5) {
      return false;
    }
  }
  return true;
}

int _duplicates(_Fixture fixture, HybridFocusPresentation shown) {
  var bad = 0;
  for (final node in fixture.nodes.where(
    (item) => focusLodKindIsCompactable(item.kind),
  )) {
    var count = 0;
    if (shown.lod.fullCardIds.contains(node.id) &&
        shown.scene.nodeById(node.id)?.width == kHybridFocusedCardWidth) {
      count += 1;
    }
    count += shown.lod.satellites
        .where((item) => item.objectId == node.id)
        .length;
    if (count > 1) {
      bad += 1;
    }
  }
  return bad;
}
