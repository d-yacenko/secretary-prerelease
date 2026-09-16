import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/ui/object_presentation.dart';
import 'package:personal_secretary/ui/provider_icon.dart';

void main() {
  test('known object kind icon and label', () {
    expect(iconForKind('task'), isNotNull);
    expect(objectKindLabel('email'), 'Письмо');
    expect(iconForKind('folder'), Icons.folder_outlined);
    expect(objectKindLabel('folder'), 'Папка');
    expect(iconForKind('temporal_hint'), Icons.schedule_outlined);
    expect(objectKindLabel('temporal_hint'), 'Возможное время');
    expect(iconForKind('unknown_kind'), isNotNull);
    expect(objectKindLabel('unknown_kind'), 'unknown_kind');
  });

  test('provider labels', () {
    expect(providerLabel('gmail'), 'Gmail');
    expect(providerLabel('yandex_mail'), 'Яндекс');
    expect(providerLabel('yandex_calendar'), 'Яндекс Календарь');
    expect(providerLabel('google_calendar'), 'Google Календарь');
    expect(providerLabel('local_device'), 'Компьютер');
    expect(providerLabel('upload'), 'Загрузка');
    expect(providerLabel('web'), 'Веб');
    expect(providerLabel('custom_provider'), 'custom_provider');
    expect(providerLabel(null), 'Источник');
  });

  test('provider compact glyphs remain available as fallback labels', () {
    expect(providerCompactGlyph('yandex_calendar'), 'Я');
    expect(providerCompactGlyph('google_calendar'), 'G');
    expect(providerCompactGlyph('yandex_mail'), 'Я');
    expect(providerCompactGlyph('gmail'), 'G');
    expect(providerCompactGlyph('mattermost'), 'M');
    expect(providerCompactGlyph('telegram'), 'T');
    expect(providerCompactGlyph('teams'), 'Ms');
  });

  test('provider visuals use source marks not duplicated kind icons', () {
    expect(providerVisual('gmail').mark, ProviderSourceMark.google);
    expect(iconForKind('email'), Icons.email_outlined);
    expect(providerVisual('google_calendar').mark, ProviderSourceMark.google);
    expect(providerVisual('google_drive').mark, ProviderSourceMark.google);
    expect(providerVisual('yandex_mail').mark, ProviderSourceMark.yandex);
    expect(providerVisual('yandex_calendar').mark, ProviderSourceMark.yandex);
    expect(providerVisual('yandex_disk').mark, ProviderSourceMark.yandex);
    expect(providerVisual('mattermost').mark, ProviderSourceMark.mattermost);
    expect(providerVisual('telegram').mark, ProviderSourceMark.telegram);
    expect(providerVisual('teams').mark, ProviderSourceMark.teams);
    expect(providerVisual('local_device').icon, Icons.computer);
    expect(providerVisual('upload').icon, Icons.upload_file);
    expect(providerVisual('web').icon, Icons.language);
    expect(providerVisual('unknown-source').icon, Icons.source_outlined);
    expect(providerVisual('gmail').color, isNot(const Color(0xFF000000)));
  });
}
