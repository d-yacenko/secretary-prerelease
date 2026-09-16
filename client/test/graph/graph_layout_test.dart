import 'dart:math' as math;
import 'dart:ui';

import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/graph/graph_layout.dart';

SecretaryObject _ringObject(String id, String title) {
  return SecretaryObject(
    id: id,
    kind: 'email',
    title: title,
    metadata: {},
    origin: 'source',
    state: 'observed',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  );
}

SecretaryObject _rootObject() {
  return SecretaryObject(
    id: 'root',
    kind: 'task',
    title: 'Root',
    metadata: {},
    origin: 'user',
    state: 'confirmed',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  );
}

void _expectNoOverlaps(Map<String, Offset> positions, {String? reason}) {
  final ids = positions.keys.toList();
  for (var i = 0; i < ids.length; i++) {
    for (var j = i + 1; j < ids.length; j++) {
      expect(
        GraphLayout.nodeRectsOverlap(positions[ids[i]]!, positions[ids[j]]!),
        isFalse,
        reason: '${reason ?? ''} overlap between ${ids[i]} and ${ids[j]}',
      );
    }
  }
}

SecretaryObject _topologyNode(String id, {String? title, String kind = 'task'}) {
  return SecretaryObject(
    id: id,
    kind: kind,
    title: title ?? id,
    metadata: {},
    origin: 'user',
    state: 'confirmed',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  );
}

SecretaryEdge _topologyEdge(String source, String target) {
  return SecretaryEdge(
    id: 'e-$source-$target',
    sourceId: source,
    targetId: target,
    type: 'related_to',
    origin: 'user',
    state: 'confirmed',
    metadata: {},
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  );
}

Offset _topologyCenter(Map<String, Offset> positions, String id) {
  final topLeft = positions[id]!;
  return Offset(
    topLeft.dx + kGraphNodeWidth / 2,
    topLeft.dy + kGraphNodeHeight / 2,
  );
}

double _topologyDistance(Offset a, Offset b) => (a - b).distance;

double _topologyMinCenterSeparation() {
  final sepW = kGraphNodeWidth + kGraphNodeHorizontalGap;
  final sepH = kGraphNodeHeight + kGraphNodeVerticalGap;
  return math.sqrt(sepW * sepW + sepH * sepH);
}

void main() {
  test('fresh root centers even when existing is empty', () {
    final root = SecretaryObject(
      id: 'root',
      kind: 'task',
      title: 'Root',
      metadata: {},
      origin: 'user',
      state: 'confirmed',
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    );
    final a = SecretaryObject(
      id: 'a',
      kind: 'note',
      title: 'A',
      metadata: {},
      origin: 'user',
      state: 'confirmed',
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    );
    final b = SecretaryObject(
      id: 'b',
      kind: 'note',
      title: 'B',
      metadata: {},
      origin: 'user',
      state: 'confirmed',
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    );

    final positions = GraphLayout.computePositions(edges: [], 
      nodes: [root, a, b],
      rootId: 'root',
      existing: {},
      freshRoot: true,
    );

    expect(positions['root'], const Offset(0, 0));
    expect(positions.containsKey('a'), isTrue);
    expect(positions.containsKey('b'), isTrue);
    expect(positions['a']!.dx, isNot(0));
    expect(positions['b']!.dx, isNot(0));
  });

  test('expand preserves existing root position', () {
    final root = SecretaryObject(
      id: 'root',
      kind: 'task',
      title: 'Root',
      metadata: {},
      origin: 'user',
      state: 'confirmed',
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    );
    final newcomer = SecretaryObject(
      id: 'new',
      kind: 'note',
      title: 'New',
      metadata: {},
      origin: 'user',
      state: 'confirmed',
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    );
    final existing = {'root': const Offset(42, 17)};

    final positions = GraphLayout.computePositions(edges: [], 
      nodes: [root, newcomer],
      rootId: 'root',
      existing: existing,
      freshRoot: false,
    );

    expect(positions['root'], const Offset(42, 17));
    expect(positions.containsKey('new'), isTrue);
  });

  test('fit single node centers in viewport using canvas coordinates', () {
    final positions = {'root': const Offset(0, 0)};
    final viewport = const Size(400, 300);
    final bounds = GraphLayout.viewportBoundsAfterFit(
      positions: positions,
      viewportSize: viewport,
    );

    expect(bounds.left, greaterThanOrEqualTo(0));
    expect(bounds.top, greaterThanOrEqualTo(0));
    expect(bounds.right, lessThanOrEqualTo(viewport.width));
    expect(bounds.bottom, lessThanOrEqualTo(viewport.height));
    expect(bounds.center.dx, closeTo(viewport.width / 2, 2.0));
    expect(bounds.center.dy, closeTo(viewport.height / 2, 2.0));
  });

  test('fit ring with negative raw coordinates stays inside viewport', () {
    final positions = {
      'root': const Offset(-200, -150),
      'a': const Offset(-20, -150),
      'b': const Offset(-200, -30),
    };
    final viewport = const Size(500, 400);
    final bounds = GraphLayout.viewportBoundsAfterFit(
      positions: positions,
      viewportSize: viewport,
    );

    expect(bounds.left, greaterThanOrEqualTo(0));
    expect(bounds.top, greaterThanOrEqualTo(0));
    expect(bounds.right, lessThanOrEqualTo(viewport.width));
    expect(bounds.bottom, lessThanOrEqualTo(viewport.height));
  });

  test('fit uses provided viewport width not a wider screen width', () {
    final positions = {
      'root': const Offset(0, 0),
      'a': const Offset(220, 40),
    };
    final canvasViewport = const Size(320, 400);
    final screenViewport = const Size(920, 400);
    final canvasFit = GraphLayout.viewportBoundsAfterFit(
      positions: positions,
      viewportSize: canvasViewport,
    );
    final screenFit = GraphLayout.viewportBoundsAfterFit(
      positions: positions,
      viewportSize: screenViewport,
    );

    expect(canvasFit.width, lessThan(screenFit.width));
  });

  test('fit clamps to shared scale range for large bounded overview graph', () {
    final positions = <String, Offset>{};
    for (var index = 0; index < 16; index++) {
      positions['wide-$index'] = Offset(index * 180.0, (index % 4) * 200.0);
    }
    final viewport = const Size(320, 500);
    final canvasBounds = GraphLayout.canvasBoundsFromPositions(positions);
    final naturalScale = math.min(
      (viewport.width - kGraphCanvasPadding * 2) / canvasBounds.width,
      (viewport.height - kGraphCanvasPadding * 2) / canvasBounds.height,
    );
    expect(naturalScale, lessThan(0.2));

    final transform = GraphLayout.fitTransform(
      positions: positions,
      viewportSize: viewport,
    );
    final scale = transform.getMaxScaleOnAxis();
    expect(scale, greaterThanOrEqualTo(kGraphMinScale));
    expect(scale, lessThanOrEqualTo(kGraphMaxScale));

    final bounds = GraphLayout.viewportBoundsAfterFit(
      positions: positions,
      viewportSize: viewport,
    );
    expect(bounds.left, greaterThanOrEqualTo(0));
    expect(bounds.top, greaterThanOrEqualTo(0));
    expect(bounds.right, lessThanOrEqualTo(viewport.width));
    expect(bounds.bottom, lessThanOrEqualTo(viewport.height));
  });

  test('computeEdgeEndpoints connects node borders not centers', () {
    final endpoints = GraphLayout.computeEdgeEndpoints(
      sourceCenter: const Offset(0, 0),
      targetCenter: const Offset(200, 0),
    );
    expect(endpoints.start.dx, closeTo(kGraphNodeWidth / 2, 0.01));
    expect(endpoints.start.dy, closeTo(0, 0.01));
    expect(endpoints.end.dx, closeTo(200 - kGraphNodeWidth / 2, 0.01));
    expect(endpoints.end.dy, closeTo(0, 0.01));
  });

  test('overview layout does not overlap fixed-size node cards', () {
    final nodes = List.generate(
      16,
      (index) => SecretaryObject(
        id: 'node-$index',
        kind: 'task',
        title: 'Task $index',
        metadata: {},
        origin: 'user',
        state: 'confirmed',
        createdAt: '2026-01-01T00:00:00Z',
        updatedAt: '2026-01-01T00:00:00Z',
      ),
    );
    final positions = GraphLayout.computePositions(edges: [], 
      nodes: nodes,
      rootId: null,
      existing: {},
      freshRoot: true,
    );
    final ids = positions.keys.toList();
    for (var i = 0; i < ids.length; i++) {
      for (var j = i + 1; j < ids.length; j++) {
        expect(
          GraphLayout.nodeRectsOverlap(positions[ids[i]]!, positions[ids[j]]!),
          isFalse,
          reason: 'overlap between ${ids[i]} and ${ids[j]}',
        );
      }
    }
  });

  test('rooted ring layout does not overlap for neighbor counts 1..24', () {
    final root = SecretaryObject(
      id: 'root',
      kind: 'task',
      title: 'Root',
      metadata: {},
      origin: 'user',
      state: 'confirmed',
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    );

    for (var count = 1; count <= 24; count++) {
      final ring = List.generate(
        count,
        (index) => SecretaryObject(
          id: 'ring-$index',
          kind: 'email',
          title: 'Email $index',
          metadata: {},
          origin: 'source',
          state: 'observed',
          createdAt: '2026-01-01T00:00:00Z',
          updatedAt: '2026-01-01T00:00:00Z',
        ),
      );
      final positions = GraphLayout.computePositions(edges: [], 
        nodes: [root, ...ring],
        rootId: 'root',
        existing: {},
        freshRoot: true,
      );
      final ids = positions.keys.toList();
      for (var i = 0; i < ids.length; i++) {
        for (var j = i + 1; j < ids.length; j++) {
          expect(
            GraphLayout.nodeRectsOverlap(positions[ids[i]]!, positions[ids[j]]!),
            isFalse,
            reason: 'count=$count overlap between ${ids[i]} and ${ids[j]}',
          );
        }
      }
    }
  });

  test('incremental placement keeps existing neighbors and avoids overlap', () {
    final root = _rootObject();
    final a = _ringObject('a', 'A');
    final b = _ringObject('b', 'B');

    final initial = GraphLayout.computePositions(edges: [], 
      nodes: [root, a],
      rootId: 'root',
      existing: {},
      freshRoot: true,
    );
    final rootPos = initial['root']!;
    final aPos = initial['a']!;

    final expanded = GraphLayout.computePositions(edges: [], 
      nodes: [root, a, b],
      rootId: 'root',
      existing: initial,
      freshRoot: false,
    );

    expect(expanded['root'], rootPos);
    expect(expanded['a'], aPos);
    expect(expanded.containsKey('b'), isTrue);
    expect(
      GraphLayout.nodeRectsOverlap(expanded['root']!, expanded['b']!),
      isFalse,
    );
    expect(
      GraphLayout.nodeRectsOverlap(expanded['a']!, expanded['b']!),
      isFalse,
    );
  });

  test('incremental neighbor addition up to 24 preserves positions and avoids overlap', () {
    final root = _rootObject();
    var positions = GraphLayout.computePositions(edges: [], 
      nodes: [root],
      rootId: 'root',
      existing: {},
      freshRoot: true,
    );
    final neighbors = <SecretaryObject>[];

    for (var index = 0; index < 24; index++) {
      final neighbor = _ringObject('n-$index', 'Neighbor $index');
      neighbors.add(neighbor);
      final before = Map<String, Offset>.from(positions);
      positions = GraphLayout.computePositions(edges: [], 
        nodes: [root, ...neighbors],
        rootId: 'root',
        existing: positions,
        freshRoot: false,
      );
      for (final entry in before.entries) {
        expect(
          positions[entry.key],
          entry.value,
          reason: 'position changed for ${entry.key} at index $index',
        );
      }
      _expectNoOverlaps(positions, reason: 'index=$index');
    }
  });

  test('star overview places hub centered with non-overlapping leaves', () {
    final hub = _topologyNode('hub', title: 'Hub');
    final leaves = List.generate(
      5,
      (index) => _topologyNode('leaf-$index', title: 'Leaf $index', kind: 'email'),
    );
    final edges = leaves.map((leaf) => _topologyEdge('hub', leaf.id)).toList();
    final positions = GraphLayout.computePositions(
      nodes: [hub, ...leaves],
      edges: edges,
      rootId: null,
      existing: {},
      freshRoot: true,
    );
    expect(positions['hub'], isNotNull);
    final hubCenter = _topologyCenter(positions, 'hub');
    var leafCx = 0.0;
    var leafCy = 0.0;
    for (final leaf in leaves) {
      final center = _topologyCenter(positions, leaf.id);
      leafCx += center.dx;
      leafCy += center.dy;
    }
    leafCx /= leaves.length;
    leafCy /= leaves.length;
    expect(
      _topologyDistance(hubCenter, Offset(leafCx, leafCy)),
      lessThan(kGraphNodeWidth),
    );
    _expectNoOverlaps(positions, reason: 'star');
  });

  test('rooted chain reflects graph distance in layers', () {
    final a = _topologyNode('a', title: 'A');
    final b = _topologyNode('b', title: 'B');
    final c = _topologyNode('c', title: 'C');
    final d = _topologyNode('d', title: 'D');
    final edges = [
      _topologyEdge('a', 'b'),
      _topologyEdge('b', 'c'),
      _topologyEdge('c', 'd'),
    ];
    final positions = GraphLayout.computePositions(
      nodes: [a, b, c, d],
      edges: edges,
      rootId: 'a',
      existing: {},
      freshRoot: true,
    );
    final rootCenter = _topologyCenter(positions, 'a');
    final distB = _topologyDistance(rootCenter, _topologyCenter(positions, 'b'));
    final distD = _topologyDistance(rootCenter, _topologyCenter(positions, 'd'));
    expect(distB, lessThan(distD));
    _expectNoOverlaps(positions, reason: 'chain');
  });

  test('two disconnected components do not overlap', () {
    final h1 = _topologyNode('h1', title: 'Hub 1');
    final l1 = _topologyNode('l1', title: 'Leaf 1', kind: 'email');
    final h2 = _topologyNode('h2', title: 'Hub 2');
    final l2 = _topologyNode('l2', title: 'Leaf 2', kind: 'email');
    final edges = [
      _topologyEdge('h1', 'l1'),
      _topologyEdge('h2', 'l2'),
    ];
    final positions = GraphLayout.computePositions(
      nodes: [h1, l1, h2, l2],
      edges: edges,
      rootId: null,
      existing: {},
      freshRoot: true,
    );
    final bounds1 = GraphLayout.computeBounds({
      'h1': positions['h1']!,
      'l1': positions['l1']!,
    });
    final bounds2 = GraphLayout.computeBounds({
      'h2': positions['h2']!,
      'l2': positions['l2']!,
    });
    expect(bounds1.overlaps(bounds2), isFalse);
    _expectNoOverlaps(positions, reason: 'two-components');
  });

  test('shuffled input order yields identical positions', () {
    final nodes = [
      _topologyNode('a'),
      _topologyNode('b'),
      _topologyNode('c'),
    ];
    final edges = [_topologyEdge('a', 'b'), _topologyEdge('b', 'c')];
    final ordered = GraphLayout.computePositions(
      nodes: nodes,
      edges: edges,
      rootId: 'a',
      existing: {},
      freshRoot: true,
    );
    final shuffled = GraphLayout.computePositions(
      nodes: [nodes[2], nodes[0], nodes[1]],
      edges: edges,
      rootId: 'a',
      existing: {},
      freshRoot: true,
    );
    for (final id in ordered.keys) {
      expect(shuffled[id], ordered[id], reason: 'position mismatch for $id');
    }
  });

  test('fresh rooted 30 nodes have no overlap', () {
    final root = _topologyNode('root', title: 'Root');
    final spokes = List.generate(29, (index) => _topologyNode('n-$index'));
    final edges = spokes.map((node) => _topologyEdge('root', node.id)).toList();
    final positions = GraphLayout.computePositions(
      nodes: [root, ...spokes],
      edges: edges,
      rootId: 'root',
      existing: {},
      freshRoot: true,
    );
    _expectNoOverlaps(positions, reason: '30-rooted');
  });

  test('incremental expansion preserves all existing positions', () {
    final root = _topologyNode('root');
    final first = _topologyNode('first', kind: 'email');
    final initial = GraphLayout.computePositions(
      nodes: [root, first],
      edges: [_topologyEdge('root', 'first')],
      rootId: 'root',
      existing: {},
      freshRoot: true,
    );
    final second = _topologyNode('second', kind: 'email');
    final expanded = GraphLayout.computePositions(
      nodes: [root, first, second],
      edges: [
        _topologyEdge('root', 'first'),
        _topologyEdge('root', 'second'),
      ],
      rootId: 'root',
      existing: initial,
      freshRoot: false,
    );
    expect(expanded['root'], initial['root']);
    expect(expanded['first'], initial['first']);
    _expectNoOverlaps(expanded, reason: 'incremental');
  });

  test('new node with two positioned neighbors anchors near centroid', () {
    final root = _topologyNode('root');
    final left = _topologyNode('left', kind: 'email');
    final right = _topologyNode('right', kind: 'email');
    final initial = GraphLayout.computePositions(
      nodes: [root, left, right],
      edges: [
        _topologyEdge('root', 'left'),
        _topologyEdge('root', 'right'),
      ],
      rootId: 'root',
      existing: {},
      freshRoot: true,
    );
    final newcomer = _topologyNode('new', kind: 'email');
    final expanded = GraphLayout.computePositions(
      nodes: [root, left, right, newcomer],
      edges: [
        _topologyEdge('root', 'left'),
        _topologyEdge('root', 'right'),
        _topologyEdge('left', 'new'),
        _topologyEdge('right', 'new'),
      ],
      rootId: 'root',
      existing: initial,
      freshRoot: false,
    );
    final anchor = Offset(
      (_topologyCenter(initial, 'left').dx + _topologyCenter(initial, 'right').dx) / 2,
      (_topologyCenter(initial, 'left').dy + _topologyCenter(initial, 'right').dy) / 2,
    );
    final newcomerCenter = _topologyCenter(expanded, 'new');
    expect(
      _topologyDistance(anchor, newcomerCenter),
      lessThan(_topologyMinCenterSeparation() * 3),
    );
    _expectNoOverlaps(expanded, reason: 'two-neighbor anchor');
  });

  test('branch affinity keeps subtrees in parent sectors', () {
    final root = _topologyNode('root');
    final a = _topologyNode('a');
    final b = _topologyNode('b');
    final a1 = _topologyNode('a1');
    final a2 = _topologyNode('a2');
    final b1 = _topologyNode('b1');
    final b2 = _topologyNode('b2');
    final edges = [
      _topologyEdge('root', 'a'),
      _topologyEdge('root', 'b'),
      _topologyEdge('a', 'a1'),
      _topologyEdge('a', 'a2'),
      _topologyEdge('b', 'b1'),
      _topologyEdge('b', 'b2'),
    ];
    final positions = GraphLayout.computePositions(
      nodes: [root, a, b, a1, a2, b1, b2],
      edges: edges,
      rootId: 'root',
      existing: {},
      freshRoot: true,
    );
    final rootCenter = _topologyCenter(positions, 'root');
    final aCenter = _topologyCenter(positions, 'a');
    final bCenter = _topologyCenter(positions, 'b');
    final a1Center = _topologyCenter(positions, 'a1');
    final b1Center = _topologyCenter(positions, 'b1');
    expect(_topologyDistance(a1Center, aCenter), lessThan(_topologyDistance(a1Center, bCenter)));
    expect(_topologyDistance(b1Center, bCenter), lessThan(_topologyDistance(b1Center, aCenter)));
    expect(_topologyDistance(rootCenter, aCenter), lessThan(_topologyDistance(rootCenter, a1Center)));
    _expectNoOverlaps(positions, reason: 'branch-affinity');
  });

  test('wide first layer keeps second hop outside first layer', () {
    final root = _topologyNode('root');
    final spokes = List.generate(20, (index) => _topologyNode('s-$index'));
    final branch = spokes[3];
    final child = _topologyNode('child');
    final edges = [
      for (final spoke in spokes) _topologyEdge('root', spoke.id),
      _topologyEdge(branch.id, 'child'),
    ];
    final positions = GraphLayout.computePositions(
      nodes: [root, ...spokes, child],
      edges: edges,
      rootId: 'root',
      existing: {},
      freshRoot: true,
    );
    final rootCenter = _topologyCenter(positions, 'root');
    final childCenter = _topologyCenter(positions, 'child');
    var maxFirstHop = 0.0;
    for (final spoke in spokes) {
      maxFirstHop = math.max(
        maxFirstHop,
        _topologyDistance(rootCenter, _topologyCenter(positions, spoke.id)),
      );
    }
    expect(
      _topologyDistance(rootCenter, childCenter),
      greaterThan(maxFirstHop),
    );
    _expectNoOverlaps(positions, reason: 'wide-layer');
  });

  test('16 isolated nodes pack compactly in grid', () {
    final nodes = List.generate(16, (index) => _topologyNode('iso-$index'));
    final positions = GraphLayout.computePositions(
      nodes: nodes,
      edges: [],
      rootId: null,
      existing: {},
      freshRoot: true,
    );
    final bounds = GraphLayout.computeBounds(positions);
    expect(bounds.height, greaterThan(GraphLayout.overviewRowStep));
    expect(bounds.width, lessThan(16 * GraphLayout.overviewColumnStep));
    _expectNoOverlaps(positions, reason: 'isolated-grid');
  });
}
