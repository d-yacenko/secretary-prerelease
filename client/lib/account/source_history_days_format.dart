/// Standard history depth presets (days).
const List<int> standardHistoryDayPresets = [1, 3, 7, 14, 30, 60, 90];

/// Russian label for a history depth in days with correct day pluralization.
String formatHistoryDays(int days) {
  final mod10 = days % 10;
  final mod100 = days % 100;
  final String suffix;
  if (mod10 == 1 && mod100 != 11) {
    suffix = 'день';
  } else if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
    suffix = 'дня';
  } else {
    suffix = 'дней';
  }
  return '$days $suffix';
}

/// Preset history choices within server bounds; always includes [currentDays].
List<int> availableHistoryDayChoices({
  required int currentDays,
  required int minDays,
  required int maxDays,
}) {
  final choices = <int>{};
  for (final preset in standardHistoryDayPresets) {
    if (preset >= minDays && preset <= maxDays) {
      choices.add(preset);
    }
  }
  if (currentDays >= minDays && currentDays <= maxDays) {
    choices.add(currentDays);
  }
  final sorted = choices.toList()..sort();
  return sorted;
}
