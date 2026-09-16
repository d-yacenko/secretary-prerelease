import 'package:flutter/material.dart';

import '../api/secretary_api_client.dart';
import '../assistant/assistant_controller.dart';
import '../auth/auth_controller.dart';
import '../capture/capture_controller.dart';
import '../navigation/secretary_navigation.dart';
import '../ui/object_bookmark_controller.dart';
import '../ui/passive_snapshot_refresh.dart';
import 'today_screen.dart';
import 'week_screen.dart';

enum TemporalMode { today, week }

class TemporalArea extends StatefulWidget {
  const TemporalArea({
    super.key,
    required this.apiClient,
    required this.authController,
    required this.captureController,
    this.assistantController,
    this.onAskSecretary,
    this.onShowInGraph,
    this.passiveRefreshInterval = kPassiveSnapshotRefreshInterval,
    this.now,
    this.clockTick = const Duration(minutes: 1),
    this.bookmarkController,
  });

  final SecretaryApiClient apiClient;
  final AuthController authController;
  final CaptureController captureController;
  final AssistantController? assistantController;
  final AskSecretaryHandler? onAskSecretary;
  final ShowInGraphHandler? onShowInGraph;
  final Duration passiveRefreshInterval;
  final DateTime Function()? now;
  final Duration clockTick;
  final ObjectBookmarkController? bookmarkController;

  @override
  State<TemporalArea> createState() => _TemporalAreaState();
}

class _TemporalAreaState extends State<TemporalArea> {
  TemporalMode _mode = TemporalMode.today;
  var _weekVisited = false;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
          child: Align(
            alignment: Alignment.center,
            child: SegmentedButton<TemporalMode>(
              key: const Key('temporal_mode_toggle'),
              segments: const [
                ButtonSegment(
                  value: TemporalMode.today,
                  label: Text('Сегодня'),
                ),
                ButtonSegment(value: TemporalMode.week, label: Text('Неделя')),
              ],
              selected: {_mode},
              showSelectedIcon: false,
              onSelectionChanged: (next) {
                if (next.isEmpty) {
                  return;
                }
                final mode = next.first;
                setState(() {
                  _mode = mode;
                  if (mode == TemporalMode.week) {
                    _weekVisited = true;
                  }
                });
              },
              style: const ButtonStyle(
                visualDensity: VisualDensity.compact,
                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              ),
            ),
          ),
        ),
        Expanded(
          child: IndexedStack(
            index: _mode == TemporalMode.today ? 0 : 1,
            children: [
              TodayScreen(
                apiClient: widget.apiClient,
                authController: widget.authController,
                captureController: widget.captureController,
                assistantController: widget.assistantController,
                onAskSecretary: widget.onAskSecretary,
                onShowInGraph: widget.onShowInGraph,
                passiveRefreshInterval: widget.passiveRefreshInterval,
                now: widget.now,
                clockTick: widget.clockTick,
                bookmarkController: widget.bookmarkController,
              ),
              _weekVisited
                  ? WeekScreen(
                      apiClient: widget.apiClient,
                      authController: widget.authController,
                      captureController: widget.captureController,
                      assistantController: widget.assistantController,
                      onAskSecretary: widget.onAskSecretary,
                      onShowInGraph: widget.onShowInGraph,
                      bookmarkController: widget.bookmarkController,
                      now: widget.now,
                      passiveRefreshInterval: widget.passiveRefreshInterval,
                      isActive: _mode == TemporalMode.week,
                    )
                  : const SizedBox.shrink(),
            ],
          ),
        ),
      ],
    );
  }
}
