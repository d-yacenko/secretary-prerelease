import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/graph/people_landscape.dart';
import 'package:personal_secretary/graph/person_context_visual.dart';

void main() {
  test(
    'normalized contexts share a family without joining unrelated names',
    () {
      final university = personContextVisual([
        _role('p', 'УЦ группы компании Arenadata'),
      ]);
      final sre = personContextVisual([_role('q', '  sre   arenadata ')]);
      final campus = personContextVisual([_role('r', 'SRE Arenadata')]);
      final south = personContextVisual([
        _role('s', 'Южный Федеральный Университет'),
      ]);
      final rubitech = personContextVisual([_role('t', 'Рубитех')]);

      expect(university.familyKey, 'arenadata');
      expect(sre.familyKey, university.familyKey);
      expect(campus.familyKey, university.familyKey);
      expect(sre.exactKey, campus.exactKey);
      expect(university.exactKey, isNot(campus.exactKey));
      expect(university.shade, isNot(campus.shade));
      expect(south.familyKey, isNot('arenadata'));
      expect(rubitech.familyKey, isNot('arenadata'));
      expect(rubitech.familyKey, 'рубитех');

      final light = ThemeData.light().colorScheme;
      final dark = ThemeData.dark().colorScheme;
      expect(contextCardColor(light, sre), contextCardColor(light, campus));
      expect(
        contextCardColor(light, university),
        isNot(contextCardColor(light, campus)),
      );
      expect(
        contextCardColor(light, const PersonContextVisual.none()),
        light.surface,
      );
      expect(contextCardColor(dark, campus), isNot(dark.surface));
      expect(contextCardColor(dark, campus), contextCardColor(dark, sre));
    },
  );

  test('multiple active contexts stay a combined signature', () {
    final combined = personContextVisual([
      _role('p', 'SRE Arenadata'),
      _role('p', 'Рубитех', id: 'b'),
    ]);
    final again = personContextVisual([
      _role('p', 'Рубитех', id: 'b'),
      _role('p', 'SRE Arenadata'),
    ]);
    final single = personContextVisual([_role('p', 'SRE Arenadata')]);
    final inactive = personContextVisual([
      _role('p', 'SRE Arenadata'),
      _role('p', 'Рубитех', id: 'b', state: 'retracted'),
    ]);

    expect(combined.multiple, isTrue);
    expect(combined.exactKey, isNull);
    expect(combined.familyKey, isNot(single.familyKey));
    expect(combined.familyKey, startsWith('multi:'));
    expect(combined.familyKey, again.familyKey);
    expect(combined.sortKey, again.sortKey);
    expect(inactive.multiple, isFalse);
    expect(inactive.familyKey, single.familyKey);
  });

  test('same context packs into one order-independent micro-cluster', () {
    const base = Offset(400, 220);
    final forward = _project(
      people: [
        _person('person-b', anchors: const ['task'], context: 'SRE Arenadata'),
        _person('person-a', anchors: const ['task'], context: 'sre arenadata'),
      ],
      taskCenters: const {'task': base},
    );
    final reversed = _project(
      people: [
        _person('person-a', anchors: const ['task'], context: 'SRE Arenadata'),
        _person(
          'person-b',
          anchors: const ['task'],
          context: '  SRE   Arenadata',
        ),
      ],
      taskCenters: const {'task': base},
    );
    expect(forward.positions, reversed.positions);
    expect(_center(forward.positions), base);
    expect(
      _gap(forward.positions['person-a']!, forward.positions['person-b']!),
      closeTo(kPeopleLandscapeIntraClusterGap, 0.01),
    );
  });

  test('related contexts stay nearer than an unrelated context and the cluster stays centered', () {
    const base = Offset(500, 300);
    final people = [
      _person(
        'person-uc',
        anchors: const ['task'],
        context: 'УЦ группы компании Arenadata',
      ),
      _person('person-sre', anchors: const ['task'], context: 'SRE Arenadata'),
      _person('person-other', anchors: const ['task'], context: 'Рубитех'),
    ];
    final overview = _project(
      people: people,
      taskCenters: const {'task': base},
    );
    final again = _project(
      people: people.reversed.toList(),
      taskCenters: const {'task': base},
    );
    expect(overview.positions, again.positions);
    expect(_center(overview.positions), offsetClose(base));
    final related = _distance(overview, 'person-uc', 'person-sre');
    final left = _distance(overview, 'person-uc', 'person-other');
    final right = _distance(overview, 'person-sre', 'person-other');
    expect(related, lessThan(left));
    expect(related, lessThan(right));
    expect(_overlaps(overview.positions), isFalse);
  });

  test('a dominant context group still does not overlap', () {
    const base = Offset(80, 40);
    final people = [
      for (var index = 0; index < 7; index++)
        _person(
          'person-$index',
          anchors: const ['task'],
          context: 'SRE Arenadata',
        ),
      _person(
        'person-other',
        anchors: const ['task'],
        context: 'Южный Федеральный Университет',
      ),
    ];
    final overview = _project(
      people: people,
      taskCenters: const {'task': base},
    );
    expect(_center(overview.positions), offsetClose(base));
    expect(_overlaps(overview.positions), isFalse);
    expect(
      overview.positions,
      _project(people: people, taskCenters: const {'task': base}).positions,
    );
  });

  test('changing one context rearranges only that anchor cluster', () {
    const left = Offset(0, 0);
    const right = Offset(2400, 40);
    final before = _project(
      people: [
        _person(
          'person-a',
          anchors: const ['task-left'],
          context: 'SRE Arenadata',
        ),
        _person('person-b', anchors: const ['task-left'], context: 'Рубитех'),
        _person('person-c', anchors: const ['task-right']),
      ],
      taskCenters: const {'task-left': left, 'task-right': right},
    );
    final after = _project(
      people: [
        _person('person-a', anchors: const ['task-left'], context: 'Ядро'),
        _person('person-b', anchors: const ['task-left'], context: 'Рубитех'),
        _person('person-c', anchors: const ['task-right']),
      ],
      taskCenters: const {'task-left': left, 'task-right': right},
    );
    expect(before.positions['person-a'], isNot(after.positions['person-a']));
    expect(after.positions['person-c'], before.positions['person-c']);
    expect(_overlaps(after.positions), isFalse);
  });

  test('unanchored people form shelf sub-clusters by context', () {
    const task = Offset(40, 20);
    final overview = _project(
      people: [
        _person('person-task', anchors: const ['task']),
        _person('person-sre-b', context: 'SRE Arenadata'),
        _person('person-plain-b'),
        _person('person-sre-a', context: 'sre arenadata'),
        _person('person-other', context: 'Рубитех'),
        _person('person-plain-a'),
      ],
      taskCenters: const {'task': task},
    );
    final bounds = overview.taskBounds!;
    for (final id in overview.unanchoredPersonIds) {
      expect(overview.positions[id]!.dx, greaterThan(bounds.right));
    }
    expect(
      overview.positions['person-plain-a']!.dx,
      overview.positions['person-plain-b']!.dx,
    );
    expect(
      overview.positions['person-plain-a']!.dy,
      lessThan(overview.positions['person-plain-b']!.dy),
    );
    expect(
      overview.positions['person-sre-a']!.dx,
      overview.positions['person-sre-b']!.dx,
    );
    expect(
      overview.positions['person-sre-a']!.dx,
      isNot(overview.positions['person-other']!.dx),
    );
    expect(
      overview.positions['person-sre-a']!.dx,
      isNot(overview.positions['person-plain-a']!.dx),
    );
  });
}

Matcher offsetClose(Offset expected) {
  return predicate<Offset>(
    (value) => (value - expected).distance < 0.01,
    'offset close to $expected',
  );
}

PersonRoleAssignment _role(
  String personId,
  String context, {
  String? id,
  String state = 'active',
}) {
  return PersonRoleAssignment(
    id: id ?? 'role',
    personId: personId,
    roleTermId: 'term',
    roleDisplayText: 'роль',
    context: context,
    origin: 'user',
    state: state,
  );
}

PersonPresentation _person(
  String id, {
  List<String> anchors = const [],
  String? context,
}) {
  return PersonPresentation(
    personId: id,
    title: id,
    salienceScore: 1,
    identities: const [],
    routes: const [],
    identityConflict: false,
    openTaskCount: 0,
    landscapeTaskIds: anchors,
    recentCommunicationCount: 0,
    roleAssignments: [if (context != null) _role(id, context)],
  );
}

PeopleLandscapeOverview _project({
  required List<PersonPresentation> people,
  required Map<String, Offset> taskCenters,
}) {
  return projectPeopleLandscapeOverview(
    personIds: [for (final person in people) person.personId],
    people: people,
    taskCenters: taskCenters,
    canonicalCentersActive: true,
  );
}

Offset _center(Map<String, Offset> positions) {
  var x = 0.0;
  var y = 0.0;
  for (final topLeft in positions.values) {
    final center = peopleMarkerCenter(topLeft);
    x += center.dx;
    y += center.dy;
  }
  return Offset(x / positions.length, y / positions.length);
}

double _gap(Offset first, Offset second) {
  final left = first.dx <= second.dx ? first : second;
  final right = first.dx <= second.dx ? second : first;
  return right.dx - (left.dx + kPeopleLandscapeOverviewCardWidth);
}

double _distance(PeopleLandscapeOverview overview, String a, String b) {
  return (peopleMarkerCenter(overview.positions[a]!) -
          peopleMarkerCenter(overview.positions[b]!))
      .distance;
}

bool _overlaps(Map<String, Offset> positions) {
  final entries = positions.entries.toList();
  const card = Size(
    kPeopleLandscapeOverviewCardWidth,
    kPeopleLandscapeOverviewCardHeight,
  );
  for (var i = 0; i < entries.length; i++) {
    final left = Rect.fromLTWH(
      entries[i].value.dx,
      entries[i].value.dy,
      card.width,
      card.height,
    );
    for (var j = i + 1; j < entries.length; j++) {
      final right = Rect.fromLTWH(
        entries[j].value.dx,
        entries[j].value.dy,
        card.width,
        card.height,
      );
      if (left.overlaps(right)) {
        return true;
      }
    }
  }
  return false;
}
