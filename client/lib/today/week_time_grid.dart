import 'package:flutter/material.dart';
import 'package:kalender/kalender.dart';

import '../api/api_models.dart';
import '../ui/app_spacing.dart';
import '../ui/date_format.dart';
import '../ui/object_bookmark.dart';
import '../ui/object_bookmark_controller.dart';
import '../ui/object_presentation.dart';
import 'week_kalender_events.dart';
import 'week_hour_grid.dart';
import 'week_item_type.dart';
import 'week_overlap.dart';
import 'week_overlap_layout.dart';
import 'week_today_column.dart';

final _readOnlyInteraction = CalendarInteraction(
  allowResizing: false,
  allowRescheduling: false,
  allowEventCreation: false,
);

const TimeOfDay kWeekMorningInitialTime = TimeOfDay(hour: 8, minute: 0);

const int kWeekCompactVisibleDays = 3;

const double kWeekTemporalHintWideWidthFactor = 0.725;
const double kWeekTemporalHintCompactWidthFactor = 0.90;

double weekTemporalHintWidthFactor({required bool compact}) {
  return compact
      ? kWeekTemporalHintCompactWidthFactor
      : kWeekTemporalHintWideWidthFactor;
}

Color weekTemporalHintFill(ColorScheme scheme) {
  if (scheme.brightness == Brightness.light) {
    return scheme.surfaceContainerLowest;
  }
  return scheme.surfaceContainerHigh;
}

/// Initial vertical viewport anchor. Wide/tablet always opens around 08:00.
/// Compact current Week keeps a current-time anchor; non-current stays 08:00.
TimeOfDay weekInitialTimeOfDay({
  required bool compact,
  required bool isCurrentWeek,
  required DateTime now,
}) {
  if (compact && isCurrentWeek) {
    return TimeOfDay(hour: now.hour, minute: now.minute);
  }
  return kWeekMorningInitialTime;
}

/// First civil day of the compact 3-day page that should be visible initially.
///
/// Current week keeps today on screen: Monday opens Mon/Tue/Wed, Sunday
/// opens Fri/Sat/Sun, and other weekdays prefer previous/current/next.
/// A non-current week opens on Mon/Tue/Wed.
DateTime weekCompactViewportStart({
  required DateTime weekStart,
  required bool isCurrentWeek,
  required DateTime today,
}) {
  final monday = DateTime.utc(weekStart.year, weekStart.month, weekStart.day);
  if (!isCurrentWeek) {
    return monday;
  }
  final todayCivil = DateTime.utc(today.year, today.month, today.day);
  if (todayCivil.weekday == DateTime.monday) {
    return monday;
  }
  if (todayCivil.weekday == DateTime.sunday) {
    return addCalendarDays(monday, 4);
  }
  return addCalendarDays(todayCivil, -1);
}

DateTimeRange weekCompactDisplayRange(DateTime viewportStart) {
  const pages = 240;
  final start = DateTime(
    viewportStart.year,
    viewportStart.month,
    viewportStart.day - (kWeekCompactVisibleDays * pages),
  );
  final end = DateTime(
    viewportStart.year,
    viewportStart.month,
    viewportStart.day + (kWeekCompactVisibleDays * pages),
  );
  return DateTimeRange(start: start, end: end);
}

String weekDayHeaderLabel(DateTime date) {
  return '${formatRussianWeekdayShort(date)} ${formatRussianDayMonth(date)}';
}

/// Read-only week time-grid over [WeekOut], backed by kalender.
class WeekTimeGrid extends StatefulWidget {
  const WeekTimeGrid({
    super.key,
    required this.week,
    required this.onOpen,
    required this.bookmarks,
    this.onRequestWeekStart,
    this.now,
  });

  final WeekOut week;
  final ValueChanged<String> onOpen;
  final ValueChanged<String>? onRequestWeekStart;
  final DateTime Function()? now;
  final ObjectBookmarkController bookmarks;

  @override
  State<WeekTimeGrid> createState() => _WeekTimeGridState();
}

class _WeekTimeGridState extends State<WeekTimeGrid> {
  final _events = DefaultEventsController();
  final _calendar = CalendarController();
  ViewConfiguration? _viewConfiguration;
  String? _eventsSignature;
  String? _configWeekStart;
  bool? _configCompact;
  bool? _configCurrentWeek;
  String? _configViewportStart;
  String? _pageRequestedWeekStart;
  DateTime? _pageRequestedVisibleStart;
  var _didJumpInitialCompact = false;

  DateTime _nowCallback() => (widget.now ?? DateTime.now)();

  @override
  void initState() {
    super.initState();
    widget.bookmarks.addListener(_onBookmarksChanged);
    _eventsSignature = weekPresentationSignature(widget.week);
    _events.replaceEvents(weekOutToKalenderEvents(widget.week));
  }

  @override
  void didUpdateWidget(covariant WeekTimeGrid oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.bookmarks != widget.bookmarks) {
      oldWidget.bookmarks.removeListener(_onBookmarksChanged);
      widget.bookmarks.addListener(_onBookmarksChanged);
    }
    final nextSignature = weekPresentationSignature(widget.week);
    if (nextSignature != _eventsSignature) {
      _eventsSignature = nextSignature;
      _events.replaceEvents(weekOutToKalenderEvents(widget.week));
    }
    if (oldWidget.week.weekStart != widget.week.weekStart) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!_calendar.isAttached) {
          return;
        }
        final compact =
            MediaQuery.sizeOf(context).width < AppSpacing.wideBreakpoint;
        final jump = _jumpDateAfterWeekChange(compact: compact);
        _calendar.jumpToDate(jump);
      });
    }
  }

  @override
  void dispose() {
    widget.bookmarks.removeListener(_onBookmarksChanged);
    _calendar.dispose();
    _events.dispose();
    super.dispose();
  }

  void _onBookmarksChanged() {
    if (mounted) {
      setState(() {});
    }
  }

  DateTime _civilLocal(String iso) {
    final civil = parseCalendarDate(iso);
    return DateTime(civil.year, civil.month, civil.day);
  }

  DateTime _civilFromDateTime(DateTime value) {
    return DateTime(value.year, value.month, value.day);
  }

  DateTime _compactViewportStart() {
    return _civilFromDateTime(
      weekCompactViewportStart(
        weekStart: parseCalendarDate(widget.week.weekStart),
        isCurrentWeek: widget.week.isCurrentWeek,
        today: parseCalendarDate(widget.week.todayDate),
      ),
    );
  }

  DateTime _jumpDateAfterWeekChange({required bool compact}) {
    final requestedIso = _pageRequestedWeekStart;
    final requestedStart = _pageRequestedVisibleStart;
    _pageRequestedWeekStart = null;
    _pageRequestedVisibleStart = null;
    if (compact &&
        requestedIso == widget.week.weekStart &&
        requestedStart != null) {
      return _civilFromDateTime(requestedStart);
    }
    if (compact) {
      return _compactViewportStart();
    }
    return _civilLocal(widget.week.weekStart);
  }

  ViewConfiguration _buildViewConfiguration({
    required bool compact,
    required TimeOfDay initialTime,
  }) {
    if (compact) {
      final viewportStart = _compactViewportStart();
      return MultiDayViewConfiguration.custom(
        name: '3-day',
        numberOfDays: kWeekCompactVisibleDays,
        initialDateTime: viewportStart,
        displayRange: weekCompactDisplayRange(viewportStart),
        firstDayOfWeek: DateTime.monday,
        initialTimeOfDay: initialTime,
        initialHeightPerMinute: 0.9,
        nowCallback: _nowCallback,
      );
    }
    return MultiDayViewConfiguration.week(
      initialDateTime: _civilLocal(widget.week.weekStart),
      firstDayOfWeek: DateTime.monday,
      initialTimeOfDay: initialTime,
      initialHeightPerMinute: 0.9,
      nowCallback: _nowCallback,
    );
  }

  void _syncViewConfiguration({required bool compact}) {
    final weekStart = widget.week.weekStart;
    final isCurrent = widget.week.isCurrentWeek;
    final viewportStart = compact
        ? formatCalendarDate(_compactViewportStart())
        : weekStart;
    if (_viewConfiguration != null &&
        _configWeekStart == weekStart &&
        _configCompact == compact &&
        _configCurrentWeek == isCurrent &&
        _configViewportStart == viewportStart) {
      return;
    }
    final initialTime = weekInitialTimeOfDay(
      compact: compact,
      isCurrentWeek: isCurrent,
      now: _nowCallback(),
    );
    _configWeekStart = weekStart;
    _configCompact = compact;
    _configCurrentWeek = isCurrent;
    _configViewportStart = viewportStart;
    _viewConfiguration = _buildViewConfiguration(
      compact: compact,
      initialTime: initialTime,
    );
  }

  void _onPageChanged(DateTimeRange range) {
    final onRequest = widget.onRequestWeekStart;
    if (onRequest == null) {
      return;
    }
    final civil = parseCalendarDate(formatCalendarDate(range.start));
    final monday = addCalendarDays(civil, 1 - civil.weekday);
    final iso = formatCalendarDate(monday);
    if (iso != widget.week.weekStart) {
      _pageRequestedWeekStart = iso;
      _pageRequestedVisibleStart = range.start;
      onRequest(iso);
    }
  }

  @override
  Widget build(BuildContext context) {
    final compact =
        MediaQuery.sizeOf(context).width < AppSpacing.wideBreakpoint;
    _syncViewConfiguration(compact: compact);
    if (!compact) {
      _didJumpInitialCompact = false;
    } else if (!_didJumpInitialCompact) {
      _didJumpInitialCompact = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted || !_calendar.isAttached) {
          return;
        }
        _calendar.jumpToDate(_compactViewportStart());
        if (mounted) {
          setState(() {});
        }
      });
    }
    final empty = widget.week.days.every(
      (day) =>
          day.events.isEmpty &&
          day.scheduledWork.isEmpty &&
          day.temporalHints.isEmpty,
    );
    final tiles = TileComponents(tileBuilder: _tileBuilder);
    return Column(
      children: [
        if (empty)
          const Padding(
            padding: EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: Align(
              alignment: Alignment.centerLeft,
              child: Text('На этой неделе событий нет'),
            ),
          ),
        Expanded(
          child: KalenderView(
            key: const Key('week_time_grid'),
            eventsController: _events,
            calendarController: _calendar,
            viewConfiguration: _viewConfiguration!,
            locale: const Locale('ru'),
            callbacks: CalendarCallbacks(
              onEventTapped: (event) => widget.onOpen(event.id),
              onPageChanged: _onPageChanged,
            ),
            components: CalendarComponents(
              multiDayComponents: MultiDayComponents(
                headerComponents: MultiDayHeaderComponents(
                  dayHeaderBuilder: (context, date) => _WeekDayHeader(
                    date: date,
                    todayDate: widget.week.todayDate,
                  ),
                ),
                bodyComponents: MultiDayBodyComponents(
                  hourLines: (context, heightPerMinute, timeOfDayRange) {
                    return WeekTodayColumnHourLines(
                      todayIndex: compact
                          ? null
                          : weekTodayColumnIndex(widget.week),
                      heightPerMinute: heightPerMinute,
                      timeOfDayRange: timeOfDayRange,
                    );
                  },
                  timeline: (context, heightPerMinute, timeOfDayRange, _, __) {
                    return WeekWholeHourTimeLine(
                      heightPerMinute: heightPerMinute,
                      timeOfDayRange: timeOfDayRange,
                    );
                  },
                ),
              ),
            ),
            header: CalendarHeader(
              interaction: _readOnlyInteraction,
              multiDayTileComponents: tiles,
            ),
            body: CalendarBody(
              interaction: _readOnlyInteraction,
              multiDayBodyConfiguration: MultiDayBodyConfiguration(
                eventLayoutStrategy:
                    const SecretaryDenseOverlapLayoutStrategy(),
                pageScrollPhysics: compact
                    ? null
                    : const NeverScrollableScrollPhysics(),
              ),
              multiDayTileComponents: tiles,
            ),
          ),
        ),
      ],
    );
  }

  Widget _tileBuilder(
    BuildContext context,
    CalendarEvent event,
    DateTimeRange tileRange,
  ) {
    final secretary = event is SecretaryWeekEvent ? event : null;
    final dayIso = formatCalendarDate(tileRange.start);
    final compact =
        MediaQuery.sizeOf(context).width < AppSpacing.wideBreakpoint;
    var depth = 0;
    if (!event.isAllDay) {
      final date = InternalDateTime.fromDateTime(tileRange.start);
      final depths = weekOverlapDepthsOnDate(
        events: _events.events,
        date: date,
        location: KalenderScope.locationOf(context),
      );
      depth = depths[event.id] ?? 0;
    }
    return WeekKalenderEventTile(
      key: Key('week_event_${dayIso}_${event.id}'),
      objectId: event.id,
      title: secretary?.title ?? '',
      provider: secretary?.provider,
      allDay: event.isAllDay,
      bookmarkColor: widget.bookmarks.colorFor(event.id),
      depth: depth,
      compact: compact,
      itemType: secretary?.itemType ?? WeekTemporalItemType.calendarCommitment,
      endUnknown: secretary?.endUnknown ?? false,
      completed: secretary?.completed ?? false,
    );
  }
}

class _WeekDayHeader extends StatelessWidget {
  const _WeekDayHeader({required this.date, required this.todayDate});

  final DateTime date;
  final String todayDate;

  @override
  Widget build(BuildContext context) {
    final iso = formatCalendarDate(date);
    final isToday = iso == todayDate;
    final label = weekDayHeaderLabel(date);
    if (!isToday) {
      return Padding(
        key: Key('week_day_$iso'),
        padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
        child: Text(
          key: Key('week_day_header_$iso'),
          label,
          textAlign: TextAlign.center,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: Theme.of(
            context,
          ).textTheme.labelMedium?.copyWith(fontWeight: FontWeight.w500),
        ),
      );
    }
    final scheme = Theme.of(context).colorScheme;
    final fill = weekTodayBadgeFill(scheme);
    final onFill = weekTodayBadgeForeground(scheme);
    return Padding(
      key: Key('week_day_$iso'),
      padding: const EdgeInsets.symmetric(horizontal: 2, vertical: 4),
      child: Center(
        child: DecoratedBox(
          key: const Key('week_today_header_badge'),
          decoration: BoxDecoration(
            color: fill,
            borderRadius: BorderRadius.circular(kWeekTodayHeaderBadgeRadius),
          ),
          child: Padding(
            padding: kWeekTodayHeaderBadgePadding,
            child: Text(
              key: Key('week_day_header_$iso'),
              label,
              textAlign: TextAlign.center,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.labelMedium?.copyWith(
                color: onFill,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class WeekKalenderEventTile extends StatelessWidget {
  const WeekKalenderEventTile({
    super.key,
    required this.objectId,
    required this.title,
    required this.provider,
    required this.allDay,
    this.bookmarkColor,
    this.depth = 0,
    this.compact = false,
    this.itemType = WeekTemporalItemType.calendarCommitment,
    this.endUnknown = false,
    this.completed = false,
  });

  final String objectId;
  final String title;
  final String? provider;
  final bool allDay;
  final String? bookmarkColor;
  final int depth;
  final bool compact;
  final WeekTemporalItemType itemType;
  final bool endUnknown;
  final bool completed;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final isHint = itemType == WeekTemporalItemType.temporalHint;
    final isScheduled = itemType == WeekTemporalItemType.scheduledWork;
    final tone = weekOverlapTone(scheme, allDay ? 1 : depth);
    final fill = isHint
        ? weekTemporalHintFill(scheme)
        : isScheduled
        ? scheme.secondaryContainer.withValues(alpha: completed ? 0.32 : 0.74)
        : tone.fill.withValues(alpha: 0.92);
    final foreground = isHint
        ? scheme.onSurface
        : isScheduled
        ? scheme.onSecondaryContainer.withValues(alpha: completed ? 0.62 : 1)
        : tone.foreground;
    final outline = isHint
        ? scheme.onSurface.withValues(alpha: 0.48)
        : isScheduled
        ? scheme.outline.withValues(alpha: 0.68)
        : scheme.outline.withValues(alpha: 0.42);
    final denseTitle = !compact && !allDay;
    final tokenColor = bookmarkColor == null
        ? null
        : bookmarkTokenColor(bookmarkColor!, scheme);
    final content = Stack(
      clipBehavior: Clip.none,
      children: [
        Padding(
          padding: EdgeInsets.fromLTRB(4, allDay ? 2 : 1, 4, allDay ? 2 : 1),
          child: Row(
            children: [
              _WeekEventIdentityRail(
                objectId: objectId,
                provider: provider,
                itemType: itemType,
                compact: !denseTitle,
                typeColor: foreground,
              ),
              const SizedBox(width: 4),
              Expanded(
                child: Text(
                  title,
                  maxLines: allDay ? 1 : 3,
                  overflow: TextOverflow.ellipsis,
                  style:
                      weekEventTitleStyle(
                        Theme.of(context).textTheme,
                        color: foreground,
                        compact: !denseTitle,
                      ).copyWith(
                        decoration: completed
                            ? TextDecoration.lineThrough
                            : null,
                      ),
                ),
              ),
              if (allDay)
                Padding(
                  padding: const EdgeInsets.only(left: 4),
                  child: Text(
                    'Весь день',
                    style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      color: foreground.withValues(alpha: 0.8),
                    ),
                  ),
                ),
            ],
          ),
        ),
        if (tokenColor != null)
          Positioned(
            top: 0,
            right: 0,
            child: IgnorePointer(
              child: Stack(
                alignment: Alignment.center,
                children: [
                  ObjectBookmarkGlyph(
                    fillColor: scheme.surface,
                    size: Size(
                      kBookmarkTabSize.width + 2,
                      kBookmarkTabSize.height + 2,
                    ),
                  ),
                  ObjectBookmarkGlyph(
                    key: Key('week_bookmark_$objectId'),
                    fillColor: tokenColor,
                    size: kBookmarkTabSize,
                  ),
                ],
              ),
            ),
          ),
        if (isHint && endUnknown)
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            height: 10,
            child: IgnorePointer(
              child: DecoratedBox(
                key: Key('week_hint_unknown_end_$objectId'),
                decoration: BoxDecoration(
                  borderRadius: const BorderRadius.vertical(
                    bottom: Radius.circular(100),
                  ),
                  gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [
                      fill.withValues(alpha: 0),
                      scheme.surface.withValues(alpha: 0.82),
                    ],
                  ),
                ),
              ),
            ),
          ),
      ],
    );
    if (isHint) {
      return Align(
        alignment: Alignment.center,
        child: FractionallySizedBox(
          key: Key('week_hint_visual_$objectId'),
          widthFactor: weekTemporalHintWidthFactor(compact: compact),
          heightFactor: 1,
          child: Material(
            key: Key('week_hint_style_$objectId'),
            color: fill,
            clipBehavior: Clip.antiAlias,
            shape: const StadiumBorder(),
            child: CustomPaint(
              painter: _WeekHintOutlinePainter(
                color: outline,
                endUnknown: endUnknown,
              ),
              child: content,
            ),
          ),
        ),
      );
    }
    final tile = Material(
      color: fill,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(4),
        side: BorderSide(color: outline, width: 0.8),
      ),
      child: content,
    );
    if (!isScheduled) {
      return tile;
    }
    return KeyedSubtree(
      key: Key('week_scheduled_style_$objectId'),
      child: completed
          ? KeyedSubtree(key: Key('week_scheduled_done_$objectId'), child: tile)
          : tile,
    );
  }
}

class _WeekHintOutlinePainter extends CustomPainter {
  const _WeekHintOutlinePainter({
    required this.color,
    required this.endUnknown,
  });

  final Color color;
  final bool endUnknown;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.15
      ..strokeCap = StrokeCap.round;
    const inset = 0.6;
    final rect = Rect.fromLTWH(
      inset,
      inset,
      size.width - inset * 2,
      size.height - inset * 2,
    );
    if (rect.isEmpty) {
      return;
    }
    final radius = Radius.circular(rect.height / 2);
    final path = Path()..addRRect(RRect.fromRectAndRadius(rect, radius));
    _dashedPath(canvas, path, paint);
    if (!endUnknown) {
      return;
    }
    final faded = Paint()
      ..color = color.withValues(alpha: 0.28)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.0
      ..strokeCap = StrokeCap.round;
    final bottom = Path()
      ..moveTo(rect.left + 4, rect.bottom)
      ..lineTo(rect.right - 4, rect.bottom);
    _dashedPath(canvas, bottom, faded, dash: 2, gap: 4);
  }

  void _dashedPath(
    Canvas canvas,
    Path path,
    Paint paint, {
    double dash = 3.2,
    double gap = 2.4,
  }) {
    for (final metric in path.computeMetrics()) {
      var drawn = 0.0;
      var on = true;
      while (drawn < metric.length) {
        final step = on ? dash : gap;
        final next = drawn + step > metric.length
            ? metric.length
            : drawn + step;
        if (on) {
          canvas.drawPath(metric.extractPath(drawn, next), paint);
        }
        drawn = next;
        on = !on;
      }
    }
  }

  @override
  bool shouldRepaint(covariant _WeekHintOutlinePainter oldDelegate) {
    return oldDelegate.color != color || oldDelegate.endUnknown != endUnknown;
  }
}

class _WeekEventIdentityRail extends StatelessWidget {
  const _WeekEventIdentityRail({
    required this.objectId,
    required this.provider,
    required this.itemType,
    required this.compact,
    required this.typeColor,
  });

  final String objectId;
  final String? provider;
  final WeekTemporalItemType itemType;
  final bool compact;
  final Color typeColor;

  @override
  Widget build(BuildContext context) {
    final providerSize = compact
        ? kWeekPhoneProviderGlyphSize
        : kWeekWideProviderGlyphSize;
    final typeSize = compact ? kWeekPhoneTypeGlyphSize : kWeekWideTypeGlyphSize;
    final glyph = compactProviderGlyphWidget(provider, size: providerSize);
    final needed =
        (glyph != null ? providerSize + kWeekIdentityRailGap : 0) + typeSize;
    final column = Column(
      key: Key('week_identity_rail_$objectId'),
      mainAxisSize: MainAxisSize.min,
      children: [
        if (glyph != null) ...[
          SizedBox(
            width: providerSize,
            height: providerSize,
            child: FittedBox(fit: BoxFit.contain, child: glyph),
          ),
          const SizedBox(height: kWeekIdentityRailGap),
        ],
        WeekTemporalItemTypeGlyph(
          objectId: objectId,
          itemType: itemType,
          size: typeSize,
          color: typeColor,
        ),
      ],
    );
    return IgnorePointer(
      child: LayoutBuilder(
        builder: (context, constraints) {
          final maxH = constraints.maxHeight;
          final fits = !maxH.isFinite || maxH >= needed;
          if (fits) {
            return column;
          }
          final railWidth = providerSize > typeSize ? providerSize : typeSize;
          return SizedBox(
            width: railWidth,
            height: maxH,
            child: ClipRect(
              child: OverflowBox(
                alignment: Alignment.topCenter,
                maxHeight: needed,
                child: column,
              ),
            ),
          );
        },
      ),
    );
  }
}
