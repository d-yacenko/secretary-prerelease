import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';
import 'package:personal_secretary/assistant/fake_voice_recorder.dart';
import 'package:personal_secretary/assistant/voice_temp_files.dart';
import 'package:personal_secretary/graph/graph_layout.dart';
import 'package:personal_secretary/graph/graph_workspace_controller.dart';
import 'package:personal_secretary/graph/graph_workspace_screen.dart';

import 'graph_test_harness.dart';

void main() {
  final sizes = <Size>[
    const Size(320, 640),
    const Size(360, 800),
    const Size(393, 852),
    const Size(1280, 800),
  ];

  for (final size in sizes) {
    testWidgets('graph screen smoke at ${size.width}x${size.height}', (tester) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final harness = GraphTestHarness(overviewMock());
      harness.configure();
      await openGraph(tester, harness);

      expect(find.byType(GraphWorkspaceScreen), findsOneWidget);
      expect(find.text('Graph task'), findsOneWidget);
      expect(find.byTooltip('Уместить граф'), findsOneWidget);
      expect(find.byType(TextField), findsOneWidget);

      harness.graph.selectObject('task-1');
      await tester.pump();

      expect(harness.graph.selectedObjectId, 'task-1');
      expect(find.text('Спросить секретаря'), findsOneWidget);
      expect(find.text('Показать связи'), findsOneWidget);

      if (size.width < 900) {
        expect(find.byType(FloatingActionButton), findsNothing);
        expect(find.byTooltip('Задача'), findsOneWidget);
      }

      await tester.tap(find.byTooltip('Уместить граф'));
      await tester.pumpAndSettle();
    });
  }

  testWidgets('search result performs true re-root', (tester) async {
    tester.view.physicalSize = const Size(360, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = GraphTestHarness(
      MockClient((request) async {
        if (request.url.path == '/notifications') {
          return http.Response(jsonEncode({'notifications': []}), 200);
        }
        if (request.url.path == '/today') {
          return http.Response(
            jsonEncode({
              'date': '2026-08-28',
              'timezone': 'Europe/Amsterdam',
              'day_start': '2026-08-28T00:00:00+02:00',
              'tasks': [],
              'calendar_events': [],
              'notifications': [],
            }),
            200,
          );
        }
        if (request.url.path == '/graph/workspace') {
          final root = request.url.queryParameters['root_id'];
          if (root == 'search-root') {
            return http.Response(
              jsonEncode(
                graphWorkspaceJson(
                  rootId: 'search-root',
                  nodes: [graphObjectJson(id: 'search-root', title: 'Search hit')],
                ),
              ),
              200,
            );
          }
          return http.Response(
            jsonEncode(
              graphWorkspaceJson(
                nodes: [graphObjectJson(id: 'old-node', title: 'Old node')],
              ),
            ),
            200,
          );
        }
        if (request.url.path == '/search') {
          return http.Response(
            jsonEncode([
              graphObjectJson(id: 'search-root', title: 'Search hit'),
            ]),
            200,
          );
        }
        return http.Response('{}', 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);

    expect(find.text('Old node'), findsOneWidget);

    await tester.enterText(find.byType(TextField), 'hit');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();

    await tester.tap(find.text('Search hit'));
    await tester.pumpAndSettle();

    expect(harness.graph.rootId, 'search-root');
    expect(harness.graph.selectedObjectId, 'search-root');
    expect(find.text('Old node'), findsNothing);
    expect(find.text('Search hit'), findsWidgets);
  });

  testWidgets('truncated indicator visible', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = GraphTestHarness(overviewMock(truncated: true));
    harness.configure();
    await openGraph(tester, harness);

    expect(
      find.text('Некоторые связанные объекты скрыты лимитом рабочей области.'),
      findsOneWidget,
    );
  });

  testWidgets('large canvas stays unconstrained and distant node reachable after fit at 320x640',
      (tester) async {
    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final nodes = List.generate(
      12,
      (index) => graphObjectJson(id: 'wide-$index', title: 'Wide graph $index'),
    );
    final harness = GraphTestHarness(
      MockClient((request) async {
        if (request.url.path == '/notifications') {
          return http.Response(jsonEncode({'notifications': []}), 200);
        }
        if (request.url.path == '/today') {
          return http.Response(
            jsonEncode({
              'date': '2026-08-28',
              'timezone': 'Europe/Amsterdam',
              'day_start': '2026-08-28T00:00:00+02:00',
              'tasks': [],
              'calendar_events': [],
              'notifications': [],
            }),
            200,
          );
        }
        if (request.url.path == '/graph/workspace') {
          return http.Response(
            jsonEncode(graphWorkspaceJson(nodes: nodes)),
            200,
          );
        }
        return http.Response('{}', 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);

    final viewer = tester.widget<InteractiveViewer>(find.byType(InteractiveViewer));
    expect(viewer.constrained, isFalse);
    expect(viewer.minScale, kGraphMinScale);
    expect(viewer.maxScale, kGraphMaxScale);

    final viewerBox = tester.renderObject<RenderBox>(find.byType(InteractiveViewer));
    final viewportWidth = viewerBox.size.width;
    final viewportHeight = viewerBox.size.height;
    expect(viewportWidth, greaterThan(0));

    final canvasFinder = find.descendant(
      of: find.byType(InteractiveViewer),
      matching: find.byWidgetPredicate(
        (widget) => widget is SizedBox && widget.child is Stack,
      ),
    );
    final canvasSize = tester.getSize(canvasFinder);
    expect(canvasSize.width, greaterThan(viewportWidth));
    // Isolated overview nodes pack horizontally; height may stay compact.

    expect(harness.graph.selectedObjectId, isNull);

    await tester.tap(find.byTooltip('Уместить граф'));
    await tester.pumpAndSettle();

    final distantNode = find.text('Wide graph 11');
    await tester.ensureVisible(distantNode);
    await tester.tap(distantNode);
    await tester.pumpAndSettle();

    expect(harness.graph.selectedObjectId, 'wide-11');
  });

  testWidgets('Details edit refreshes rooted workspace', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var graphCalls = 0;
    var rootedRefreshed = false;
    final harness = GraphTestHarness(
      MockClient((request) async {
        if (request.url.path == '/notifications') {
          return http.Response(jsonEncode({'notifications': []}), 200);
        }
        if (request.url.path == '/today') {
          return http.Response(
            jsonEncode({
              'date': '2026-08-28',
              'timezone': 'Europe/Amsterdam',
              'day_start': '2026-08-28T00:00:00+02:00',
              'tasks': [],
              'calendar_events': [],
              'notifications': [],
            }),
            200,
          );
        }
        if (request.url.path == '/graph/workspace') {
          graphCalls += 1;
          final root = request.url.queryParameters['root_id'];
          if (root == 'task-a') {
            return http.Response(
              jsonEncode(
                graphWorkspaceJson(
                  rootId: 'task-a',
                  nodes: [
                    graphObjectJson(
                      id: 'task-a',
                      title: rootedRefreshed ? 'Renamed A' : 'Task A',
                    ),
                  ],
                ),
              ),
              200,
            );
          }
          return http.Response(
            jsonEncode(
              graphWorkspaceJson(
                nodes: [graphObjectJson(id: 'task-a', title: 'Task A')],
              ),
            ),
            200,
          );
        }
        if (request.url.path == '/objects/task-a') {
          return http.Response(
            jsonEncode(graphObjectJson(id: 'task-a', title: 'Task A')),
            200,
          );
        }
        if (request.url.path == '/objects/task-a/neighbors') {
          return http.Response(
            jsonEncode({'object_id': 'task-a', 'neighbors': []}),
            200,
          );
        }
        if (request.url.path == '/objects/task-a/context') {
          return http.Response(
            jsonEncode({
              'object': graphObjectJson(id: 'task-a', title: 'Task A'),
              'edges': [],
              'neighbors': [],
            }),
            200,
          );
        }
        if (request.method == 'PATCH' && request.url.path == '/tasks/task-a') {
          rootedRefreshed = true;
          return http.Response(
            jsonEncode({
              'object': graphObjectJson(id: 'task-a', title: 'Renamed A'),
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);

    await harness.graph.reRoot('task-a');
    await tester.pumpAndSettle();

    harness.graph.selectObject('task-a');
    await tester.pump();

    await tester.tap(find.text('Подробнее'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Редактировать'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, 'Renamed A');
    await tester.tap(find.text('Сохранить'));
    await tester.pumpAndSettle();

    await tester.pageBack();
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));

    expect(harness.graph.rootId, 'task-a');
    expect(find.text('Renamed A'), findsWidgets);
    expect(graphCalls, greaterThanOrEqualTo(3));
  });

  testWidgets('Details delete refreshes overview without deleted task', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var overviewCalls = 0;
    final harness = GraphTestHarness(
      MockClient((request) async {
        if (request.url.path == '/notifications') {
          return http.Response(jsonEncode({'notifications': []}), 200);
        }
        if (request.url.path == '/today') {
          return http.Response(
            jsonEncode({
              'date': '2026-08-28',
              'timezone': 'Europe/Amsterdam',
              'day_start': '2026-08-28T00:00:00+02:00',
              'tasks': [],
              'calendar_events': [],
              'notifications': [],
            }),
            200,
          );
        }
        if (request.url.path == '/graph/workspace' &&
            request.url.queryParameters['root_id'] == null) {
          overviewCalls += 1;
          final nodes = overviewCalls == 1
              ? [
                  graphObjectJson(id: 'task-a', title: 'Task A'),
                  graphObjectJson(id: 'task-b', title: 'Task B'),
                ]
              : [graphObjectJson(id: 'task-b', title: 'Task B')];
          return http.Response(jsonEncode(graphWorkspaceJson(nodes: nodes)), 200);
        }
        if (request.url.path == '/objects/task-a') {
          return http.Response(
            jsonEncode(graphObjectJson(id: 'task-a', title: 'Task A')),
            200,
          );
        }
        if (request.url.path == '/objects/task-a/neighbors') {
          return http.Response(
            jsonEncode({'object_id': 'task-a', 'neighbors': []}),
            200,
          );
        }
        if (request.url.path == '/objects/task-a/context') {
          return http.Response(
            jsonEncode({
              'object': graphObjectJson(id: 'task-a', title: 'Task A'),
              'edges': [],
              'neighbors': [],
            }),
            200,
          );
        }
        if (request.method == 'DELETE' && request.url.path == '/tasks/task-a') {
          return http.Response(
            jsonEncode({
              'object': graphObjectJson(id: 'task-a', title: 'Task A', status: 'deleted'),
              'new_status': 'deleted',
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);

    harness.graph.selectObject('task-a');
    await tester.pump();

    await tester.tap(find.text('Подробнее'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Удалить'));
    await tester.pumpAndSettle();
    await tester.tap(
      find.descendant(
        of: find.byType(AlertDialog),
        matching: find.widgetWithText(FilledButton, 'Удалить'),
      ),
    );
    await tester.pumpAndSettle();

    await tester.pageBack();
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));

    expect(harness.graph.rootId, isNull);
    expect(find.text('Task A'), findsNothing);
    expect(find.text('Task B'), findsOneWidget);
    expect(overviewCalls, greaterThanOrEqualTo(2));
  });

  testWidgets('Details delete current root falls back to overview', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var rootedCalls = 0;
    var overviewCalls = 0;
    final harness = GraphTestHarness(
      MockClient((request) async {
        if (request.url.path == '/notifications') {
          return http.Response(jsonEncode({'notifications': []}), 200);
        }
        if (request.url.path == '/today') {
          return http.Response(
            jsonEncode({
              'date': '2026-08-28',
              'timezone': 'Europe/Amsterdam',
              'day_start': '2026-08-28T00:00:00+02:00',
              'tasks': [],
              'calendar_events': [],
              'notifications': [],
            }),
            200,
          );
        }
        if (request.url.path == '/graph/workspace') {
          final root = request.url.queryParameters['root_id'];
          if (root == 'task-a') {
            rootedCalls += 1;
            if (rootedCalls == 1) {
              return http.Response(
                jsonEncode(
                  graphWorkspaceJson(
                    rootId: 'task-a',
                    nodes: [graphObjectJson(id: 'task-a', title: 'Task A')],
                  ),
                ),
                200,
              );
            }
            return http.Response('{"detail":"not found"}', 404);
          }
          overviewCalls += 1;
          final nodes = overviewCalls == 1
              ? [graphObjectJson(id: 'task-a', title: 'Task A')]
              : [graphObjectJson(id: 'task-b', title: 'Task B')];
          return http.Response(jsonEncode(graphWorkspaceJson(nodes: nodes)), 200);
        }
        if (request.url.path == '/objects/task-a') {
          return http.Response(
            jsonEncode(graphObjectJson(id: 'task-a', title: 'Task A')),
            200,
          );
        }
        if (request.url.path == '/objects/task-a/neighbors') {
          return http.Response(
            jsonEncode({'object_id': 'task-a', 'neighbors': []}),
            200,
          );
        }
        if (request.url.path == '/objects/task-a/context') {
          return http.Response(
            jsonEncode({
              'object': graphObjectJson(id: 'task-a', title: 'Task A'),
              'edges': [],
              'neighbors': [],
            }),
            200,
          );
        }
        if (request.method == 'DELETE' && request.url.path == '/tasks/task-a') {
          return http.Response(
            jsonEncode({
              'object': graphObjectJson(id: 'task-a', title: 'Task A', status: 'deleted'),
              'new_status': 'deleted',
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);

    await harness.graph.reRoot('task-a');
    await tester.pumpAndSettle();

    harness.graph.selectObject('task-a');
    await tester.pump();

    await tester.tap(find.text('Подробнее'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Удалить'));
    await tester.pumpAndSettle();
    await tester.tap(
      find.descendant(
        of: find.byType(AlertDialog),
        matching: find.widgetWithText(FilledButton, 'Удалить'),
      ),
    );
    await tester.pumpAndSettle();

    await tester.pageBack();
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));

    expect(harness.graph.rootId, isNull);
    expect(find.text('Task A'), findsNothing);
    expect(find.text('Task B'), findsOneWidget);
    expect(rootedCalls, 1);
    expect(overviewCalls, greaterThanOrEqualTo(2));
  });

  testWidgets('Details Ask Secretary does not refresh disposed Graph screen', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var graphCalls = 0;
    final harness = GraphTestHarness(
      MockClient((request) async {
        if (request.url.path == '/notifications') {
          return http.Response(jsonEncode({'notifications': []}), 200);
        }
        if (request.url.path == '/today') {
          return http.Response(
            jsonEncode({
              'date': '2026-08-28',
              'timezone': 'Europe/Amsterdam',
              'day_start': '2026-08-28T00:00:00+02:00',
              'tasks': [],
              'calendar_events': [],
              'notifications': [],
            }),
            200,
          );
        }
        if (request.url.path == '/graph/workspace') {
          graphCalls += 1;
          return http.Response(
            jsonEncode(
              graphWorkspaceJson(
                nodes: [graphObjectJson(id: 'task-a', title: 'Task A')],
              ),
            ),
            200,
          );
        }
        if (request.url.path == '/objects/task-a') {
          return http.Response(
            jsonEncode(graphObjectJson(id: 'task-a', title: 'Task A')),
            200,
          );
        }
        if (request.url.path == '/objects/task-a/neighbors') {
          return http.Response(
            jsonEncode({'object_id': 'task-a', 'neighbors': []}),
            200,
          );
        }
        if (request.url.path == '/objects/task-a/context') {
          return http.Response(
            jsonEncode({
              'object': graphObjectJson(id: 'task-a', title: 'Task A'),
              'edges': [],
              'neighbors': [],
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);

    harness.graph.selectObject('task-a');
    await tester.pump();

    await tester.tap(find.text('Подробнее'));
    await tester.pumpAndSettle();

    final graphCallsBeforeAsk = graphCalls;

    await tester.tap(find.text('Спросить секретаря'));
    await tester.pumpAndSettle();

    expect(find.text('Секретарь'), findsWidgets);
    expect(harness.assistant.objectContext?.id, 'task-a');
    expect(graphCalls, graphCallsBeforeAsk);
    expect(find.byType(GraphWorkspaceScreen), findsNothing);
  });

  testWidgets('desktop graph type filter uses anchored menu and sends kind=task', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    String? searchKind;
    final harness = GraphTestHarness(
      MockClient((request) async {
        if (request.url.path == '/notifications') {
          return http.Response(jsonEncode({'notifications': []}), 200);
        }
        if (request.url.path == '/today') {
          return http.Response(
            jsonEncode({
              'date': '2026-08-28',
              'timezone': 'Europe/Amsterdam',
              'day_start': '2026-08-28T00:00:00+02:00',
              'tasks': [],
              'calendar_events': [],
              'notifications': [],
            }),
            200,
          );
        }
        if (request.url.path == '/graph/workspace') {
          return http.Response(
            jsonEncode(
              graphWorkspaceJson(
                nodes: [graphObjectJson(id: 'task-1', title: 'Graph task')],
              ),
            ),
            200,
          );
        }
        if (request.url.path == '/search/facets') {
          return http.Response(
            jsonEncode({
              'kinds': [
                {'value': 'task', 'count': 1},
                {'value': 'email', 'count': 1},
              ],
              'providers': [
                {'value': 'gmail', 'count': 1},
              ],
            }),
            200,
          );
        }
        if (request.url.path == '/search') {
          searchKind = request.url.queryParameters['kind'];
          expect(request.url.queryParameters['sort'], 'relevance');
          return http.Response('[]', 200);
        }
        return http.Response('{}', 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);

    await tester.enterText(find.byType(TextField), 'graph');
    await tester.tap(find.bySemanticsLabel('Фильтр типа: Все типы'));
    await tester.pumpAndSettle();
    expect(find.byType(BottomSheet), findsNothing);
    await tester.tap(find.ancestor(
      of: find.text('Задача'),
      matching: find.byType(MenuItemButton),
    ));
    await tester.pumpAndSettle();

    expect(searchKind, 'task');
  });

  testWidgets('desktop graph provider filter uses anchored menu and sends provider=gmail', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    String? searchProvider;
    final harness = GraphTestHarness(
      MockClient((request) async {
        if (request.url.path == '/notifications') {
          return http.Response(jsonEncode({'notifications': []}), 200);
        }
        if (request.url.path == '/today') {
          return http.Response(
            jsonEncode({
              'date': '2026-08-28',
              'timezone': 'Europe/Amsterdam',
              'day_start': '2026-08-28T00:00:00+02:00',
              'tasks': [],
              'calendar_events': [],
              'notifications': [],
            }),
            200,
          );
        }
        if (request.url.path == '/graph/workspace') {
          return http.Response(
            jsonEncode(
              graphWorkspaceJson(
                nodes: [graphObjectJson(id: 'task-1', title: 'Graph task')],
              ),
            ),
            200,
          );
        }
        if (request.url.path == '/search/facets') {
          return http.Response(
            jsonEncode({
              'kinds': [
                {'value': 'task', 'count': 1},
              ],
              'providers': [
                {'value': 'gmail', 'count': 1},
                {'value': 'local_device', 'count': 1},
              ],
            }),
            200,
          );
        }
        if (request.url.path == '/search') {
          searchProvider = request.url.queryParameters['provider'];
          expect(request.url.queryParameters['sort'], 'relevance');
          return http.Response('[]', 200);
        }
        return http.Response('{}', 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);

    await tester.enterText(find.byType(TextField), 'mail');
    await tester.tap(find.bySemanticsLabel('Фильтр источника: Все источники'));
    await tester.pumpAndSettle();
    expect(find.byType(BottomSheet), findsNothing);
    await tester.tap(find.ancestor(
      of: find.text('Gmail'),
      matching: find.byType(MenuItemButton),
    ));
    await tester.pumpAndSettle();

    expect(searchProvider, 'gmail');
  });

  testWidgets('display kind filter hides non-matching loaded nodes', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = GraphTestHarness(
      MockClient((request) async {
        if (request.url.path == '/notifications') {
          return http.Response(jsonEncode({'notifications': []}), 200);
        }
        if (request.url.path == '/today') {
          return http.Response(
            jsonEncode({
              'date': '2026-08-28',
              'timezone': 'Europe/Amsterdam',
              'day_start': '2026-08-28T00:00:00+02:00',
              'tasks': [],
              'calendar_events': [],
              'notifications': [],
            }),
            200,
          );
        }
        if (request.url.path == '/graph/workspace') {
          return http.Response(
            jsonEncode(
              graphWorkspaceJson(
                nodes: [
                  graphObjectJson(
                    id: 'task-local',
                    title: 'Local task',
                    kind: 'task',
                    provider: 'local',
                  ),
                  graphObjectJson(
                    id: 'email-yandex',
                    title: 'Yandex mail',
                    kind: 'email',
                    provider: 'yandex_mail',
                  ),
                  graphObjectJson(
                    id: 'email-gmail',
                    title: 'Gmail mail',
                    kind: 'email',
                    provider: 'gmail',
                  ),
                ],
              ),
            ),
            200,
          );
        }
        if (request.url.path == '/search/facets') {
          return http.Response(
            jsonEncode({
              'kinds': [
                {'value': 'task', 'count': 1},
                {'value': 'email', 'count': 2},
              ],
              'providers': [
                {'value': 'gmail', 'count': 1},
                {'value': 'yandex_mail', 'count': 1},
              ],
            }),
            200,
          );
        }
        return http.Response('{}', 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);

    expect(find.text('Local task'), findsOneWidget);
    expect(find.text('Gmail mail'), findsOneWidget);
    expect(find.text('Yandex mail'), findsOneWidget);

    await tester.tap(find.bySemanticsLabel('Фильтр типа: Все типы'));
    await tester.pumpAndSettle();
    await tester.tap(find.ancestor(
      of: find.text('Письмо'),
      matching: find.byType(MenuItemButton),
    ));
    await tester.pumpAndSettle();

    expect(find.text('Local task'), findsNothing);
    expect(find.text('Gmail mail'), findsOneWidget);
    expect(find.text('Yandex mail'), findsOneWidget);

    await tester.tap(find.bySemanticsLabel('Фильтр источника: Все источники'));
    await tester.pumpAndSettle();
    await tester.tap(find.ancestor(
      of: find.text('Gmail'),
      matching: find.byType(MenuItemButton),
    ));
    await tester.pumpAndSettle();

    expect(find.text('Yandex mail'), findsNothing);
    expect(find.text('Gmail mail'), findsOneWidget);
  });

  testWidgets('graph detail preserves multiline object body', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final multilineBody = 'Первая строка\n\nВторой абзац\nТретья строка';
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
                  id: 'email-body',
                  title: 'Readable email',
                  kind: 'email',
                  provider: 'gmail',
                  body: multilineBody,
                ),
              ],
            ),
          );
        }
        if (request.url.path == '/objects/email-body') {
          return jsonUtf8Response(
            graphObjectJson(
              id: 'email-body',
              title: 'Readable email',
              kind: 'email',
              provider: 'gmail',
              body: multilineBody,
            ),
          );
        }
        if (request.url.path == '/search/facets') {
          return jsonUtf8Response({
            'kinds': [
              {'value': 'email', 'count': 1},
            ],
            'providers': [
              {'value': 'gmail', 'count': 1},
            ],
          });
        }
        return jsonUtf8Response({}, statusCode: 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);

    expect(harness.graph.loadState, GraphWorkspaceLoadState.ready);
    expect(harness.graph.nodes.length, 1);
    expect(harness.graph.nodes.first.body, multilineBody);

    await tester.tap(find.text('Readable email'));
    await tester.pumpAndSettle();

    expect(harness.graph.selectedObject?.body, multilineBody);
    expect(find.textContaining('Первая строка'), findsWidgets);
    expect(find.textContaining('Второй абзац'), findsWidgets);
  });
}
