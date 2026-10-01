import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets('search kind facet does not hide hybrid glyphs', (tester) async {
    await _pumpOverview(tester);
    final harness = _harness;
    final searches = _searches;
    final before = Offset(
      harness.graph.positions['publication']!.dx,
      harness.graph.positions['publication']!.dy,
    );
    expect(find.byKey(const ValueKey('hybrid-glyph-pdf')), findsOneWidget);
    expect(_hairlineToPdf(tester), isTrue);
    expect(find.text('Нет объектов по выбранным фильтрам'), findsNothing);

    await tester.enterText(find.byType(TextField), 'icdm');
    await _chooseKind(tester, 'Задача');

    expect(searches.single['kind'], 'task');
    expect(find.text('ICDM done'), findsOneWidget);
    expect(find.byKey(const ValueKey('hybrid-glyph-pdf')), findsOneWidget);
    expect(_hairlineToPdf(tester), isTrue);
    expect(
      harness.graph.visibleNodes.map((node) => node.id).toSet(),
      {'publication', 'pdf'},
    );
    expect(harness.graph.positions['publication'], before);
    expect(find.text('Нет объектов по выбранным фильтрам'), findsNothing);
  });

  testWidgets('provider facet is also search-only', (tester) async {
    await _pumpOverview(tester);
    final beforeIds = _harness.graph.visibleNodes.map((node) => node.id).toSet();
    expect(find.byKey(const ValueKey('hybrid-glyph-pdf')), findsOneWidget);

    await tester.enterText(find.byType(TextField), 'mail');
    await tester.tap(find.bySemanticsLabel('Источник в поиске: Все источники'));
    await tester.pumpAndSettle();
    await tester.tap(
      find.ancestor(of: find.text('Gmail'), matching: find.byType(MenuItemButton)),
    );
    await tester.pumpAndSettle();

    expect(_searches.single['provider'], 'gmail');
    expect(find.text('Gmail hit'), findsOneWidget);
    expect(_harness.graph.visibleNodes.map((node) => node.id).toSet(), beforeIds);
    expect(find.byKey(const ValueKey('hybrid-glyph-pdf')), findsOneWidget);
    expect(_hairlineToPdf(tester), isTrue);
  });

  testWidgets('selection is not cleared by a search facet', (tester) async {
    await _pumpOverview(tester);
    _harness.graph.selectObject('pdf');
    await tester.pumpAndSettle();
    expect(_harness.graph.selectedObjectId, 'pdf');

    await tester.enterText(find.byType(TextField), 'task');
    await _chooseKind(tester, 'Задача');

    expect(_harness.graph.selectedObjectId, 'pdf');
    expect(find.byKey(const ValueKey('hybrid-glyph-pdf')), findsOneWidget);
  });

  testWidgets('topology refresh keeps evidence while a search facet is active', (tester) async {
    await _pumpOverview(tester);
    await tester.enterText(find.byType(TextField), 'icdm');
    await _chooseKind(tester, 'Задача');
    expect(_harness.graph.searchKindFilter, 'task');

    await _harness.graph.applyCreatedRelation(
      sourceId: 'completed',
      sourceKind: 'task',
      edge: SecretaryEdge(
        id: 'edge-rejoin',
        sourceId: 'completed',
        targetId: 'publication',
        type: 'related_to',
        origin: 'user',
        state: 'confirmed',
        metadata: const {},
        createdAt: '2026-01-01T00:00:00Z',
        updatedAt: '2026-01-01T00:00:00Z',
      ),
    );
    await tester.pumpAndSettle();

    expect(_harness.graph.searchKindFilter, 'task');
    expect(
      _harness.graph.visibleNodes.map((node) => node.id).toSet(),
      containsAll(['publication', 'pdf']),
    );
    expect(find.byKey(const ValueKey('hybrid-glyph-pdf')), findsOneWidget);
    expect(find.text('Нет объектов по выбранным фильтрам'), findsNothing);
  });

  testWidgets('clearing the search facet does not change canvas membership', (tester) async {
    await _pumpOverview(tester);
    final before = _harness.graph.visibleNodes.map((node) => node.id).toSet();
    await tester.enterText(find.byType(TextField), 'icdm');
    await _chooseKind(tester, 'Задача');
    final afterFacet = _harness.graph.visibleNodes.map((node) => node.id).toSet();
    expect(afterFacet, before);

    await tester.tap(find.bySemanticsLabel('Тип в поиске: Задача'));
    await tester.pumpAndSettle();
    await tester.tap(
      find.ancestor(of: find.text('Все типы'), matching: find.byType(MenuItemButton)),
    );
    await tester.pumpAndSettle();

    expect(_searches.last.containsKey('kind'), isFalse);
    expect(_harness.graph.searchKindFilter, isNull);
    expect(_harness.graph.visibleNodes.map((node) => node.id).toSet(), before);
    expect(find.byKey(const ValueKey('hybrid-glyph-pdf')), findsOneWidget);
  });
}

late GraphTestHarness _harness;
final List<Map<String, String>> _searches = [];

Future<void> _pumpOverview(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1280, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  _searches.clear();
  _harness = GraphTestHarness(
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
              graphObjectJson(id: 'publication', title: 'Publication'),
              graphObjectJson(id: 'pdf', title: 'Program_DYSC.pdf', kind: 'file'),
            ],
            edges: [
              {
                'id': 'edge-pdf',
                'source_id': 'publication',
                'target_id': 'pdf',
                'type': 'references',
                'origin': 'user',
                'state': 'confirmed',
                'metadata': {},
                'created_at': '2026-01-01T00:00:00Z',
                'updated_at': '2026-01-01T00:00:00Z',
              },
            ],
          ),
        );
      }
      if (request.url.path == '/search/facets') {
        return jsonUtf8Response({
          'kinds': [
            {'value': 'task', 'count': 2},
            {'value': 'file', 'count': 1},
          ],
          'providers': [
            {'value': 'gmail', 'count': 1},
          ],
        });
      }
      if (request.url.path == '/search') {
        final params = request.url.queryParameters;
        _searches.add(Map<String, String>.from(params));
        if (params['kind'] == 'task') {
          return jsonUtf8Response([
            graphObjectJson(id: 'completed', title: 'ICDM done', status: 'done'),
          ]);
        }
        if (params['provider'] == 'gmail') {
          return jsonUtf8Response([
            graphObjectJson(
              id: 'mail',
              title: 'Gmail hit',
              kind: 'email',
              provider: 'gmail',
            ),
          ]);
        }
        return jsonUtf8Response([
          graphObjectJson(id: 'broad', title: 'Broad hit', kind: 'file'),
        ]);
      }
      return jsonUtf8Response({}, statusCode: 404);
    }),
  );
  _harness.configure();
  await openGraph(tester, _harness);
}

Future<void> _chooseKind(WidgetTester tester, String label) async {
  await tester.tap(find.bySemanticsLabel('Тип в поиске: Все типы'));
  await tester.pumpAndSettle();
  await tester.tap(
    find.ancestor(of: find.text(label), matching: find.byType(MenuItemButton)),
  );
  await tester.pumpAndSettle();
}

bool _hairlineToPdf(WidgetTester tester) {
  for (final paint in tester.widgetList<CustomPaint>(find.byType(CustomPaint))) {
    final painter = paint.painter;
    if (painter == null || painter.runtimeType.toString() != 'HybridHairlinePainter') {
      continue;
    }
    final hairlines = (painter as dynamic).hairlines as List<dynamic>;
    if (hairlines.any((hairline) => hairline.markId == 'pdf')) {
      return true;
    }
  }
  return false;
}
