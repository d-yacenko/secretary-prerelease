import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/graph/graph_workspace_controller.dart';
import 'package:personal_secretary/graph/people_landscape.dart';

SecretaryObject _task(String id) {
  return SecretaryObject(
    id: id,
    kind: 'task',
    title: id,
    metadata: const {},
    origin: 'user',
    state: 'confirmed',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  );
}

SecretaryEdge _partOf(String id, String child, String parent) {
  return SecretaryEdge(
    id: id,
    sourceId: child,
    targetId: parent,
    type: 'part_of',
    origin: 'user',
    state: 'confirmed',
    metadata: const {},
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  );
}

PersonPresentation _person(
  String id, {
  List<String> anchors = const [],
  bool complete = true,
}) {
  return PersonPresentation(
    personId: id,
    title: id,
    salienceScore: 9,
    identities: const [],
    routes: const [],
    identityConflict: false,
    openTaskCount: 0,
    landscapeTaskIds: anchors,
    landscapeTaskIdsComplete: complete,
    recentCommunicationCount: 0,
  );
}

PeopleLandscapeOverview _project({
  required List<String> personIds,
  required List<PersonPresentation> people,
  Map<String, Offset> taskCenters = const {},
  bool active = true,
}) {
  return projectPeopleLandscapeOverview(
    personIds: personIds,
    people: people,
    taskCenters: taskCenters,
    canonicalCentersActive: active,
  );
}

bool _compactCardsOverlap(Offset left, Offset right) {
  final card = const Size(
    kPeopleLandscapeOverviewCardWidth,
    kPeopleLandscapeOverviewCardHeight,
  );
  return Rect.fromLTWH(left.dx, left.dy, card.width, card.height).overlaps(
    Rect.fromLTWH(right.dx, right.dy, card.width, card.height),
  );
}

void main() {
  test('one complete Task anchor uses canonical Task geography', () {
    const center = Offset(400, 220);
    final overview = _project(
      personIds: const ['person-a'],
      people: [_person('person-a', anchors: const ['task-a'])],
      taskCenters: const {'task-a': center},
    );
    expect(overview.usable, isTrue);
    expect(peopleMarkerCenter(overview.positions['person-a']!), center);
    expect(overview.anchoredPersonIds, ['person-a']);
    expect(overview.unanchoredPersonIds, isEmpty);
  });

  test('a visible Person without a presentation blocks every position', () {
    final overview = _project(
      personIds: const ['person-a', 'person-z'],
      people: [_person('person-a', anchors: const ['task-a'])],
      taskCenters: const {'task-a': Offset(10, 20)},
    );
    expect(overview.usable, isFalse);
    expect(overview.positions, isEmpty);
    expect(overview.unresolvedPersonIds, ['person-z']);
  });

  test('several Tasks use the centroid of canonical positions', () {
    const left = Offset(100, 80);
    const right = Offset(300, 160);
    final overview = _project(
      personIds: const ['person-a'],
      people: [
        _person('person-a', anchors: const ['task-a', 'task-a', 'task-b']),
      ],
      taskCenters: const {'task-a': left, 'task-b': right},
    );
    expect(overview.usable, isTrue);
    expect(
      peopleMarkerCenter(overview.positions['person-a']!),
      const Offset(200, 120),
    );
  });

  test('unanchored People sit outside Task bounds without moving anchors', () {
    const centers = {
      'task-a': Offset(100, 80),
      'task-b': Offset(300, 160),
      'task-far': Offset(2000, 80),
    };
    final anchoredOnly = _project(
      personIds: const ['person-anchored'],
      people: [_person('person-anchored', anchors: const ['task-a', 'task-b'])],
      taskCenters: centers,
    );
    final overview = _project(
      personIds: const ['person-shelf-b', 'person-anchored', 'person-shelf-a'],
      people: [
        _person('person-anchored', anchors: const ['task-a', 'task-b']),
        _person('person-shelf-b'),
        _person('person-shelf-a'),
      ],
      taskCenters: centers,
    );
    expect(overview.usable, isTrue);
    expect(overview.positions['person-anchored'], anchoredOnly.positions['person-anchored']);
    expect(overview.unanchoredPersonIds, ['person-shelf-a', 'person-shelf-b']);
    final bounds = overview.taskBounds!;
    final stripX = overview.positions['person-shelf-a']!.dx;
    expect(overview.positions['person-shelf-b']!.dx, stripX);
    expect(
      overview.positions['person-shelf-a']!.dy,
      lessThan(overview.positions['person-shelf-b']!.dy),
    );
    expect(
      overview.positions['person-anchored']!.dx + kPeopleLandscapeOverviewCardWidth,
      lessThan(stripX),
    );
    for (final id in overview.unanchoredPersonIds) {
      final topLeft = overview.positions[id]!;
      expect(topLeft.dx, greaterThanOrEqualTo(bounds.right + kPeopleLandscapeShelfGap));
      final card = Rect.fromLTWH(
        topLeft.dx,
        topLeft.dy,
        kPeopleLandscapeOverviewCardWidth,
        kPeopleLandscapeOverviewCardHeight,
      );
      expect(card.overlaps(bounds), isFalse);
    }
    expect(
      _compactCardsOverlap(
        overview.positions['person-shelf-a']!,
        overview.positions['person-shelf-b']!,
      ),
      isFalse,
    );
    final reversed = _project(
      personIds: const ['person-shelf-a', 'person-shelf-b', 'person-anchored'],
      people: [
        _person('person-shelf-a'),
        _person('person-anchored', anchors: const ['task-b', 'task-a']),
        _person('person-shelf-b'),
      ],
      taskCenters: centers,
    );
    expect(reversed.positions, overview.positions);
  });

  test('empty complete Task context places unanchored People on a neutral shelf', () {
    final overview = _project(
      personIds: const ['person-b', 'person-a'],
      people: [_person('person-b'), _person('person-a')],
    );
    expect(overview.usable, isTrue);
    expect(overview.taskBounds, isNull);
    expect(overview.positions['person-a'], kPeopleLandscapeNeutralShelfOrigin);
    expect(
      overview.positions['person-b'],
      const Offset(
        0,
        kPeopleLandscapeOverviewCardHeight + kPeopleLandscapeOverviewCardGap,
      ),
    );
    expect(overview.positions['person-a']!.dx, overview.positions['person-b']!.dx);
    expect(
      _compactCardsOverlap(overview.positions['person-a']!, overview.positions['person-b']!),
      isFalse,
    );
  });

  test('inactive canonical centers yield no Person positions', () {
    final overview = _project(
      personIds: const ['person-a'],
      people: [_person('person-a', anchors: const ['task-a'])],
      taskCenters: const {'task-a': Offset(10, 20)},
      active: false,
    );
    expect(overview.usable, isFalse);
    expect(overview.positions, isEmpty);
    expect(overview.taskBounds, isNull);
  });

  test('an incomplete Person anchor set blocks every position', () {
    final overview = _project(
      personIds: const ['person-ready', 'person-partial'],
      people: [
        _person('person-ready', anchors: const ['task-a']),
        _person('person-partial', anchors: const ['task-a'], complete: false),
      ],
      taskCenters: const {'task-a': Offset(10, 20)},
    );
    expect(overview.usable, isFalse);
    expect(overview.positions, isEmpty);
    expect(overview.unresolvedPersonIds, ['person-partial']);
    expect(overview.anchoredPersonIds, isEmpty);
  });

  test('a missing complete anchor blocks every position', () {
    final overview = _project(
      personIds: const ['person-a', 'person-b'],
      people: [
        _person('person-a', anchors: const ['task-a']),
        _person('person-b', anchors: const ['task-a', 'task-missing']),
      ],
      taskCenters: const {'task-a': Offset(10, 20)},
    );
    expect(overview.usable, isFalse);
    expect(overview.positions, isEmpty);
    expect(overview.unresolvedPersonIds, ['person-b']);
  });

  test('controller replaces People Task context instead of accumulating it', () async {
    final firstEdge = _partOf('edge-old', 'task-old-child', 'task-old');
    final responses = [
      GraphWorkspaceOut(
        seedIds: const [],
        nodes: const [],
        edges: const [],
        truncated: false,
        landscapeTasks: [_task('task-old'), _task('task-old-child')],
        landscapeTaskEdges: [firstEdge],
        landscapeTaskContextComplete: true,
      ),
      GraphWorkspaceOut(
        seedIds: const [],
        nodes: const [],
        edges: const [],
        truncated: false,
        landscapeTasks: [_task('task-new')],
        landscapeTaskContextComplete: false,
      ),
    ];
    var index = 0;
    final controller = GraphWorkspaceController(
      apiClient: _PeopleApi(() => responses[index++]),
      authController: _FakeAuth(),
    );

    await controller.setMode(GraphWorkspaceMode.people);
    expect(controller.landscapeTasks.map((task) => task.id), ['task-old', 'task-old-child']);
    expect(controller.landscapeTaskEdges.map((edge) => edge.id), ['edge-old']);
    expect(controller.landscapeTaskContextComplete, isTrue);

    await controller.loadOverview();
    expect(controller.landscapeTasks.map((task) => task.id), ['task-new']);
    expect(controller.landscapeTaskEdges, isEmpty);
    expect(controller.landscapeTaskContextComplete, isFalse);
    expect(controller.nodes, isEmpty);
    expect(controller.edges, isEmpty);

    controller.resetSession();
    expect(controller.landscapeTasks, isEmpty);
    expect(controller.landscapeTaskEdges, isEmpty);
    expect(controller.landscapeTaskContextComplete, isTrue);
  });

  test('person ids keep their projected positions when input order changes', () {
    const centers = {
      'task-left': Offset(80, 40),
      'task-right': Offset(640, 40),
    };
    final forward = _project(
      personIds: const ['person-b', 'person-a'],
      people: [
        _person('person-b', anchors: const ['task-right']),
        _person('person-a', anchors: const ['task-left']),
      ],
      taskCenters: centers,
    );
    final reversed = _project(
      personIds: const ['person-a', 'person-b'],
      people: [
        _person('person-a', anchors: const ['task-left']),
        _person('person-b', anchors: const ['task-right']),
      ],
      taskCenters: centers,
    );
    expect(forward.usable, isTrue);
    expect(forward.positions, reversed.positions);
    expect(peopleMarkerCenter(forward.positions['person-a']!), centers['task-left']);
    expect(peopleMarkerCenter(forward.positions['person-b']!), centers['task-right']);
  });

  test('shared and near anchors separate locally without overlap', () {
    const shared = Offset(480, 220);
    PeopleLandscapeOverview project(List<String> ids) {
      return _project(
        personIds: ids,
        people: [
          for (final id in ids) _person(id, anchors: const ['task-shared']),
        ],
        taskCenters: const {'task-shared': shared},
      );
    }

    final identical = project(const ['person-b', 'person-a', 'person-c']);
    final repeated = project(const ['person-c', 'person-a', 'person-b']);
    expect(identical.positions, repeated.positions);
    expect(peopleMarkerCenter(identical.positions['person-a']!), shared);
    expect(_compactCardsOverlap(identical.positions['person-a']!, identical.positions['person-b']!), isFalse);
    expect(_compactCardsOverlap(identical.positions['person-a']!, identical.positions['person-c']!), isFalse);
    expect(_compactCardsOverlap(identical.positions['person-b']!, identical.positions['person-c']!), isFalse);
    for (final position in identical.positions.values) {
      expect((peopleMarkerCenter(position) - shared).distance, lessThan(400));
    }

    const left = Offset(10, 30);
    const right = Offset(18, 34);
    final near = _project(
      personIds: const ['person-b', 'person-a'],
      people: [
        _person('person-a', anchors: const ['task-left']),
        _person('person-b', anchors: const ['task-right']),
      ],
      taskCenters: const {'task-left': left, 'task-right': right},
    );
    expect(_compactCardsOverlap(near.positions['person-a']!, near.positions['person-b']!), isFalse);
    expect((peopleMarkerCenter(near.positions['person-a']!) - left).distance, lessThan(400));
    expect((peopleMarkerCenter(near.positions['person-b']!) - right).distance, lessThan(400));
  });
}

class _PeopleApi extends SecretaryApiClient {
  _PeopleApi(this._next);

  final GraphWorkspaceOut Function() _next;

  @override
  Future<GraphWorkspaceOut> getPeopleWorkspace({
    String? rootId,
    String? query,
    int? seedLimit,
    int? neighborLimit,
  }) async {
    return _next();
  }
}

class _FakeAuth extends AuthController {
  _FakeAuth()
      : super(
          apiClient: SecretaryApiClient(),
          tokenStore: FakeTokenStore(),
          serverUrlStore: FakeServerUrlStore(),
        );
}
