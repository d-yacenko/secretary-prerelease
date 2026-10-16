import 'package:flutter/material.dart';

import '../api/api_models.dart';

/// Client-only visual identity for active Person role contexts.
///
/// Nothing here is persisted. The same normalized context always maps to the
/// same key and tint; related contexts share a family with a nearby shade.
class PersonContextVisual {
  const PersonContextVisual({
    required this.exactKey,
    required this.familyKey,
    required this.sortKey,
    required this.shade,
    required this.multiple,
  });

  const PersonContextVisual.none()
    : exactKey = null,
      familyKey = null,
      sortKey = '',
      shade = 0,
      multiple = false;

  final String? exactKey;
  final String? familyKey;
  final String sortKey;
  final int shade;
  final bool multiple;
}

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
  final hue = (_stableHash(family) % 360).toDouble();
  final shade = visual.shade;
  final light = scheme.brightness == Brightness.dark
      ? 0.42 + shade * 0.03
      : 0.62 + shade * 0.03;
  final tint = HSLColor.fromAHSL(
    1,
    hue,
    0.42,
    light.clamp(0.25, 0.86),
  ).toColor();
  return Color.alphaBlend(tint.withValues(alpha: 0.34), scheme.surface);
}

int _stableHash(String value) {
  var hash = 0;
  for (final unit in value.codeUnits) {
    hash = (hash * 33 + unit) & 0x7fffffff;
  }
  return hash;
}
