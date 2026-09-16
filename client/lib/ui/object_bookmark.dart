import 'dart:math' as math;

import 'package:flutter/material.dart';

const List<String> kBookmarkColorTokens = [
  'red',
  'orange',
  'yellow',
  'green',
  'blue',
  'violet',
  'gray',
];

const String kBookmarkClearMenuValue = '__clear__';

const Map<String, String> kBookmarkColorLabels = {
  'red': 'Красный',
  'orange': 'Оранжевый',
  'yellow': 'Жёлтый',
  'green': 'Зелёный',
  'blue': 'Синий',
  'violet': 'Фиолетовый',
  'gray': 'Серый',
};

const Size kBookmarkGlyphSize = Size(14, 18);
const Size kBookmarkTabSize = Size(16, 20);
const Size kBookmarkTabHitSize = Size(36, 36);

/// Internal header inset so an overlaid tab does not cover timestamp/title.
/// Never applied outside the card: bookmark presence must not change card width.
const double kBookmarkRibbonReserve = 18;

Color bookmarkTokenColor(String token, ColorScheme scheme) {
  switch (token) {
    case 'red':
      return const Color(0xFFE53935);
    case 'orange':
      return const Color(0xFFFB8C00);
    case 'yellow':
      return const Color(0xFFFDD835);
    case 'green':
      return const Color(0xFF43A047);
    case 'blue':
      return const Color(0xFF1E88E5);
    case 'violet':
      return const Color(0xFF8E24AA);
    case 'gray':
      return scheme.outline;
    default:
      return scheme.outline;
  }
}

List<PopupMenuEntry<String>> bookmarkPaletteEntries({
  required String? color,
  required ColorScheme scheme,
}) {
  return [
    for (final token in kBookmarkColorTokens)
      PopupMenuItem(
        value: token,
        child: Row(
          children: [
            Container(
              width: 12,
              height: 12,
              decoration: BoxDecoration(
                color: bookmarkTokenColor(token, scheme),
                shape: BoxShape.circle,
              ),
            ),
            const SizedBox(width: 8),
            Text(kBookmarkColorLabels[token] ?? token),
          ],
        ),
      ),
    if (color != null)
      const PopupMenuItem(
        value: kBookmarkClearMenuValue,
        child: Text('Убрать закладку'),
      ),
  ];
}

void handleBookmarkMenuSelection(
  String value, {
  required ValueChanged<String> onSelect,
  required VoidCallback onClear,
}) {
  if (value == kBookmarkClearMenuValue) {
    onClear();
    return;
  }
  onSelect(value);
}

class ObjectBookmarkPaletteButton extends StatelessWidget {
  const ObjectBookmarkPaletteButton({
    super.key,
    required this.color,
    required this.onSelect,
    required this.onClear,
    required this.child,
    this.tooltip = 'Закладка',
    this.padding = EdgeInsets.zero,
  });

  final String? color;
  final ValueChanged<String> onSelect;
  final VoidCallback onClear;
  final Widget child;
  final String tooltip;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    return PopupMenuButton<String>(
      tooltip: tooltip,
      padding: padding,
      onSelected: (value) => handleBookmarkMenuSelection(
        value,
        onSelect: onSelect,
        onClear: onClear,
      ),
      itemBuilder: (context) => bookmarkPaletteEntries(
        color: color,
        scheme: Theme.of(context).colorScheme,
      ),
      child: child,
    );
  }
}

/// Physical page-tab / swallow-tail silhouette used for both outline and fill.
class BookmarkSilhouettePainter extends CustomPainter {
  BookmarkSilhouettePainter({
    required this.color,
    required this.filled,
    this.strokeWidth = 1.5,
  });

  final Color color;
  final bool filled;
  final double strokeWidth;

  static Path silhouette(Size size) {
    final w = size.width;
    final h = size.height;
    final notch = h * 0.30;
    final topRadius = (w * 0.12).clamp(0.8, 1.6);
    return Path()
      ..moveTo(topRadius, 0)
      ..lineTo(w - topRadius, 0)
      ..quadraticBezierTo(w, 0, w, topRadius)
      ..lineTo(w, h)
      ..lineTo(w / 2, h - notch)
      ..lineTo(0, h)
      ..lineTo(0, topRadius)
      ..quadraticBezierTo(0, 0, topRadius, 0)
      ..close();
  }

  @override
  void paint(Canvas canvas, Size size) {
    final inset = filled ? 0.0 : strokeWidth / 2;
    final drawSize = Size(
      math.max(1, size.width - inset * 2),
      math.max(1, size.height - inset * 2),
    );
    final path = silhouette(drawSize).shift(Offset(inset, inset));
    if (filled) {
      canvas.drawPath(
        path,
        Paint()
          ..color = color
          ..style = PaintingStyle.fill,
      );
    } else {
      canvas.drawPath(
        path,
        Paint()
          ..color = color
          ..style = PaintingStyle.stroke
          ..strokeWidth = strokeWidth
          ..strokeJoin = StrokeJoin.round
          ..strokeCap = StrokeCap.round,
      );
    }
  }

  @override
  bool shouldRepaint(covariant BookmarkSilhouettePainter oldDelegate) {
    return oldDelegate.color != color ||
        oldDelegate.filled != filled ||
        oldDelegate.strokeWidth != strokeWidth;
  }
}

class ObjectBookmarkGlyph extends StatelessWidget {
  const ObjectBookmarkGlyph({
    super.key,
    this.fillColor,
    this.size = kBookmarkGlyphSize,
  });

  final Color? fillColor;
  final Size size;

  @override
  Widget build(BuildContext context) {
    final outline = Theme.of(context).colorScheme.onSurfaceVariant;
    return SizedBox(
      width: size.width,
      height: size.height,
      child: CustomPaint(
        painter: BookmarkSilhouettePainter(
          color: fillColor ?? outline,
          filled: fillColor != null,
        ),
      ),
    );
  }
}

class ObjectBookmarkRibbon extends StatelessWidget {
  const ObjectBookmarkRibbon({
    super.key,
    required this.child,
    this.color,
    this.onSelect,
    this.onClear,
    this.reserveTrailingSpace = true,
  });

  final Widget child;
  final String? color;
  final ValueChanged<String>? onSelect;
  final VoidCallback? onClear;
  final bool reserveTrailingSpace;

  @override
  Widget build(BuildContext context) {
    if (color == null) {
      return child;
    }
    final tokenColor = bookmarkTokenColor(color!, Theme.of(context).colorScheme);
    final tab = ObjectBookmarkGlyph(
      key: const Key('object_bookmark_tab'),
      fillColor: tokenColor,
      size: kBookmarkTabSize,
    );
    final canEdit = onSelect != null && onClear != null;
    return Stack(
      clipBehavior: Clip.none,
      children: [
        child,
        Positioned(
          top: -2,
          right: reserveTrailingSpace ? 0 : -2,
          child: canEdit
              ? ObjectBookmarkPaletteButton(
                  color: color,
                  onSelect: onSelect!,
                  onClear: onClear!,
                  tooltip: 'Закладка',
                  child: SizedBox(
                    key: const Key('object_bookmark_tab_hit'),
                    width: kBookmarkTabHitSize.width,
                    height: kBookmarkTabHitSize.height,
                    child: Listener(
                      behavior: HitTestBehavior.opaque,
                      child: Align(
                        alignment: Alignment.topRight,
                        child: tab,
                      ),
                    ),
                  ),
                )
              : tab,
        ),
      ],
    );
  }
}

class ObjectBookmarkControl extends StatelessWidget {
  const ObjectBookmarkControl({
    super.key,
    required this.color,
    required this.onSelect,
    required this.onClear,
  });

  final String? color;
  final ValueChanged<String> onSelect;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    return ObjectBookmarkPaletteButton(
      key: const Key('object_bookmark_control'),
      color: color,
      onSelect: onSelect,
      onClear: onClear,
      tooltip: 'поставить закладку',
      child: const SizedBox(
        width: 36,
        height: 36,
        child: Center(
          child: ObjectBookmarkGlyph(),
        ),
      ),
    );
  }
}

class ObjectBookmarkEditor extends StatelessWidget {
  const ObjectBookmarkEditor({
    super.key,
    required this.color,
    required this.onSelect,
    required this.onClear,
  });

  final String? color;
  final ValueChanged<String> onSelect;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    if (color == null) {
      return ObjectBookmarkControl(
        color: color,
        onSelect: onSelect,
        onClear: onClear,
      );
    }
    final tokenColor = bookmarkTokenColor(color!, Theme.of(context).colorScheme);
    return ObjectBookmarkPaletteButton(
      color: color,
      onSelect: onSelect,
      onClear: onClear,
      tooltip: 'Закладка',
      child: SizedBox(
        width: 36,
        height: 36,
        child: Center(
          child: ObjectBookmarkGlyph(
            key: const Key('object_bookmark_tab'),
            fillColor: tokenColor,
            size: kBookmarkTabSize,
          ),
        ),
      ),
    );
  }
}
