import 'dart:math' as math;

import 'package:flutter/material.dart';

/// Source-system identity, independent of Object kind.
enum ProviderSourceMark {
  google,
  yandex,
  mattermost,
  telegram,
  teams,
  computer,
  cloud,
  web,
  file,
  fallback,
}

class ProviderSourceMarkView extends StatelessWidget {
  const ProviderSourceMarkView({
    super.key,
    required this.mark,
    this.size = 16,
  });

  final ProviderSourceMark mark;
  final double size;

  @override
  Widget build(BuildContext context) {
    switch (mark) {
      case ProviderSourceMark.google:
        return CustomPaint(
          key: const Key('source_mark_google'),
          size: Size.square(size),
          painter: const GoogleGMarkPainter(),
        );
      case ProviderSourceMark.yandex:
        return CustomPaint(
          key: const Key('source_mark_yandex'),
          size: Size.square(size),
          painter: const YandexYMarkPainter(),
        );
      case ProviderSourceMark.mattermost:
        return CustomPaint(
          key: const Key('source_mark_mattermost'),
          size: Size.square(size),
          painter: const MattermostMarkPainter(),
        );
      case ProviderSourceMark.telegram:
        return Icon(
          Icons.telegram,
          key: const Key('source_mark_telegram'),
          size: size,
          color: const Color(0xFF229ED9),
        );
      case ProviderSourceMark.teams:
        return Icon(
          Icons.groups,
          key: const Key('source_mark_teams'),
          size: size,
          color: const Color(0xFF6264A7),
        );
      case ProviderSourceMark.computer:
        return Icon(
          Icons.computer,
          key: const Key('source_mark_computer'),
          size: size,
          color: const Color(0xFF5F6368),
        );
      case ProviderSourceMark.cloud:
        return Icon(
          Icons.cloud_outlined,
          key: const Key('source_mark_cloud'),
          size: size,
          color: const Color(0xFF5F6368),
        );
      case ProviderSourceMark.web:
        return Icon(
          Icons.language,
          key: const Key('source_mark_web'),
          size: size,
          color: const Color(0xFF5F6368),
        );
      case ProviderSourceMark.file:
        return Icon(
          Icons.upload_file,
          key: const Key('source_mark_file'),
          size: size,
          color: const Color(0xFF7B61FF),
        );
      case ProviderSourceMark.fallback:
        return Icon(
          Icons.source_outlined,
          key: const Key('source_mark_fallback'),
          size: size,
          color: const Color(0xFF607D8B),
        );
    }
  }
}

/// Original four-color Google G using published Google brand colors.
/// Not a raster copy; geometry is an original compact recreation.
class GoogleGMarkPainter extends CustomPainter {
  const GoogleGMarkPainter();

  static const _blue = Color(0xFF4285F4);
  static const _red = Color(0xFFEA4335);
  static const _yellow = Color(0xFFFBBC05);
  static const _green = Color(0xFF34A853);

  @override
  void paint(Canvas canvas, Size size) {
    final s = size.shortestSide;
    final stroke = s * 0.22;
    final center = Offset(s / 2, s / 2);
    final radius = s / 2 - stroke / 2 - s * 0.03;
    final rect = Rect.fromCircle(center: center, radius: radius);

    Paint ring(Color color) {
      return Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = stroke
        ..strokeCap = StrokeCap.butt;
    }

    double rad(double deg) => deg * math.pi / 180;

    canvas.drawArc(rect, rad(18), rad(72), false, ring(_green));
    canvas.drawArc(rect, rad(90), rad(90), false, ring(_yellow));
    canvas.drawArc(rect, rad(180), rad(90), false, ring(_red));
    canvas.drawArc(rect, rad(270), rad(82), false, ring(_blue));

    final barH = stroke;
    canvas.drawRect(
      Rect.fromLTRB(center.dx, center.dy - barH / 2, s - s * 0.02, center.dy + barH / 2),
      Paint()..color = _blue,
    );
  }

  @override
  bool shouldRepaint(covariant GoogleGMarkPainter oldDelegate) => false;
}

/// Original red Yandex Y using published Yandex red.
class YandexYMarkPainter extends CustomPainter {
  const YandexYMarkPainter();

  static const _red = Color(0xFFFC3F1D);

  @override
  void paint(Canvas canvas, Size size) {
    final s = size.shortestSide;
    final paint = Paint()
      ..color = _red
      ..style = PaintingStyle.stroke
      ..strokeWidth = s * 0.18
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    final path = Path()
      ..moveTo(s * 0.16, s * 0.12)
      ..lineTo(s * 0.50, s * 0.50)
      ..lineTo(s * 0.84, s * 0.12)
      ..moveTo(s * 0.50, s * 0.50)
      ..lineTo(s * 0.50, s * 0.90);
    canvas.drawPath(path, paint);
  }

  @override
  bool shouldRepaint(covariant YandexYMarkPainter oldDelegate) => false;
}

/// Original Mattermost-like clustered mark in Mattermost blue.
class MattermostMarkPainter extends CustomPainter {
  const MattermostMarkPainter();

  static const _blue = Color(0xFF0058CC);

  @override
  void paint(Canvas canvas, Size size) {
    final s = size.shortestSide;
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        Rect.fromLTWH(0, 0, s, s),
        Radius.circular(s * 0.22),
      ),
      Paint()..color = _blue,
    );
    final white = Paint()..color = Colors.white;
    canvas.drawCircle(Offset(s * 0.38, s * 0.40), s * 0.15, white);
    canvas.drawCircle(Offset(s * 0.62, s * 0.40), s * 0.15, white);
    canvas.drawCircle(Offset(s * 0.50, s * 0.62), s * 0.15, white);
  }

  @override
  bool shouldRepaint(covariant MattermostMarkPainter oldDelegate) => false;
}
