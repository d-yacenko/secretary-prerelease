import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../api/api_models.dart';
import '../ui/object_bookmark.dart';
import '../ui/object_visuals.dart';
import 'graph_layout.dart';

/// Extra canvas margin so satellite rings do not change the graph origin
/// when the selected Task changes.
const double kFocusLodCanvasMargin = 480;

/// Compact satellite diameter. Rings are presentation-only and do not feed
/// [GraphLayout].
const double kFocusLodSatelliteSize = 24;

const int kFocusLodSatelliteCap = 20;

const double _satelliteGap = 4;
const int _slotsPerRing = 12;
const int _maxRings = 48;

const Set<String> kFocusLodCompactKinds = {
  'email',
  'calendar_event',
  'event',
  'file',
  'document',
  'dataset',
  'folder',
  'note',
  'web_page',
  'chat',
  'message',
  'chat_message',
};

class FocusLodSatellite {
  const FocusLodSatellite({
    required this.objectId,
    required this.anchorTaskId,
    required this.topLeft,
    required this.bookmarked,
  });

  final String objectId;
  final String anchorTaskId;
  final Offset topLeft;
  final bool bookmarked;

  Rect get rect => Rect.fromLTWH(
    topLeft.dx,
    topLeft.dy,
    kFocusLodSatelliteSize,
    kFocusLodSatelliteSize,
  );
}

class FocusLodOverflow {
  const FocusLodOverflow({
    required this.anchorTaskId,
    required this.remainder,
    required this.topLeft,
  });

  final String anchorTaskId;
  final int remainder;
  final Offset topLeft;

  Rect get rect => Rect.fromLTWH(
    topLeft.dx,
    topLeft.dy,
    kFocusLodSatelliteSize,
    kFocusLodSatelliteSize,
  );
}

class FocusLodProjection {
  const FocusLodProjection({
    required this.fullCardIds,
    required this.satellites,
    required this.overflows,
  });

  final Set<String> fullCardIds;
  final List<FocusLodSatellite> satellites;
  final List<FocusLodOverflow> overflows;
}

bool focusLodKindIsCompactable(String kind) =>
    kFocusLodCompactKinds.contains(kind);

/// Presentation lens over the current graph.
///
/// The presentation anchor is not ownership and is not written back to edges
/// or workspace data. A Flow object connected to several Tasks is drawn once,
/// beside the visible Task whose current center is closest, with Task id as
/// the tie-break.
FocusLodProjection projectFocusLod({
  required List<SecretaryObject> nodes,
  required List<SecretaryEdge> edges,
  required Map<String, Offset> positions,
  required String? selectedObjectId,
  bool Function(String objectId)? isBookmarked,
  bool expandSelectedFlow = true,
  Map<String, Rect>? taskObstacleRects,
}) {
  final byId = {for (final node in nodes) node.id: node};
  final bookmarked = isBookmarked ?? (_) => false;
  final taskIds = <String>{
    for (final node in nodes)
      if (node.kind == 'task' && positions.containsKey(node.id)) node.id,
  };
  final selected = selectedObjectId == null ? null : byId[selectedObjectId];
  final selectedIsTask =
      selected != null &&
      selected.kind == 'task' &&
      taskIds.contains(selected.id);

  final tasksByFlow = <String, Set<String>>{};
  for (final edge in edges) {
    final source = byId[edge.sourceId];
    final target = byId[edge.targetId];
    if (source == null || target == null) {
      continue;
    }
    void link(SecretaryObject flow, SecretaryObject other) {
      if (!focusLodKindIsCompactable(flow.kind) || other.kind != 'task') {
        return;
      }
      if (!positions.containsKey(flow.id) || !taskIds.contains(other.id)) {
        return;
      }
      tasksByFlow.putIfAbsent(flow.id, () => <String>{}).add(other.id);
    }

    link(source, target);
    link(target, source);
  }

  final expanded = <String>{};
  if (selectedIsTask && expandSelectedFlow) {
    for (final entry in tasksByFlow.entries) {
      if (entry.value.contains(selected.id)) {
        expanded.add(entry.key);
      }
    }
  }

  final fullCardIds = <String>{
    for (final node in nodes)
      if (node.kind == 'task' ||
          !focusLodKindIsCompactable(node.kind) ||
          expanded.contains(node.id) ||
          !(tasksByFlow[node.id]?.isNotEmpty ?? false))
        node.id,
  };

  final grouped = <String, List<SecretaryObject>>{};
  for (final node in nodes) {
    if (!focusLodKindIsCompactable(node.kind) || expanded.contains(node.id)) {
      continue;
    }
    final tasks = tasksByFlow[node.id];
    if (tasks == null || tasks.isEmpty || !positions.containsKey(node.id)) {
      continue;
    }
    final anchor = _presentationAnchor(
      flowId: node.id,
      taskIds: tasks,
      positions: positions,
    );
    if (anchor == null) {
      fullCardIds.add(node.id);
      continue;
    }
    fullCardIds.remove(node.id);
    grouped.putIfAbsent(anchor, () => <SecretaryObject>[]).add(node);
  }

  final taskRects = {
    for (final id in taskIds)
      id: taskObstacleRects?[id] ?? GraphLayout.nodeRectAt(positions[id]!),
  };
  final satellites = <FocusLodSatellite>[];
  final overflows = <FocusLodOverflow>[];
  final anchorIds = grouped.keys.toList()..sort();
  for (final anchorId in anchorIds) {
    final members = grouped[anchorId]!
      ..sort((left, right) => _satelliteOrder(left, right, bookmarked));
    final placed = <Rect>[];
    final limit = math.min(kFocusLodSatelliteCap, members.length);
    var placedCount = 0;
    for (final member in members.take(limit)) {
      final slot = _nextSlot(
        anchor: positions[anchorId]!,
        taskRects: taskRects.values,
        placed: placed,
      );
      if (slot == null) {
        break;
      }
      placed.add(slot);
      placedCount += 1;
      satellites.add(
        FocusLodSatellite(
          objectId: member.id,
          anchorTaskId: anchorId,
          topLeft: slot.topLeft,
          bookmarked: bookmarked(member.id),
        ),
      );
    }
    final remainder = members.length - placedCount;
    if (remainder > 0) {
      final slot = _nextSlot(
        anchor: positions[anchorId]!,
        taskRects: taskRects.values,
        placed: placed,
      );
      if (slot != null) {
        overflows.add(
          FocusLodOverflow(
            anchorTaskId: anchorId,
            remainder: remainder,
            topLeft: slot.topLeft,
          ),
        );
      }
    }
  }

  return FocusLodProjection(
    fullCardIds: fullCardIds,
    satellites: satellites,
    overflows: overflows,
  );
}

bool focusLodEdgeIsVisible({
  required SecretaryEdge edge,
  required Set<String> fullCardIds,
}) {
  return fullCardIds.contains(edge.sourceId) &&
      fullCardIds.contains(edge.targetId);
}

int focusLodTaskOverlaps({
  required Iterable<Rect> marks,
  required Iterable<Rect> taskRects,
}) {
  var count = 0;
  for (final mark in marks) {
    for (final task in taskRects) {
      if (_area(mark, task) > 0.5) {
        count += 1;
      }
    }
  }
  return count;
}

int focusLodSameHaloOverlaps(List<FocusLodSatellite> satellites) {
  final groups = <String, List<FocusLodSatellite>>{};
  for (final satellite in satellites) {
    groups
        .putIfAbsent(satellite.anchorTaskId, () => <FocusLodSatellite>[])
        .add(satellite);
  }
  var count = 0;
  for (final group in groups.values) {
    for (var i = 0; i < group.length; i++) {
      for (var j = i + 1; j < group.length; j++) {
        if (_area(group[i].rect, group[j].rect) > 0.5) {
          count += 1;
        }
      }
    }
  }
  return count;
}

String? _presentationAnchor({
  required String flowId,
  required Set<String> taskIds,
  required Map<String, Offset> positions,
}) {
  final flow = positions[flowId];
  if (flow == null || taskIds.isEmpty) {
    return null;
  }
  final flowCenter = _center(flow);
  final ordered = taskIds.toList()..sort();
  String? best;
  var bestDistance = double.infinity;
  for (final taskId in ordered) {
    final task = positions[taskId];
    if (task == null) {
      continue;
    }
    final distance = (_center(task) - flowCenter).distance;
    if (distance + 0.001 < bestDistance) {
      best = taskId;
      bestDistance = distance;
    }
  }
  return best;
}

int _satelliteOrder(
  SecretaryObject left,
  SecretaryObject right,
  bool Function(String objectId) bookmarked,
) {
  final leftMark = bookmarked(left.id);
  final rightMark = bookmarked(right.id);
  if (leftMark != rightMark) {
    return leftMark ? -1 : 1;
  }
  final recency = right.updatedAt.compareTo(left.updatedAt);
  if (recency != 0) {
    return recency;
  }
  return left.id.compareTo(right.id);
}

Offset _center(Offset topLeft) {
  return Offset(
    topLeft.dx + kGraphNodeWidth / 2,
    topLeft.dy + kGraphNodeHeight / 2,
  );
}

Rect? _nextSlot({
  required Offset anchor,
  required Iterable<Rect> taskRects,
  required List<Rect> placed,
}) {
  final anchorCenter = _center(anchor);
  final baseRadius = math.sqrt(
    math.pow(
          kGraphNodeWidth / 2 + kFocusLodSatelliteSize / 2 + _satelliteGap,
          2,
        ) +
        math.pow(
          kGraphNodeHeight / 2 + kFocusLodSatelliteSize / 2 + _satelliteGap,
          2,
        ),
  );
  final step = kFocusLodSatelliteSize + _satelliteGap;
  final angleStep = (2 * math.pi) / _slotsPerRing;
  for (var ring = 0; ring < _maxRings; ring++) {
    final radius = baseRadius + ring * step;
    for (var slot = 0; slot < _slotsPerRing; slot++) {
      final angle = angleStep * slot - math.pi / 2;
      final center = Offset(
        anchorCenter.dx + math.cos(angle) * radius,
        anchorCenter.dy + math.sin(angle) * radius,
      );
      final rect = Rect.fromCenter(
        center: center,
        width: kFocusLodSatelliteSize,
        height: kFocusLodSatelliteSize,
      );
      if (_hitsAny(rect, taskRects) || _hitsAny(rect, placed)) {
        continue;
      }
      return rect;
    }
  }
  return null;
}

bool _hitsAny(Rect rect, Iterable<Rect> others) {
  for (final other in others) {
    if (_area(rect, other) > 0.5) {
      return true;
    }
  }
  return false;
}

class FocusLodSatelliteMark extends StatelessWidget {
  const FocusLodSatelliteMark({
    super.key,
    required this.objectId,
    required this.kind,
    required this.title,
    required this.provider,
    required this.bookmarkColor,
    required this.onTap,
  });

  final String objectId;
  final String kind;
  final String title;
  final String? provider;
  final String? bookmarkColor;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final tooltip = [
      title,
      if (provider != null && provider!.trim().isNotEmpty) provider,
    ].join(' · ');
    final identity = providerHasIdentity(provider)
        ? ProviderSourceIcon(provider: provider, size: 16)
        : Icon(iconForKind(kind), size: 16);
    return Semantics(
      button: true,
      label: title,
      child: Tooltip(
        message: tooltip,
        child: GestureDetector(
          onTap: onTap,
          child: SizedBox(
            width: kFocusLodSatelliteSize,
            height: kFocusLodSatelliteSize,
            child: DecoratedBox(
              decoration: BoxDecoration(
                color: scheme.surface,
                shape: BoxShape.circle,
                border: Border.all(color: scheme.outline),
              ),
              child: Stack(
                clipBehavior: Clip.none,
                children: [
                  Center(child: identity),
                  if (bookmarkColor != null)
                    Positioned(
                      right: -1,
                      top: -1,
                      child: Container(
                        key: ValueKey('focus-lod-bookmark-$objectId'),
                        width: 8,
                        height: 8,
                        decoration: BoxDecoration(
                          color: bookmarkTokenColor(bookmarkColor!, scheme),
                          shape: BoxShape.circle,
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class FocusLodOverflowMark extends StatelessWidget {
  const FocusLodOverflowMark({
    super.key,
    required this.remainder,
    required this.onTap,
  });

  final int remainder;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return GestureDetector(
      onTap: onTap,
      child: SizedBox(
        width: kFocusLodSatelliteSize,
        height: kFocusLodSatelliteSize,
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: scheme.surfaceContainerHighest,
            shape: BoxShape.circle,
            border: Border.all(color: scheme.outline),
          ),
          child: Center(
            child: Text(
              '+$remainder',
              style: Theme.of(context).textTheme.labelSmall,
            ),
          ),
        ),
      ),
    );
  }
}

double _area(Rect a, Rect b) {
  final left = math.max(a.left, b.left);
  final right = math.min(a.right, b.right);
  final top = math.max(a.top, b.top);
  final bottom = math.min(a.bottom, b.bottom);
  if (right - left <= 0.5 || bottom - top <= 0.5) {
    return 0;
  }
  return (right - left) * (bottom - top);
}
