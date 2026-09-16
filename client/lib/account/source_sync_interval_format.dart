/// Standard recurring sync cadence presets (seconds).
const List<int> standardSyncIntervalPresets = [
  60,
  120,
  300,
  600,
  900,
  1800,
  3600,
  7200,
  14400,
  28800,
  86400,
];

/// Friendly Russian label for a sync interval in seconds.
String formatSyncIntervalSeconds(int seconds) {
  if (seconds < 60) {
    return '$seconds с';
  }
  final totalMinutes = seconds ~/ 60;
  final hours = totalMinutes ~/ 60;
  final minutes = totalMinutes % 60;
  if (hours == 0) {
    return '$minutes мин';
  }
  if (minutes == 0) {
    return hours == 1 ? '1 ч' : '$hours ч';
  }
  return '$hours ч $minutes мин';
}

/// Preset cadence choices within server bounds; always includes [currentSeconds].
List<int> availableSyncIntervalChoices({
  required int currentSeconds,
  required int minSeconds,
  required int maxSeconds,
}) {
  final choices = <int>{};
  for (final preset in standardSyncIntervalPresets) {
    if (preset >= minSeconds && preset <= maxSeconds) {
      choices.add(preset);
    }
  }
  if (currentSeconds >= minSeconds && currentSeconds <= maxSeconds) {
    choices.add(currentSeconds);
  }
  final sorted = choices.toList()..sort();
  return sorted;
}
