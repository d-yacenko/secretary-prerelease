import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets('panel rename updates the unrooted task node immediately', (
    tester,
  ) async {
    final layoutWrites = <String>[];
    final harness = _harness(layoutWrites: layoutWrites);
    harness.configure();
    await _open(tester, harness);

    expect(harness.graph.canonicalTaskCenters['task-a'], const Offset(100, 80));
    expect(harness.graph.rootId, isNull);
    expect(harness.graph.windowIndex, 0);
    expect(harness.graph.mode.name, 'tasks');

    harness.graph.selectObject('task-a');
    await tester.pumpAndSettle();
    final camera = _zoom(tester);
    await tester.pump();
    final workspaceCalls = _workspaceCalls;
    await _rename(tester, 'Новое имя');

    expect(find.text('Новое имя'), findsWidgets);
    expect(find.text('Старое имя'), findsNothing);
    expect(harness.graph.nodeById('task-a')?.title, 'Новое имя');
    expect(harness.graph.nodeById('task-a')?.id, 'task-a');
    expect(harness.graph.rootId, isNull);
    expect(harness.graph.windowIndex, 0);
    expect(harness.graph.mode.name, 'tasks');
    expect(harness.graph.selectedObjectId, 'task-a');
    expect(harness.graph.canonicalTaskCenters['task-a'], const Offset(100, 80));
    expect(harness.graph.canonicalTaskCentersActive, isTrue);
    expect(_workspaceCalls, workspaceCalls);
    expect(layoutWrites, isEmpty);
    expect(_cameraOf(tester).storage, camera.storage);
  });

  testWidgets('panel rename updates the rooted task node without moving the view', (
    tester,
  ) async {
    final layoutWrites = <String>[];
    final harness = _harness(layoutWrites: layoutWrites);
    harness.configure();
    await _open(tester, harness);
    await harness.graph.reRoot('task-a');
    await tester.pumpAndSettle();

    harness.graph.selectObject('task-a');
    await tester.pumpAndSettle();
    final camera = _zoom(tester);
    await tester.pump();
    final workspaceCalls = _workspaceCalls;
    await _rename(tester, 'Новое имя');

    expect(find.text('Новое имя'), findsWidgets);
    expect(find.text('Старое имя'), findsNothing);
    expect(harness.graph.rootId, 'task-a');
    expect(harness.graph.windowIndex, 0);
    expect(harness.graph.canonicalTaskCenters['task-a'], const Offset(100, 80));
    expect(_workspaceCalls, workspaceCalls);
    expect(layoutWrites, isEmpty);
    expect(_cameraOf(tester).storage, camera.storage);
  });

  testWidgets('details rename keeps the new title without reloading the graph', (
    tester,
  ) async {
    final harness = _harness();
    harness.configure();
    await _open(tester, harness);
    harness.graph.selectObject('task-a');
    await tester.pumpAndSettle();
    final camera = _zoom(tester);
    await tester.pump();
    final workspaceCalls = _workspaceCalls;

    await tester.tap(find.text('Подробнее'));
    await tester.pumpAndSettle();
    await _rename(tester, 'Новое имя');
    await tester.pageBack();
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));

    expect(find.text('Новое имя'), findsWidgets);
    expect(find.text('Старое имя'), findsNothing);
    expect(harness.graph.rootId, isNull);
    expect(harness.graph.windowIndex, 0);
    expect(harness.graph.canonicalTaskCenters['task-a'], const Offset(100, 80));
    expect(_workspaceCalls, workspaceCalls);
    expect(_cameraOf(tester).getMaxScaleOnAxis(), camera.getMaxScaleOnAxis());
  });

  testWidgets('a stale successful rename still replaces the visible title', (
    tester,
  ) async {
    final layoutWrites = <String>[];
    final harness = _harness(layoutWrites: layoutWrites, staleTitle: true);
    harness.configure();
    await _open(tester, harness);
    harness.graph.selectObject('task-a');
    await tester.pumpAndSettle();
    final camera = _zoom(tester);
    await tester.pump();
    final workspaceCalls = _workspaceCalls;

    await _rename(tester, 'Новое имя');
    await tester.pump();

    expect(find.text('Новое имя'), findsWidgets);
    expect(find.text('Старое имя'), findsNothing);
    expect(harness.graph.nodeById('task-a')?.title, 'Новое имя');
    expect(harness.graph.nodeById('task-a')?.id, 'task-a');
    expect(harness.graph.rootId, isNull);
    expect(harness.graph.selectedObjectId, 'task-a');
    expect(harness.graph.windowIndex, 0);
    expect(harness.graph.canonicalTaskCenters['task-a'], const Offset(100, 80));
    expect(harness.graph.canonicalTaskCentersActive, isTrue);
    expect(_workspaceCalls, workspaceCalls);
    expect(layoutWrites, isEmpty);
    expect(_cameraOf(tester).storage, camera.storage);
  });

  testWidgets('a stale successful rename keeps the rooted view stable', (
    tester,
  ) async {
    final layoutWrites = <String>[];
    final harness = _harness(layoutWrites: layoutWrites, staleTitle: true);
    harness.configure();
    await _open(tester, harness);
    await harness.graph.reRoot('task-a');
    await tester.pumpAndSettle();
    harness.graph.selectObject('task-a');
    await tester.pumpAndSettle();
    final camera = _zoom(tester);
    await tester.pump();
    final workspaceCalls = _workspaceCalls;

    await _rename(tester, 'Новое имя');
    await tester.pump();

    expect(harness.graph.nodeById('task-a')?.title, 'Новое имя');
    expect(find.text('Старое имя'), findsNothing);
    expect(harness.graph.rootId, 'task-a');
    expect(harness.graph.selectedObjectId, 'task-a');
    expect(harness.graph.windowIndex, 0);
    expect(harness.graph.canonicalTaskCenters['task-a'], const Offset(100, 80));
    expect(_workspaceCalls, workspaceCalls);
    expect(layoutWrites, isEmpty);
    expect(_cameraOf(tester).storage, camera.storage);
  });
}

var _workspaceCalls = 0;

Future<void> _open(WidgetTester tester, GraphTestHarness harness) async {
  tester.view.physicalSize = const Size(1280, 800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  _workspaceCalls = 0;
  await openGraph(tester, harness);
}

Future<void> _rename(WidgetTester tester, String title) async {
  await tester.tap(find.text('Редактировать'));
  await tester.pumpAndSettle();
  await tester.enterText(
    find.descendant(of: find.byType(AlertDialog), matching: find.byType(TextField)).first,
    title,
  );
  await tester.tap(find.widgetWithText(FilledButton, 'Сохранить'));
  await tester.pumpAndSettle();
}

Matrix4 _zoom(WidgetTester tester) {
  final viewer = tester.widget<InteractiveViewer>(find.byType(InteractiveViewer));
  final controller = viewer.transformationController!;
  controller.value = controller.value.clone()..scale(1.35);
  tester.binding.scheduleFrame();
  return controller.value.clone();
}

Matrix4 _cameraOf(WidgetTester tester) {
  final viewer = tester.widget<InteractiveViewer>(find.byType(InteractiveViewer));
  return viewer.transformationController!.value.clone();
}

GraphTestHarness _harness({
  List<String>? layoutWrites,
  bool staleTitle = false,
}) {
  return GraphTestHarness(
    MockClient((request) async {
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
      if (request.url.path == '/graph/workspace') {
        _workspaceCalls += 1;
        final root = request.url.queryParameters['root_id'];
        return jsonUtf8Response(
          graphWorkspaceJson(
            rootId: root,
            nodes: [graphObjectJson(id: 'task-a', title: 'Старое имя')],
          ),
        );
      }
      if (request.method == 'GET' && request.url.path == '/graph/task-layout') {
        return jsonUtf8Response({
          'topology_revision': 3,
          'snapshot_revision': 3,
          'algorithm_version': kTaskLayoutAlgorithmVersion,
          'usable': true,
          'centers': [
            {'task_id': 'task-a', 'world_x': 100, 'world_y': 80},
          ],
        });
      }
      if (request.method == 'PUT' && request.url.path == '/graph/task-layout') {
        layoutWrites?.add(request.url.path);
        return jsonUtf8Response({}, statusCode: 409);
      }
      if (request.url.path == '/graph/task-layout/topology') {
        layoutWrites?.add(request.url.path);
        return jsonUtf8Response({}, statusCode: 404);
      }
      if (request.method == 'PATCH' && request.url.path == '/tasks/task-a') {
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        final title = staleTitle ? 'Старое имя' : body['title'] as String;
        return jsonUtf8Response({
          'object': graphObjectJson(id: 'task-a', title: title),
          'changed': true,
        });
      }
      if (request.url.path == '/objects/task-a') {
        return jsonUtf8Response(graphObjectJson(id: 'task-a', title: 'Старое имя'));
      }
      if (request.url.path == '/objects/task-a/neighbors') {
        return jsonUtf8Response({'object_id': 'task-a', 'neighbors': []});
      }
      if (request.url.path == '/objects/task-a/context') {
        return jsonUtf8Response({
          'object': graphObjectJson(id: 'task-a', title: 'Старое имя'),
          'edges': [],
          'neighbors': [],
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
      return jsonUtf8Response({}, statusCode: 404);
    }),
  );
}
