import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// Target swipe distance before a modal-confirm release can activate Remove.
const double kInboxSwipeRemoveExtentPx = 96;
const double kInboxSwipeRemoveMinFraction = 0.18;
const double kInboxSwipeRemoveMaxFraction = 0.4;

/// Stronger armed distance for direct provider-backed deletion.
const double kInboxSwipeDirectDeleteExtentPx = 180;
const double kInboxSwipeDirectDeleteMinFraction = 0.24;
const double kInboxSwipeDirectDeleteMaxFraction = 0.60;

double inboxSwipeRemoveDismissThreshold(double cardWidth) {
  if (cardWidth <= 0) {
    return kInboxSwipeRemoveMaxFraction;
  }
  return (kInboxSwipeRemoveExtentPx / cardWidth).clamp(
    kInboxSwipeRemoveMinFraction,
    kInboxSwipeRemoveMaxFraction,
  );
}

double inboxSwipeDirectDeleteThreshold(double cardWidth) {
  if (cardWidth <= 0) {
    return kInboxSwipeDirectDeleteMaxFraction;
  }
  return (kInboxSwipeDirectDeleteExtentPx / cardWidth).clamp(
    kInboxSwipeDirectDeleteMinFraction,
    kInboxSwipeDirectDeleteMaxFraction,
  );
}

void inboxSwipeArmedHaptic() {
  HapticFeedback.mediumImpact();
}

class InboxSwipeRemoveBackground extends StatelessWidget {
  const InboxSwipeRemoveBackground({
    super.key,
    required this.objectId,
    this.armed = false,
  });

  final String objectId;
  final bool armed;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return ColoredBox(
      key: Key('inbox_swipe_remove_background_$objectId'),
      color: scheme.error,
      child: Align(
        alignment: Alignment.centerRight,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              Icon(
                armed ? Icons.delete : Icons.delete_outline,
                color: scheme.onError,
                size: 20,
              ),
              const SizedBox(width: 8),
              Flexible(
                child: Text(
                  armed ? 'Отпустите, чтобы удалить' : 'Удалить',
                  key: Key('inbox_swipe_remove_label_$objectId'),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  textAlign: TextAlign.right,
                  style: Theme.of(context).textTheme.labelLarge?.copyWith(
                    color: scheme.onError,
                    fontWeight: armed ? FontWeight.w600 : FontWeight.w500,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Touch-only end-to-start swipe that reveals Remove.
///
/// Provider-backed objects use a stronger armed threshold; release while armed
/// deletes immediately. Native/unknown objects keep the lighter threshold and
/// a confirmation dialog via [onConfirmRemove].
class InboxSwipeToRemove extends StatefulWidget {
  const InboxSwipeToRemove({
    super.key,
    required this.objectId,
    required this.directDelete,
    required this.onConfirmRemove,
    required this.onRemoved,
    required this.child,
  });

  final String objectId;
  final bool directDelete;
  final Future<bool> Function() onConfirmRemove;
  final VoidCallback onRemoved;
  final Widget child;

  @override
  State<InboxSwipeToRemove> createState() => _InboxSwipeToRemoveState();
}

class _InboxSwipeToRemoveState extends State<InboxSwipeToRemove> {
  var _armed = false;
  var _deleteInFlight = false;

  @override
  void didUpdateWidget(covariant InboxSwipeToRemove oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.objectId != widget.objectId) {
      _armed = false;
      _deleteInFlight = false;
    }
  }

  double _thresholdFor(double width) {
    return widget.directDelete
        ? inboxSwipeDirectDeleteThreshold(width)
        : inboxSwipeRemoveDismissThreshold(width);
  }

  void _onUpdate(DismissUpdateDetails details) {
    if (!widget.directDelete) {
      return;
    }
    if (details.reached == _armed) {
      return;
    }
    setState(() => _armed = details.reached);
    if (details.reached) {
      inboxSwipeArmedHaptic();
    }
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final width = constraints.maxWidth.isFinite && constraints.maxWidth > 0
            ? constraints.maxWidth
            : MediaQuery.sizeOf(context).width;
        return Dismissible(
          key: Key('inbox_swipe_remove_${widget.objectId}'),
          direction: DismissDirection.endToStart,
          dismissThresholds: {
            DismissDirection.endToStart: _thresholdFor(width),
          },
          onUpdate: _onUpdate,
          confirmDismiss: (direction) async {
            if (direction != DismissDirection.endToStart) {
              return false;
            }
            if (_deleteInFlight) {
              return false;
            }
            _deleteInFlight = true;
            final ok = await widget.onConfirmRemove();
            if (!ok && mounted) {
              setState(() {
                _deleteInFlight = false;
                _armed = false;
              });
            }
            return ok;
          },
          onDismissed: (_) => widget.onRemoved(),
          background: InboxSwipeRemoveBackground(
            objectId: widget.objectId,
            armed: widget.directDelete && _armed,
          ),
          child: widget.child,
        );
      },
    );
  }
}
