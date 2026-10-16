import 'package:flutter/material.dart';

import '../api/api_models.dart';

/// Client-only visual identity for active Person role contexts.
///
/// The mapping is a pure function of the normalized context. Nothing is
/// persisted, and the same exact context keeps one color in every cluster.
/// Related contexts share a family hue; [hueOffset] is a bounded exact-context
/// shift inside that hue, at most ±[kContextHueOffsetDegrees].
class PersonContextVisual {
  const PersonContextVisual({
    required this.exactKey,
    required this.familyKey,
    required this.sortKey,
    required this.shade,
    required this.multiple,
    this.hueOffset = 0,
  });

  const PersonContextVisual.none()
    : exactKey = null,
      familyKey = null,
      sortKey = '',
      shade = 0,
      multiple = false,
      hueOffset = 0;

  final String? exactKey;
  final String? familyKey;
  final String sortKey;
  final int shade;
  final bool multiple;
  final double hueOffset;
}

/// Maximum exact-context hue shift away from the family base hue.
const double kContextHueOffsetDegrees = 22;

/// Minimum Euclidean RGB distance, in 0–1 channels, required between two
/// related exact-context card colors. The HG6A shade step stays below this.
const double kContextCardMinSeparation = 0.08;

const _genericContextTokens = {
  'ао',
  'группа',
  'группы',
  'зао',
  'и',
  'компания',
  'компании',
  'ооо',
  'пао',
  'университет',
  'университета',
  'company',
  'gmbh',
  'group',
  'гк',
  'inc',
  'llc',
  'ltd',
  'of',
  'the',
  'university',
};

String normalizePersonContext(String raw) {
  final separated = raw.toLowerCase().replaceAll(
    RegExp(r'[^\p{L}\p{N}]+', unicode: true),
    ' ',
  );
  return separated.replaceAll(RegExp(r'\s+'), ' ').trim();
}

String? personContextFamilyKey(String normalized) {
  if (normalized.isEmpty) {
    return null;
  }
  final tokens = normalized.split(' ');
  while (tokens.isNotEmpty && _genericContextTokens.contains(tokens.last)) {
    tokens.removeLast();
  }
  if (tokens.isEmpty) {
    return normalized;
  }
  return tokens.last;
}

PersonContextVisual personContextVisual(List<PersonRoleAssignment> roles) {
  final exacts = <String>{};
  for (final role in roles) {
    if (role.state != 'active') {
      continue;
    }
    final context = role.context;
    if (context == null) {
      continue;
    }
    final key = normalizePersonContext(context);
    if (key.isEmpty) {
      continue;
    }
    exacts.add(key);
  }
  final sorted = exacts.toList()..sort();
  if (sorted.isEmpty) {
    return const PersonContextVisual.none();
  }
  if (sorted.length == 1) {
    final exact = sorted.single;
    final family = personContextFamilyKey(exact);
    return PersonContextVisual(
      exactKey: exact,
      familyKey: family,
      sortKey: '${family ?? ''}\u0001$exact',
      shade: _stableHash(exact) % 5,
      hueOffset: _exactHueOffset(exact),
      multiple: false,
    );
  }
  final signature = sorted.join('\u0001');
  return PersonContextVisual(
    exactKey: null,
    familyKey: 'multi:${_stableHash(signature)}',
    sortKey: 'multi\u0001$signature',
    shade: 0,
    multiple: true,
  );
}

Color contextCardColor(ColorScheme scheme, PersonContextVisual visual) {
  final family = visual.familyKey;
  if (family == null || family.isEmpty) {
    return scheme.surface;
  }
  final baseHue = (_stableHash(family) % 360).toDouble();
  final exact = visual.exactKey ?? family;
  final hue = (baseHue + visual.hueOffset) % 360;
  final saturation = 0.52 + _unit(exact, 2) * 0.28;
  final lightness =
      (scheme.brightness == Brightness.dark ? 0.46 : 0.56) +
      (_unit(exact, 3) - 0.5) * 0.18;
  final tint = HSLColor.fromAHSL(
    1,
    hue,
    saturation.clamp(0, 1),
    lightness.clamp(0.28, 0.78),
  ).toColor();
  return Color.alphaBlend(tint.withValues(alpha: 0.7), scheme.surface);
}

double _exactHueOffset(String exact) {
  return (_unit(exact, 1) - 0.5) * 2 * kContextHueOffsetDegrees;
}

double _unit(String value, int salt) {
  return (_stableHash('$salt:$value') % 1000) / 999;
}

int _stableHash(String value) {
  var hash = 0;
  for (final unit in value.codeUnits) {
    hash = (hash * 33 + unit) & 0x7fffffff;
  }
  return hash;
}
