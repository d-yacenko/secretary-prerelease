import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/ui/passive_snapshot_refresh.dart';

void main() {
  setUp(() {
    WidgetsFlutterBinding.ensureInitialized();
  });

  test('runs periodic callback on interval', () async {
    var count = 0;
    final refresh = PassiveSnapshotRefresh(
      interval: const Duration(milliseconds: 40),
      isPaused: () => false,
      onRefresh: () async {
        count++;
      },
    );
    refresh.attach();
    await Future<void>.delayed(const Duration(milliseconds: 120));
    refresh.dispose();
    expect(count, greaterThanOrEqualTo(2));
  });

  test('paused tick skips callback but polling survives', () async {
    var paused = true;
    var count = 0;
    final refresh = PassiveSnapshotRefresh(
      interval: const Duration(milliseconds: 40),
      isPaused: () => paused,
      onRefresh: () async {
        count++;
      },
    );
    refresh.attach();
    await Future<void>.delayed(const Duration(milliseconds: 60));
    expect(count, 0);

    paused = false;
    await Future<void>.delayed(const Duration(milliseconds: 80));
    refresh.dispose();
    expect(count, greaterThanOrEqualTo(1));
  });

  test('after unpause a later tick runs callback', () async {
    var paused = true;
    var count = 0;
    final refresh = PassiveSnapshotRefresh(
      interval: const Duration(milliseconds: 30),
      isPaused: () => paused,
      onRefresh: () async {
        count++;
      },
    );
    refresh.attach();
    await Future<void>.delayed(const Duration(milliseconds: 50));
    paused = false;
    await Future<void>.delayed(const Duration(milliseconds: 90));
    refresh.dispose();
    expect(count, greaterThanOrEqualTo(2));
  });

  test('does not run concurrent callbacks', () async {
    var inProgress = false;
    var overlaps = 0;
    final refresh = PassiveSnapshotRefresh(
      interval: const Duration(milliseconds: 20),
      isPaused: () => false,
      onRefresh: () async {
        if (inProgress) {
          overlaps++;
        }
        inProgress = true;
        await Future<void>.delayed(const Duration(milliseconds: 80));
        inProgress = false;
      },
    );
    refresh.attach();
    await Future<void>.delayed(const Duration(milliseconds: 200));
    refresh.dispose();
    expect(overlaps, 0);
  });

  test('inactive does not stop periodic refresh', () async {
    var count = 0;
    final refresh = PassiveSnapshotRefresh(
      interval: const Duration(milliseconds: 40),
      isPaused: () => false,
      onRefresh: () async {
        count++;
      },
    );
    refresh.attach();
    await Future<void>.delayed(const Duration(milliseconds: 50));
    refresh.didChangeAppLifecycleState(AppLifecycleState.inactive);
    await Future<void>.delayed(const Duration(milliseconds: 120));
    refresh.dispose();
    expect(count, greaterThanOrEqualTo(2));
  });

  test('inactive across multiple intervals keeps callbacks running', () async {
    var count = 0;
    final refresh = PassiveSnapshotRefresh(
      interval: const Duration(milliseconds: 30),
      isPaused: () => false,
      onRefresh: () async {
        count++;
      },
    );
    refresh.attach();
    refresh.didChangeAppLifecycleState(AppLifecycleState.inactive);
    await Future<void>.delayed(const Duration(milliseconds: 150));
    refresh.dispose();
    expect(count, greaterThanOrEqualTo(3));
  });

  test('hidden stops polling until resumed', () async {
    var count = 0;
    final refresh = PassiveSnapshotRefresh(
      interval: const Duration(milliseconds: 40),
      isPaused: () => false,
      onRefresh: () async {
        count++;
      },
    );
    refresh.attach();
    await Future<void>.delayed(const Duration(milliseconds: 50));
    refresh.didChangeAppLifecycleState(AppLifecycleState.hidden);
    final hiddenCount = count;
    await Future<void>.delayed(const Duration(milliseconds: 120));
    expect(count, hiddenCount);

    refresh.didChangeAppLifecycleState(AppLifecycleState.resumed);
    await Future<void>.delayed(const Duration(milliseconds: 80));
    refresh.dispose();
    expect(count, greaterThan(hiddenCount));
  });

  test('hidden then resumed performs immediate refresh and restarts timer',
      () async {
    var count = 0;
    final refresh = PassiveSnapshotRefresh(
      interval: const Duration(milliseconds: 200),
      isPaused: () => false,
      onRefresh: () async {
        count++;
      },
    );
    refresh.attach();
    await Future<void>.delayed(const Duration(milliseconds: 20));
    final beforeHidden = count;

    refresh.didChangeAppLifecycleState(AppLifecycleState.hidden);
    await Future<void>.delayed(const Duration(milliseconds: 50));
    expect(count, beforeHidden);

    refresh.didChangeAppLifecycleState(AppLifecycleState.resumed);
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(count, greaterThan(beforeHidden));

    await Future<void>.delayed(const Duration(milliseconds: 220));
    refresh.dispose();
    expect(count, greaterThanOrEqualTo(beforeHidden + 2));
  });

  test('lifecycle pause stops polling and resume restarts refresh', () async {
    var count = 0;
    final refresh = PassiveSnapshotRefresh(
      interval: const Duration(milliseconds: 40),
      isPaused: () => false,
      onRefresh: () async {
        count++;
      },
    );
    refresh.attach();
    await Future<void>.delayed(const Duration(milliseconds: 50));
    refresh.didChangeAppLifecycleState(AppLifecycleState.paused);
    final pausedCount = count;
    await Future<void>.delayed(const Duration(milliseconds: 80));
    expect(count, pausedCount);

    refresh.didChangeAppLifecycleState(AppLifecycleState.resumed);
    await Future<void>.delayed(const Duration(milliseconds: 80));
    refresh.dispose();
    expect(count, greaterThan(pausedCount));
  });

  test('manual refresh pause and inactive does not permanently stop polling',
      () async {
    var sourceRefreshing = true;
    var count = 0;
    final refresh = PassiveSnapshotRefresh(
      interval: const Duration(milliseconds: 40),
      isPaused: () => sourceRefreshing,
      onRefresh: () async {
        count++;
      },
    );
    refresh.attach();
    await Future<void>.delayed(const Duration(milliseconds: 60));
    refresh.didChangeAppLifecycleState(AppLifecycleState.inactive);
    await Future<void>.delayed(const Duration(milliseconds: 80));
    expect(count, 0);

    sourceRefreshing = false;
    await Future<void>.delayed(const Duration(milliseconds: 120));
    refresh.dispose();
    expect(count, greaterThanOrEqualTo(1));
  });

  test('dispose stops future callbacks', () async {
    var count = 0;
    final refresh = PassiveSnapshotRefresh(
      interval: const Duration(milliseconds: 30),
      isPaused: () => false,
      onRefresh: () async {
        count++;
      },
    );
    refresh.attach();
    await Future<void>.delayed(const Duration(milliseconds: 40));
    final beforeDispose = count;
    refresh.dispose();
    await Future<void>.delayed(const Duration(milliseconds: 80));
    expect(count, beforeDispose);
  });
}
