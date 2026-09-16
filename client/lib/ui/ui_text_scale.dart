import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

const double kUiTextScaleMin = 0.50;
const double kUiTextScaleMax = 1.30;
const double kUiTextScaleDefault = 1.0;
const double kUiTextScaleStep = 0.05;
const String kUiTextScalePrefsKey = 'ui_text_scale_factor';

/// Slider ticks from 50% to 130% in 5% steps: 50, 55, …, 130.
const int kUiTextScaleDivisions = 16;

double clampUiTextScale(double? value) {
  if (value == null || value.isNaN || value.isInfinite) {
    return kUiTextScaleDefault;
  }
  if (value < kUiTextScaleMin) {
    return kUiTextScaleMin;
  }
  if (value > kUiTextScaleMax) {
    return kUiTextScaleMax;
  }
  return value;
}

class UiTextScaleController extends ChangeNotifier {
  UiTextScaleController({double factor = kUiTextScaleDefault})
      : _factor = clampUiTextScale(factor);

  double _factor;

  double get factor => _factor;

  int get percent => (_factor * 100).round();

  Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    final stored = prefs.getDouble(kUiTextScalePrefsKey);
    final next = clampUiTextScale(stored ?? kUiTextScaleDefault);
    if (next == _factor) {
      return;
    }
    _factor = next;
    notifyListeners();
  }

  Future<void> setFactor(double value) async {
    final next = clampUiTextScale(value);
    if (next == _factor) {
      return;
    }
    _factor = next;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setDouble(kUiTextScalePrefsKey, next);
  }

  Future<void> reset() => setFactor(kUiTextScaleDefault);

  Future<void> nudge(double delta) => setFactor(_factor + delta);
}

class UiTextScaleScope extends InheritedNotifier<UiTextScaleController> {
  const UiTextScaleScope({
    super.key,
    required UiTextScaleController controller,
    required super.child,
  }) : super(notifier: controller);

  static UiTextScaleController of(BuildContext context) {
    final scope =
        context.dependOnInheritedWidgetOfExactType<UiTextScaleScope>();
    assert(scope != null, 'UiTextScaleScope not found');
    return scope!.notifier!;
  }

  static UiTextScaleController? maybeOf(BuildContext context) {
    return context
        .dependOnInheritedWidgetOfExactType<UiTextScaleScope>()
        ?.notifier;
  }
}
