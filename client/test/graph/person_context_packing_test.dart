import 'dart:math' as math;

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

      final sreShort = personContextVisual([_role('gk', 'SRE ГК Arenadata')]);
      final trainingShort = personContextVisual([
        _role('uc', 'УЦ ГК Arenadata'),
      ]);
      expect(university.familyKey, 'arenadata');
      expect(sre.familyKey, university.familyKey);
      expect(campus.familyKey, university.familyKey);
      expect(sreShort.familyKey, 'arenadata');
      expect(trainingShort.familyKey, 'arenadata');
      expect(sreShort.exactKey, isNot(campus.exactKey));
      expect(trainingShort.exactKey, isNot(university.exactKey));
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
      expect(
        campus.hueOffset.abs(),
        lessThanOrEqualTo(kContextHueOffsetDegrees),
      );
      expect(
        university.hueOffset.abs(),
        lessThanOrEqualTo(kContextHueOffsetDegrees),
      );
      expect(_hueDelta(campus, university, light), lessThan(40));
      expect(_hueDelta(campus, university, dark), lessThan(40));
      expect(
        _rgbDistance(
          contextCardColor(light, campus),
          contextCardColor(light, university),
        ),
        greaterThanOrEqualTo(kContextCardMinSeparation),
      );
      expect(
        _rgbDistance(
          contextCardColor(dark, campus),
          contextCardColor(dark, university),
        ),
        greaterThanOrEqualTo(kContextCardMinSeparation),
      );
    },
  );

  test(
    'exact context color is global and ignores person, cluster, and order',
    () {
      final anchored = personContextVisual([
        _role('person-a', 'SRE Arenadata'),
      ]);
      final otherCluster = personContextVisual([
        _role('person-z', 'SRE Arenadata'),
      ]);
      final shelf = personContextVisual([
        _role('person-shelf', '  sre   arenadata '),
      ]);
      final again = personContextVisual([
        _role('person-z', 'Рубитех', id: 'other', state: 'retracted'),
        _role('person-z', 'SRE Arenadata'),
      ]);
      final light = ThemeData.light().colorScheme;
      expect(anchored.exactKey, otherCluster.exactKey);
      expect(anchored.familyKey, shelf.familyKey);
      expect(anchored.hueOffset, shelf.hueOffset);
      expect(
        contextCardColor(light, anchored),
        contextCardColor(light, otherCluster),
      );
      expect(contextCardColor(light, anchored), contextCardColor(light, shelf));
      expect(contextCardColor(light, anchored), contextCardColor(light, again));
      expect(
        contextCardColor(light, const PersonContextVisual.none()),
        light.surface,
      );
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

  test('thirteen mixed-context people stay inside a compact 4x4 envelope', () {
    const base = Offset(240, 160);
    final people = [
      for (var index = 0; index < 2; index++)
        _person(
          'sre-$index',
          anchors: const ['task'],
          context: 'SRE Arenadata',
        ),
      for (var index = 0; index < 4; index++)
        _person(
          'uc-$index',
          anchors: const ['task'],
          context: 'УЦ группы компании Arenadata',
        ),
      for (var index = 0; index < 6; index++)
        _person('plain-$index', anchors: const ['task']),
      _person('other', anchors: const ['task'], context: 'Рубитех'),
    ];
    final forward = _project(people: people, taskCenters: const {'task': base});
    final reversed = _project(
      people: people.reversed.toList(),
      taskCenters: const {'task': base},
    );
    final shuffled = _project(
      people: [...people.sublist(6), ...people.sublist(0, 6)],
      taskCenters: const {'task': base},
    );
    expect(forward.positions, reversed.positions);
    expect(forward.positions, shuffled.positions);
    expect(_center(forward.positions), offsetClose(base));
    expect(_overlaps(forward.positions), isFalse);
    final bounds = _bounds(forward.positions);
    final envelopeWidth =
        4 * kPeopleLandscapeOverviewCardWidth +
        3 * kPeopleLandscapeIntraClusterGap;
    final envelopeHeight =
        4 * kPeopleLandscapeOverviewCardHeight +
        3 * kPeopleLandscapeIntraClusterGap;
    expect(bounds.width, lessThanOrEqualTo(envelopeWidth + 0.01));
    expect(bounds.height, lessThanOrEqualTo(envelopeHeight + 0.01));

    final sreGap = _distance(forward, 'sre-0', 'sre-1');
    expect(
      sreGap,
      lessThanOrEqualTo(
        kPeopleLandscapeOverviewCardHeight +
            kPeopleLandscapeIntraClusterGap +
            0.01,
      ),
    );
    final ucBounds = _bounds({
      for (final id in ['uc-0', 'uc-1', 'uc-2', 'uc-3'])
        id: forward.positions[id]!,
    });
    expect(
      ucBounds.width,
      lessThanOrEqualTo(
        2 * kPeopleLandscapeOverviewCardWidth +
            kPeopleLandscapeIntraClusterGap +
            0.01,
      ),
    );
    final related = _groupDistance(
      forward,
      ['sre-0', 'sre-1'],
      ['uc-0', 'uc-1', 'uc-2', 'uc-3'],
    );
    final unrelated = _groupDistance(forward, ['sre-0', 'sre-1'], ['other']);
    expect(related, lessThan(unrelated));
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

double _rgbDistance(Color left, Color right) {
  final dr = left.r - right.r;
  final dg = left.g - right.g;
  final db = left.b - right.b;
  return math.sqrt(dr * dr + dg * dg + db * db);
}

double _hueDelta(
  PersonContextVisual left,
  PersonContextVisual right,
  ColorScheme scheme,
) {
  final a = HSLColor.fromColor(contextCardColor(scheme, left)).hue;
  final b = HSLColor.fromColor(contextCardColor(scheme, right)).hue;
  final delta = (a - b).abs();
  return math.min(delta, 360 - delta);
}

Rect _bounds(Map<String, Offset> positions) {
  var minX = double.infinity;
  var minY = double.infinity;
  var maxX = double.negativeInfinity;
  var maxY = double.negativeInfinity;
  for (final topLeft in positions.values) {
    minX = math.min(minX, topLeft.dx);
    minY = math.min(minY, topLeft.dy);
    maxX = math.max(maxX, topLeft.dx + kPeopleLandscapeOverviewCardWidth);
    maxY = math.max(maxY, topLeft.dy + kPeopleLandscapeOverviewCardHeight);
  }
  return Rect.fromLTRB(minX, minY, maxX, maxY);
}

double _groupDistance(
  PeopleLandscapeOverview overview,
  List<String> left,
  List<String> right,
) {
  final a = _center({for (final id in left) id: overview.positions[id]!});
  final b = _center({for (final id in right) id: overview.positions[id]!});
  return (a - b).distance;
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
