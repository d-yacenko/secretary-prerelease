import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/graph/graph_layout.dart';
import 'package:personal_secretary/graph/graph_workspace_controller.dart';
import 'package:personal_secretary/graph/graph_workspace_screen.dart';
import 'package:personal_secretary/ui/domain_labels.dart';
import 'package:personal_secretary/ui/object_visuals.dart';

import '../graph/graph_test_harness.dart';

const _longRussianTitle =
    'Подготовить презентацию для важного совещания с руководством';

void main() {
  test('graph layout accepts russian task title', () {
    final node = SecretaryObject.fromJson(
      graphObjectJson(id: 't1', title: _longRussianTitle),
    );
    final positions = GraphLayout.computePositions(
      nodes: [node],
      edges: [],
      rootId: null,
      existing: {},
      freshRoot: true,
    );
    expect(positions.length, 1);
  });

  final sizes = <Size>[
    const Size(320, 640),
    const Size(360, 800),
    const Size(393, 852),
    const Size(1280, 800),
  ];

  for (final size in sizes) {
    testWidgets('production graph node no overflow at ${size.width}x${size.height}',
        (tester) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final harness = GraphTestHarness(
        overviewMock(
          truncated: false,
          title: _longRussianTitle,
          status: 'in_progress',
        ),
      );
      harness.configure();
      await openGraph(tester, harness);

      expect(find.byType(GraphWorkspaceScreen), findsOneWidget);
      expect(harness.graph.loadState, GraphWorkspaceLoadState.ready);
      expect(find.textContaining('Подготовить'), findsWidgets);
      expect(find.text(objectKindLabel('task')), findsWidgets);
      expect(find.text('В работе'), findsWidgets);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('production graph node no overflow with enlarged text', (tester) async {
    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = GraphTestHarness(
      overviewMock(
        truncated: false,
        title: _longRussianTitle,
        status: 'in_progress',
      ),
    );
    harness.configure();
    await tester.pumpWidget(
      harness.app(textScaler: const TextScaler.linear(1.25)),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Граф'));
    await tester.pumpAndSettle();

    expect(find.byType(GraphWorkspaceScreen), findsOneWidget);
    expect(harness.graph.loadState, GraphWorkspaceLoadState.ready);
    expect(find.text('В работе'), findsWidgets);
    expect(tester.takeException(), isNull);
  });

  testWidgets('overview shows provider badges and human-readable types', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = GraphTestHarness(multiNodeOverviewMock());
    harness.configure();
    await openGraph(tester, harness);

    expect(find.text(objectKindLabel('task')), findsWidgets);
    expect(find.text(objectKindLabel('email')), findsWidgets);
    expect(
      find.descendant(
        of: find.byKey(const Key('graph_node_overview-0')),
        matching: find.text(objectKindLabel('task')),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('graph_node_overview-1')),
        matching: find.text(objectKindLabel('email')),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('graph_node_overview-1')),
        matching: find.byKey(const Key('source_mark_google')),
      ),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('overview layout positions do not overlap', (tester) async {
    final harness = GraphTestHarness(multiNodeOverviewMock());
    harness.configure();
    await openGraph(tester, harness);

    final positions = harness.graph.positions;
    final ids = positions.keys.toList();
    for (var i = 0; i < ids.length; i++) {
      for (var j = i + 1; j < ids.length; j++) {
        expect(
          GraphLayout.nodeRectsOverlap(positions[ids[i]]!, positions[ids[j]]!),
          isFalse,
        );
      }
    }
  });

  testWidgets('rooted focus mode keeps neighbors visible', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = GraphTestHarness(multiNodeOverviewMock());
    harness.configure();
    await openGraph(tester, harness);

    await harness.graph.reRoot('task-center');
    await tester.pumpAndSettle();

    harness.graph.selectObject('task-center');
    await tester.pump();

    expect(find.text('Gmail письмо'), findsWidgets);
    expect(find.text('Яндекс письмо'), findsWidgets);
    expect(find.text('Локальный файл'), findsWidgets);
    expect(tester.takeException(), isNull);
  });

  test('edge endpoints use card boundaries not centers', () {
    final endpoints = GraphLayout.computeEdgeEndpoints(
      sourceCenter: const Offset(50, 50),
      targetCenter: const Offset(300, 50),
    );
    expect(endpoints.start.dx, greaterThan(50));
    expect(endpoints.end.dx, lessThan(300));
  });

  testWidgets('graph task detail shows semantic date without duplicate prefix',
      (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = GraphTestHarness(
      MockClient((request) async {
        if (request.url.path == '/notifications') {
          return jsonUtf8Response({'notifications': []});
        }
        if (request.url.path == '/today') {
          return jsonUtf8Response({
            'date': '2026-08-28',
            'timezone': 'Europe/Amsterdam',
            'day_start': '2026-08-28T00:00:00+02:00',
            'tasks': [],
            'calendar_events': [],
            'notifications': [],
          });
        }
        if (request.url.path == '/graph/workspace') {
          return jsonUtf8Response(
            graphWorkspaceJson(
              nodes: [
                graphObjectJson(
                  id: 'task-due',
                  title: 'Задача со сроком',
                  dueAt: '2026-08-30T18:00:00Z',
                ),
              ],
              truncated: false,
            ),
          );
        }
        return jsonUtf8Response({}, statusCode: 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);

    harness.graph.selectObject('task-due');
    await tester.pump();

    expect(find.textContaining('Срок: 30.08.2026'), findsWidgets);
    expect(find.textContaining('Срок: Срок:'), findsNothing);
  });
}
