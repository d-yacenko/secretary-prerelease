import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/graph/fcose_graph_refiner.dart';
import 'package:personal_secretary/graph/graph_layout.dart';
import 'package:personal_secretary/graph/hybrid_focus_lod.dart';

void main() {
  test('ongoing anchor stays centered and keeps flow compact', () {
    final fixture = _cluster();
    final before = Map<String, Offset>.from(fixture.positions);
    final overview = _present(fixture, null);
    final ongoing = overview.scene.nodeById('direction')!;
    expect(ongoing.width, kHybridOngoingSize);
    expect(ongoing.height, kHybridOngoingSize);
    expect(ongoing.fixed, isTrue);
    final canonicalCenter = before['direction']! +
        const Offset(kGraphNodeWidth / 2, kGraphNodeHeight / 2);
    expect(ongoing.center, canonicalCenter);
    expect(
      overview.lod.fullCardIds.contains('mail-d'),
      isFalse,
    );
    expect(
      overview.lod.satellites.map((item) => item.objectId),
      contains('mail-d'),
    );

    final selected = _present(fixture, 'direction');
    expect(selected.lod.satellites.map((item) => item.objectId), contains('mail-d'));
    expect(selected.scene.nodeById('mail-d')!.width, kHybridGlyphSize);
    expect(
      selected.scene.nodes.where((node) => node.width == kHybridFocusedCardWidth),
      isEmpty,
    );
    expect(selected.scene.nodeById('finite')!.width, kGraphNodeWidth);
    expect(selected.displayTopLeft['direction'], ongoing.topLeft);
    expect(fixture.positions, before);

    final finite = _present(fixture, 'finite');
    expect(finite.scene.nodeById('mail-f')!.width, kHybridFocusedCardWidth);
    expect(finite.lod.satellites.map((item) => item.objectId), contains('mail-d'));
    final finiteCenter = before['finite']! +
        const Offset(kGraphNodeWidth / 2, kGraphNodeHeight / 2);
    expect(finite.scene.nodeById('finite')!.center, finiteCenter);
    expect(
      (selected.scene.nodeById('direction')!.center - canonicalCenter).distance,
      0,
    );

    final hairline = selected.hairlines.singleWhere(
      (line) => line.markId == 'mail-d',
    );
    final distance = (hairline.start - canonicalCenter).distance;
    expect(distance, closeTo(kHybridOngoingSize / 2, 0.01));
    final toward = canonicalCenter + const Offset(80, 40);
    final square = GraphLayout.computeEdgeEndpoints(
      sourceCenter: canonicalCenter,
      targetCenter: toward,
      nodeWidth: kHybridOngoingSize,
      nodeHeight: kHybridOngoingSize,
    ).start;
    final diagonal = (toward - canonicalCenter).distance;
    final circle = canonicalCenter + (toward - canonicalCenter) / diagonal * (kHybridOngoingSize / 2);
    expect((circle - square).distance, greaterThan(1));
    expect((hairline.start - canonicalCenter).distance, closeTo((circle - canonicalCenter).distance, 0.01));
  });
}

HybridFocusPresentation _present(_Fixture fixture, String? selected) {
  return presentHybridFocus(
    nodes: fixture.nodes,
    edges: fixture.edges,
    positions: fixture.positions,
    selectedObjectId: selected,
    refiner: FcoseGraphRefiner(mode: FcoseRefinementMode.preserve),
  );
}

class _Fixture {
  const _Fixture(this.nodes, this.edges, this.positions);
  final List<SecretaryObject> nodes;
  final List<SecretaryEdge> edges;
  final Map<String, Offset> positions;
}

_Fixture _cluster() {
  return _Fixture(
    [
      _object('direction', 'Направление', completionMode: 'ongoing'),
      _object('finite', 'Задача'),
      _object('mail-d', 'Письмо направления', kind: 'email'),
      _object('mail-f', 'Письмо задачи', kind: 'email'),
    ],
    [
      _edge('direction', 'finite', type: 'depends_on'),
      _edge('direction', 'mail-d'),
      _edge('finite', 'mail-f'),
    ],
    {
      'direction': const Offset(0, 0),
      'finite': const Offset(480, 40),
      'mail-d': const Offset(7000, 1000),
      'mail-f': const Offset(7200, 1000),
    },
  );
}

SecretaryObject _object(
  String id,
  String title, {
  String kind = 'task',
  String? completionMode,
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
    updatedAt: '2026-01-01T00:00:00Z',
  );
}

SecretaryEdge _edge(String sourceId, String targetId, {String type = 'references'}) {
  return SecretaryEdge(
    id: '$sourceId-$targetId',
    sourceId: sourceId,
    targetId: targetId,
    type: type,
    origin: 'user',
    state: 'confirmed',
    metadata: const {},
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  );
}
