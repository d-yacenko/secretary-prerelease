import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/account/client_disconnect.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/auth/auth_controller.dart';
import 'package:personal_secretary/auth/server_url_store.dart';
import 'package:personal_secretary/auth/token_store.dart';

class _CountingTokenStore implements TokenStore {
  String? token = 'opaque-test-token';
  int deletes = 0;

  @override
  Future<String?> readToken() async => token;

  @override
  Future<void> writeToken(String value) async {
    token = value;
  }

  @override
  Future<void> deleteToken() async {
    deletes += 1;
    token = null;
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late List<http.Request> apiCalls;
  late _CountingTokenStore tokens;
  late AuthController auth;

  Widget harness({required Widget child}) {
    return MaterialApp(
      home: Scaffold(
        body: ListView(
          children: [
            FilledButton(onPressed: () {}, child: const Text('Сохранить имя')),
            child,
          ],
        ),
      ),
    );
  }

  setUp(() {
    apiCalls = [];
    tokens = _CountingTokenStore();
    final apiClient = SecretaryApiClient(
      httpClient: MockClient((request) async {
        apiCalls.add(request);
        return http.Response('{}', 404);
      }),
    );
    auth = AuthController(
      apiClient: apiClient,
      tokenStore: tokens,
      serverUrlStore: FakeServerUrlStore(),
    );
    auth.status = AuthStatus.authenticated;
    auth.user = UserMe(
      id: 'user-1',
      displayName: 'Alice',
      createdAt: '2026-01-01T00:00:00Z',
    );
  });

  Future<void> pumpControl(WidgetTester tester) async {
    await tester.pumpWidget(
      harness(child: ClientDisconnectControl(authController: auth)),
    );
  }

  test('confirmation matcher is exact lowercase delete', () {
    expect(clientDisconnectConfirmationMatches('delete'), isTrue);
    expect(clientDisconnectConfirmationMatches('DELETE'), isFalse);
    expect(clientDisconnectConfirmationMatches('Delete'), isFalse);
    expect(clientDisconnectConfirmationMatches('delete '), isFalse);
    expect(clientDisconnectConfirmationMatches(' delete'), isFalse);
    expect(clientDisconnectConfirmationMatches(''), isFalse);
  });

  testWidgets('destructive disconnect is separate from save controls', (
    tester,
  ) async {
    await pumpControl(tester);
    expect(find.text('Отключить этот клиент'), findsOneWidget);
    expect(find.text('Забыть токен / отключить клиент'), findsNothing);
    final disconnect = tester.widget<OutlinedButton>(
      find.byKey(const Key('client_disconnect_button')),
    );
    final scheme = Theme.of(
      tester.element(find.byKey(const Key('client_disconnect_button'))),
    ).colorScheme;
    expect(disconnect.style?.foregroundColor?.resolve({}), scheme.error);
    expect(find.widgetWithText(FilledButton, 'Сохранить имя'), findsOneWidget);
    expect(
      find.text(
        'Удалит сохранённый токен на этом устройстве. Данные на сервере не удаляются.',
      ),
      findsOneWidget,
    );
  });

  testWidgets('first click opens dialog and does not forget the token', (
    tester,
  ) async {
    await pumpControl(tester);
    await tester.tap(find.byKey(const Key('client_disconnect_button')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('client_disconnect_dialog')), findsOneWidget);
    expect(tokens.deletes, 0);
    expect(auth.status, AuthStatus.authenticated);
  });

  testWidgets('confirm stays disabled until exact delete', (tester) async {
    await pumpControl(tester);
    await tester.tap(find.byKey(const Key('client_disconnect_button')));
    await tester.pumpAndSettle();

    OutlinedButton confirm() {
      return tester.widget<OutlinedButton>(
        find.byKey(const Key('client_disconnect_confirm')),
      );
    }

    expect(confirm().onPressed, isNull);

    await tester.enterText(
      find.byKey(const Key('client_disconnect_confirm_field')),
      'DELETE',
    );
    await tester.pump();
    expect(confirm().onPressed, isNull);

    await tester.enterText(
      find.byKey(const Key('client_disconnect_confirm_field')),
      'Delete',
    );
    await tester.pump();
    expect(confirm().onPressed, isNull);

    await tester.enterText(
      find.byKey(const Key('client_disconnect_confirm_field')),
      'delete ',
    );
    await tester.pump();
    expect(confirm().onPressed, isNull);

    await tester.enterText(
      find.byKey(const Key('client_disconnect_confirm_field')),
      'delete',
    );
    await tester.pump();
    expect(confirm().onPressed, isNotNull);
    expect(tokens.deletes, 0);
  });

  testWidgets('Cancel does not forget the token', (tester) async {
    await pumpControl(tester);
    await tester.tap(find.byKey(const Key('client_disconnect_button')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('client_disconnect_cancel')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('client_disconnect_dialog')), findsNothing);
    expect(tokens.deletes, 0);
    expect(auth.status, AuthStatus.authenticated);
  });

  testWidgets('Escape dismisses without forgetting the token', (tester) async {
    await pumpControl(tester);
    await tester.tap(find.byKey(const Key('client_disconnect_button')));
    await tester.pumpAndSettle();
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('client_disconnect_dialog')), findsNothing);
    expect(tokens.deletes, 0);
  });

  testWidgets('exact delete plus confirm forgets the token once', (
    tester,
  ) async {
    var popped = false;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) {
            return Scaffold(
              body: Center(
                child: FilledButton(
                  onPressed: () {
                    Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (_) => Scaffold(
                          body: ClientDisconnectControl(authController: auth),
                        ),
                      ),
                    );
                  },
                  child: const Text('open-account'),
                ),
              ),
            );
          },
        ),
      ),
    );
    await tester.tap(find.text('open-account'));
    await tester.pumpAndSettle();
    auth.onSessionTerminated = () {
      popped = true;
    };

    await tester.tap(find.byKey(const Key('client_disconnect_button')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('client_disconnect_confirm_field')),
      'delete',
    );
    await tester.pump();
    await tester.tap(find.byKey(const Key('client_disconnect_confirm')));
    await tester.pumpAndSettle();

    expect(tokens.deletes, 1);
    expect(tokens.token, isNull);
    expect(auth.status, AuthStatus.needsAuth);
    expect(find.text('Отключить этот клиент'), findsNothing);
    expect(popped, isTrue);
    expect(apiCalls, isEmpty);
  });
}
