import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/ui/domain_labels.dart';

import 'graph_test_harness.dart';

void main() {
  test('ongoing task summary says direction and finite says task', () {
    final ongoing = graphObjectJson(
      id: 'task-1',
      title: 'Direction',
      completionMode: 'ongoing',
    );
    final finite = graphObjectJson(
      id: 'task-2',
      title: 'Task',
      completionMode: 'finite',
    );
    expect(
      objectSummaryLabel(SecretaryObject.fromJson(ongoing)),
      startsWith('Направление'),
    );
    expect(
      objectSummaryLabel(SecretaryObject.fromJson(finite)),
      startsWith('Задача'),
    );
  });

  testWidgets(
    'finite to ongoing edit updates graph presentation and survives refresh',
    (tester) async {
      await _pumpGraph(tester);
      final mode = _Mode();
      final harness = GraphTestHarness(_mock(mode));
      harness.configure();
      await openGraph(tester, harness);
      harness.graph.selectObject('task-1');
      await tester.pumpAndSettle();

      expect(find.byKey(const ValueKey('hybrid-ongoing-task-1')), findsNothing);
      expect(find.textContaining('Задача •'), findsWidgets);

      await tester.tap(find.text('Редактировать'));
      await tester.pumpAndSettle();
      await tester.tap(
        find.descendant(
          of: find.byKey(const Key('task_completion_mode')),
          matching: find.text('Направление'),
        ),
      );
      await tester.tap(find.text('Сохранить'));
      await tester.pumpAndSettle();

      expect(mode.patchBody!['completion_mode'], 'ongoing');
      expect(harness.graph.nodeById('task-1')!.completionMode, 'ongoing');
      expect(
        find.byKey(const ValueKey('hybrid-ongoing-task-1')),
        findsOneWidget,
      );
      expect(find.textContaining('Направление •'), findsWidgets);
      expect(find.text('Направление сохранено'), findsOneWidget);
      expect(find.text('Задача обновлена'), findsNothing);

      await harness.graph.loadOverview();
      await tester.pumpAndSettle();
      harness.graph.selectObject('task-1');
      await tester.pumpAndSettle();
      expect(harness.graph.nodeById('task-1')!.completionMode, 'ongoing');
      expect(
        find.byKey(const ValueKey('hybrid-ongoing-task-1')),
        findsOneWidget,
      );
      expect(find.textContaining('Направление •'), findsWidgets);
    },
  );

  testWidgets('ongoing to finite edit returns the finite task presentation', (
    tester,
  ) async {
    await _pumpGraph(tester);
    final mode = _Mode()..completionMode = 'ongoing';
    final harness = GraphTestHarness(_mock(mode));
    harness.configure();
    await openGraph(tester, harness);
    harness.graph.selectObject('task-1');
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('hybrid-ongoing-task-1')), findsOneWidget);

    await tester.tap(find.text('Редактировать'));
    await tester.pumpAndSettle();
    await tester.tap(
      find.descendant(
        of: find.byKey(const Key('task_completion_mode')),
        matching: find.text('Задача'),
      ),
    );
    await tester.tap(find.text('Сохранить'));
    await tester.pumpAndSettle();

    expect(mode.patchBody!['completion_mode'], 'finite');
    expect(harness.graph.nodeById('task-1')!.effectiveCompletionMode, 'finite');
    expect(find.byKey(const ValueKey('hybrid-ongoing-task-1')), findsNothing);
    expect(find.textContaining('Задача •'), findsWidgets);
    expect(find.text('Задача сохранена'), findsOneWidget);

    await harness.graph.loadOverview();
    await tester.pumpAndSettle();
    harness.graph.selectObject('task-1');
    await tester.pumpAndSettle();
    expect(harness.graph.nodeById('task-1')!.effectiveCompletionMode, 'finite');
    expect(find.byKey(const ValueKey('hybrid-ongoing-task-1')), findsNothing);
    expect(find.textContaining('Задача •'), findsWidgets);
  });
}

class _Mode {
  String completionMode = 'finite';
  Map<String, dynamic>? patchBody;
}

MockClient _mock(_Mode mode) {
  return MockClient((request) async {
    if (request.url.path == '/notifications') {
      return jsonUtf8Response({'notifications': []});
    }
    if (request.url.path == '/today') {
      return jsonUtf8Response({
        'date': '2026-08-28',
        'timezone': 'Europe/Amsterdam',
        'day_start': '2026-08-28T08:00:00+02:00',
        'tasks': [],
        'calendar_events': [],
        'notifications': [],
      });
    }
    if (request.url.path == '/search/facets') {
      return jsonUtf8Response({
        'kinds': [
          {'value': 'task', 'count': 1},
        ],
        'providers': [],
      });
    }
    if (request.url.path == '/graph/workspace') {
      return jsonUtf8Response(
        graphWorkspaceJson(
          nodes: [
            graphObjectJson(
              id: 'task-1',
              title: 'Академический черновик',
              completionMode: mode.completionMode,
            ),
          ],
        ),
      );
    }
    if (request.method == 'PATCH' && request.url.path == '/tasks/task-1') {
      mode.patchBody = jsonDecode(request.body) as Map<String, dynamic>;
      mode.completionMode = mode.patchBody!['completion_mode'] as String;
      return jsonUtf8Response({
        'object': graphObjectJson(
          id: 'task-1',
          title: 'Академический черновик',
          completionMode: mode.completionMode,
        ),
        'changed': true,
      });
    }
    return jsonUtf8Response({}, statusCode: 404);
  });
}

Future<void> _pumpGraph(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1280, 800);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}
