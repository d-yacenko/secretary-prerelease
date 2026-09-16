import 'package:flutter_test/flutter_test.dart';

import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/objects/object_delete_actions.dart';

void main() {
  test('delete confirmation for note is secretary-only', () {
    final object = SecretaryObject(
      id: '2',
      kind: 'note',
      title: 'Note',
      metadata: const {},
      origin: 'user',
      state: 'confirmed',
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    );
    expect(deleteConfirmationMessage(object), 'Удалить из Секретаря?');
    expect(deleteConfirmationMessage(object), isNot(contains('Gmail')));
  });

  test('delete confirmation for local file mentions device', () {
    final object = SecretaryObject(
      id: '1',
      kind: 'file',
      title: 'Local doc',
      provider: 'local_device',
      metadata: const {},
      origin: 'explicit',
      state: 'confirmed',
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    );
    expect(
      deleteConfirmationMessage(object),
      contains('устройстве'),
    );
  });

  test('delete confirmation for mattermost mentions upstream', () {
    final object = SecretaryObject(
      id: '3',
      kind: 'chat_message',
      title: 'MM',
      provider: 'mattermost',
      metadata: const {},
      origin: 'source',
      state: 'observed',
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    );
    expect(deleteConfirmationMessage(object), contains('Mattermost'));
  });

  test('delete confirmation for local folder mentions device folder', () {
    final object = SecretaryObject(
      id: '4',
      kind: 'folder',
      title: 'Projects',
      provider: 'local_device',
      metadata: const {},
      origin: 'source',
      state: 'observed',
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    );
    expect(deleteConfirmationMessage(object), contains('папка'));
  });

  SecretaryObject obj({
    required String kind,
    String? provider,
  }) {
    return SecretaryObject(
      id: 'x',
      kind: kind,
      title: 't',
      provider: provider,
      metadata: const {},
      origin: 'source',
      state: 'observed',
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    );
  }

  test('direct swipe delete is fail-closed to known provider sources', () {
    expect(
      objectSupportsDeliberateSwipeDeleteWithoutDialog(
        obj(kind: 'email', provider: 'gmail'),
      ),
      isTrue,
    );
    expect(
      objectSupportsDeliberateSwipeDeleteWithoutDialog(
        obj(kind: 'email', provider: 'yandex_mail'),
      ),
      isTrue,
    );
    expect(
      objectSupportsDeliberateSwipeDeleteWithoutDialog(
        obj(kind: 'event', provider: 'google_calendar'),
      ),
      isTrue,
    );
    expect(
      objectSupportsDeliberateSwipeDeleteWithoutDialog(
        obj(kind: 'event', provider: 'yandex_calendar'),
      ),
      isTrue,
    );
    expect(
      objectSupportsDeliberateSwipeDeleteWithoutDialog(
        obj(kind: 'chat_message', provider: 'mattermost'),
      ),
      isTrue,
    );
    expect(
      objectSupportsDeliberateSwipeDeleteWithoutDialog(
        obj(kind: 'file', provider: 'google_drive'),
      ),
      isTrue,
    );
    expect(
      objectSupportsDeliberateSwipeDeleteWithoutDialog(
        obj(kind: 'file', provider: 'yandex_disk'),
      ),
      isTrue,
    );
    expect(
      objectSupportsDeliberateSwipeDeleteWithoutDialog(
        obj(kind: 'file', provider: 'local_device'),
      ),
      isTrue,
    );
    expect(
      objectSupportsDeliberateSwipeDeleteWithoutDialog(obj(kind: 'web_page')),
      isTrue,
    );
  });

  test('task, note, and unknown kinds keep the confirmation dialog', () {
    expect(
      objectSupportsDeliberateSwipeDeleteWithoutDialog(obj(kind: 'task')),
      isFalse,
    );
    expect(
      objectSupportsDeliberateSwipeDeleteWithoutDialog(
        obj(kind: 'task', provider: 'gmail'),
      ),
      isFalse,
    );
    expect(
      objectSupportsDeliberateSwipeDeleteWithoutDialog(obj(kind: 'note')),
      isFalse,
    );
    expect(
      objectSupportsDeliberateSwipeDeleteWithoutDialog(
        obj(kind: 'chat_message', provider: 'telegram'),
      ),
      isFalse,
    );
    expect(
      objectSupportsDeliberateSwipeDeleteWithoutDialog(obj(kind: 'file')),
      isFalse,
    );
    expect(
      objectSupportsDeliberateSwipeDeleteWithoutDialog(obj(kind: 'email')),
      isFalse,
    );
  });
}
