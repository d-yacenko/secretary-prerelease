import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/graph/graph_workspace_controller.dart';
import 'package:personal_secretary/graph/people_landscape.dart';
import 'package:personal_secretary/graph/task_map_hierarchy.dart';

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
  List<SecretaryObject> tasks = const [],
  List<SecretaryEdge> edges = const [],
  bool complete = true,
}) {
  return projectPeopleLandscapeOverview(
    personIds: personIds,
    people: people,
    landscapeTasks: tasks,
    landscapeTaskEdges: edges,
    landscapeTaskContextComplete: complete,
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

const _compactSize = Size(
  kPeopleLandscapeOverviewCardWidth,
  kPeopleLandscapeOverviewCardHeight,
);

void main() {
  test('one complete Task anchor uses canonical Task geography', () {
    final tasks = [_task('task-a')];
    final hierarchy = projectTaskMapHierarchy(nodes: tasks, edges: const []);
    final overview = _project(
      personIds: const ['person-a'],
      people: [_person('person-a', anchors: const ['task-a'])],
      tasks: tasks,
    );
    expect(overview.usable, isTrue);
    expect(overview.positions['person-a'], hierarchy.positions['task-a']);
    expect(overview.anchoredPersonIds, ['person-a']);
    expect(overview.unanchoredPersonIds, isEmpty);
  });

  test('a visible Person without a presentation blocks every position', () {
    final overview = _project(
      personIds: const ['person-a', 'person-z'],
      people: [_person('person-a', anchors: const ['task-a'])],
      tasks: [_task('task-a')],
    );
    expect(overview.usable, isFalse);
    expect(overview.positions, isEmpty);
    expect(overview.unresolvedPersonIds, ['person-z']);
  });

  test('several Tasks use the centroid of canonical positions', () {
    final tasks = [_task('task-a'), _task('task-b')];
    final edges = [_partOf('edge-1', 'task-b', 'task-a')];
    final hierarchy = projectTaskMapHierarchy(nodes: tasks, edges: edges);
    final overview = _project(
      personIds: const ['person-a'],
      people: [
        _person('person-a', anchors: const ['task-a', 'task-a', 'task-b']),
      ],
      tasks: tasks,
      edges: edges,
    );
    final left = hierarchy.positions['task-a']!;
    final right = hierarchy.positions['task-b']!;
    expect(overview.usable, isTrue);
    expect(
      overview.positions['person-a'],
      Offset((left.dx + right.dx) / 2, (left.dy + right.dy) / 2),
    );
  });

  test('unanchored People sit outside Task bounds without moving anchors', () {
    final tasks = [_task('task-a'), _task('task-b')];
    final edges = [_partOf('edge-1', 'task-b', 'task-a')];
    final anchoredOnly = _project(
      personIds: const ['person-anchored'],
      people: [_person('person-anchored', anchors: const ['task-a', 'task-b'])],
      tasks: tasks,
      edges: edges,
    );
    final overview = _project(
      personIds: const ['person-shelf-b', 'person-anchored', 'person-shelf-a'],
      people: [
        _person('person-anchored', anchors: const ['task-a', 'task-b']),
        _person('person-shelf-b'),
        _person('person-shelf-a'),
      ],
      tasks: tasks,
      edges: edges,
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
      tasks: tasks,
      edges: edges,
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

  test('incomplete Task context yields no Person positions', () {
    final overview = _project(
      personIds: const ['person-a'],
      people: [_person('person-a', anchors: const ['task-a'])],
      tasks: [_task('task-a')],
      complete: false,
    );
    expect(overview.usable, isFalse);
    expect(overview.positions, isEmpty);
    expect(overview.taskBounds, isNull);
  });

  test('an incomplete Person anchor set blocks every position', () {
    final tasks = [_task('task-a')];
    final overview = _project(
      personIds: const ['person-ready', 'person-partial'],
      people: [
        _person('person-ready', anchors: const ['task-a']),
        _person('person-partial', anchors: const ['task-a'], complete: false),
      ],
      tasks: tasks,
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
      tasks: [_task('task-a')],
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
    final tasks = [_task('task-left'), _task('task-right')];
    final edges = [_partOf('edge-1', 'task-right', 'task-left')];
    final forward = _project(
      personIds: const ['person-b', 'person-a'],
      people: [
        _person('person-b', anchors: const ['task-right']),
        _person('person-a', anchors: const ['task-left']),
      ],
      tasks: tasks,
      edges: edges,
    );
    final reversed = _project(
      personIds: const ['person-a', 'person-b'],
      people: [
        _person('person-a', anchors: const ['task-left']),
        _person('person-b', anchors: const ['task-right']),
      ],
      tasks: tasks,
      edges: edges,
    );
    expect(forward.usable, isTrue);
    expect(forward.positions, reversed.positions);
    expect(forward.positions['person-a'], isNot(forward.positions['person-b']));
    final hierarchy = projectTaskMapHierarchy(nodes: tasks, edges: edges);
    expect(forward.positions['person-a'], hierarchy.positions['task-left']);
    expect(forward.positions['person-b'], hierarchy.positions['task-right']);
  });

  test('shared and near anchors separate locally without overlap', () {
    const shared = Offset(480, 220);
    final identical = projectPeopleFromTasks(
      personIds: const ['person-b', 'person-a', 'person-c'],
      taskPositions: const {'task-shared': shared},
      taskIdsByPerson: const {
        'person-a': ['task-shared'],
        'person-b': ['task-shared'],
        'person-c': ['task-shared'],
      },
      cardSize: _compactSize,
      nearGap: kPeopleLandscapeOverviewCardGap,
    );
    final repeated = projectPeopleFromTasks(
      personIds: const ['person-c', 'person-a', 'person-b'],
      taskPositions: const {'task-shared': shared},
      taskIdsByPerson: const {
        'person-c': ['task-shared'],
        'person-a': ['task-shared'],
        'person-b': ['task-shared'],
      },
      cardSize: _compactSize,
      nearGap: kPeopleLandscapeOverviewCardGap,
    );
    expect(identical, repeated);
    expect(identical['person-a'], shared);
    expect(_compactCardsOverlap(identical['person-a']!, identical['person-b']!), isFalse);
    expect(_compactCardsOverlap(identical['person-a']!, identical['person-c']!), isFalse);
    expect(_compactCardsOverlap(identical['person-b']!, identical['person-c']!), isFalse);
    for (final position in identical.values) {
      expect((position - shared).distance, lessThan(400));
    }

    const left = Offset(10, 30);
    const right = Offset(18, 34);
    final near = projectPeopleFromTasks(
      personIds: const ['person-b', 'person-a'],
      taskPositions: const {'task-left': left, 'task-right': right},
      taskIdsByPerson: const {
        'person-a': ['task-left'],
        'person-b': ['task-right'],
      },
      cardSize: _compactSize,
      nearGap: kPeopleLandscapeOverviewCardGap,
    );
    expect(_compactCardsOverlap(near['person-a']!, near['person-b']!), isFalse);
    expect((near['person-a']! - left).distance, lessThan(400));
    expect((near['person-b']! - right).distance, lessThan(400));
    expect(near['person-a']!.dx, lessThan(near['person-b']!.dx + kPeopleLandscapeOverviewCardWidth));
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
