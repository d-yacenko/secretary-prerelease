import 'package:flutter/material.dart';

/// Limited spacing vocabulary for Design Quality Pass A.
abstract final class AppSpacing {
  static const double xs = 4;
  static const double sm = 8;
  static const double md = 12;
  static const double lg = 16;
  static const double xl = 24;

  static const double wideBreakpoint = 600;
  static const double providerIconSize = 16;
  static const double kindIconSize = 16;
}

bool isWideLayout(BuildContext context) {
  return MediaQuery.sizeOf(context).width >= AppSpacing.wideBreakpoint;
}
