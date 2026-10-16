import 'package:flutter/material.dart';

import '../api/api_error.dart';
import '../api/api_models.dart';
import '../api/secretary_api_client.dart';

const personRoleUpdateFailed = 'Не удалось обновить роль';
const personRoleSearchFailed = 'Не удалось загрузить роли';

/// User-facing role failure text. API detail is kept only when it is a short
/// sanitized message; stacks, SQL, and tokens stay hidden.
String personRoleFailureMessage(Object error, {required String fallback}) {
  if (error is! ApiException) {
    return fallback;
  }
  final message = SecretaryApiClient.sanitizeErrorMessage(error.message).trim();
  final lowered = message.toLowerCase();
  if (message.isEmpty ||
      message.length > 240 ||
      message.contains('\n') ||
      lowered.contains('traceback') ||
      lowered.contains('select ') ||
      lowered.contains('sqlalchemy') ||
      lowered.contains('psycopg')) {
    return fallback;
  }
  return message;
}

String _roleMutationError(Object error) {
  final message = personRoleFailureMessage(
    error,
    fallback: personRoleUpdateFailed,
  );
  if (message == personRoleUpdateFailed) {
    return personRoleUpdateFailed;
  }
  return '$personRoleUpdateFailed. $message';
}

String collapsePersonRoleText(String value) {
  return value.trim().replaceAll(RegExp(r'\s+'), ' ');
}

/// First one or two distinct role titles, plus an overflow count. No ids.
String? personRoleCardSummary(List<PersonRoleAssignment> roles) {
  final names = <String>[];
  final seen = <String>{};
  for (final role in roles) {
    if (role.state != 'active') {
      continue;
    }
    if (seen.add(role.roleDisplayText)) {
      names.add(role.roleDisplayText);
    }
  }
  if (names.isEmpty) {
    return null;
  }
  final shown = names.take(2).join(' · ');
  final extra = names.length - 2;
  if (extra > 0) {
    return '$shown +$extra';
  }
  return shown;
}

class PersonRolesSection extends StatefulWidget {
  const PersonRolesSection({
    super.key,
    required this.person,
    required this.apiClient,
    required this.onChanged,
  });

  final PersonPresentation person;
  final SecretaryApiClient apiClient;
  final Future<void> Function(PersonRoleAssignment assignment) onChanged;

  @override
  State<PersonRolesSection> createState() => _PersonRolesSectionState();
}

class _PersonRolesSectionState extends State<PersonRolesSection> {
  String? _error;

  Future<void> _retract(PersonRoleAssignment role) async {
    try {
      final updated = await widget.apiClient.retractPersonRole(
        personId: widget.person.personId,
        assignmentId: role.id,
      );
      if (!mounted) {
        return;
      }
      setState(() => _error = null);
      await widget.onChanged(updated);
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() => _error = _roleMutationError(error));
    }
  }

  @override
  Widget build(BuildContext context) {
    final person = widget.person;
    final active = person.roleAssignments
        .where((item) => item.state == 'active')
        .toList();
    return Column(
      key: const ValueKey('person-roles-section'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Роли', style: TextStyle(fontWeight: FontWeight.w700)),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton(
            key: const ValueKey('person-role-add'),
            onPressed: () => _openAdd(context),
            child: const Text('Добавить роль'),
          ),
        ),
        if (_error != null)
          Text(_error!, key: const ValueKey('person-role-error')),
        if (active.isEmpty)
          const Text('Нет ролей', key: ValueKey('person-role-empty'))
        else
          for (final role in active)
            ListTile(
              key: ValueKey('person-role-row-${role.id}'),
              dense: true,
              title: Text(role.label),
              trailing: TextButton(
                key: ValueKey('person-role-retract-${role.id}'),
                onPressed: () => _retract(role),
                child: const Text('Убрать'),
              ),
            ),
      ],
    );
  }

  Future<void> _openAdd(BuildContext context) {
    return showDialog<void>(
      context: context,
      builder: (dialogContext) {
        return _AddPersonRoleDialog(
          personId: widget.person.personId,
          apiClient: widget.apiClient,
          onChanged: widget.onChanged,
        );
      },
    );
  }
}

class _AddPersonRoleDialog extends StatefulWidget {
  const _AddPersonRoleDialog({
    required this.personId,
    required this.apiClient,
    required this.onChanged,
  });

  final String personId;
  final SecretaryApiClient apiClient;
  final Future<void> Function(PersonRoleAssignment assignment) onChanged;

  @override
  State<_AddPersonRoleDialog> createState() => _AddPersonRoleDialogState();
}

class _AddPersonRoleDialogState extends State<_AddPersonRoleDialog> {
  final _role = TextEditingController();
  final _contextText = TextEditingController();
  List<PersonRoleTerm> _terms = const [];
  String? _exactMatchTermId;
  int _searchGeneration = 0;
  bool _searchSettled = false;
  bool _searchFailed = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _search('');
  }

  @override
  void dispose() {
    _role.dispose();
    _contextText.dispose();
    super.dispose();
  }

  Future<void> _load(String value) {
    setState(() {
      _terms = const [];
      _exactMatchTermId = null;
      _searchSettled = false;
      _searchFailed = false;
      _error = null;
    });
    return _search(value);
  }

  Future<void> _search(String value) async {
    final generation = ++_searchGeneration;
    try {
      final next = await widget.apiClient.searchPersonRoleTerms(query: value);
      if (!mounted || generation != _searchGeneration) {
        return;
      }
      setState(() {
        _terms = next.terms;
        _exactMatchTermId = next.exactMatchTermId;
        _searchSettled = true;
        _searchFailed = false;
        _error = null;
      });
    } catch (error) {
      if (!mounted || generation != _searchGeneration) {
        return;
      }
      setState(() {
        _terms = const [];
        _exactMatchTermId = null;
        _searchSettled = true;
        _searchFailed = true;
        _error = personRoleFailureMessage(
          error,
          fallback: personRoleSearchFailed,
        );
      });
    }
  }

  Future<void> _assign(String role) async {
    try {
      final updated = await widget.apiClient.assignPersonRole(
        personId: widget.personId,
        role: role,
        context: _contextText.text,
      );
      if (!mounted) {
        return;
      }
      Navigator.of(context).pop();
      await widget.onChanged(updated);
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() => _error = _roleMutationError(error));
    }
  }

  @override
  Widget build(BuildContext context) {
    final typed = collapsePersonRoleText(_role.text);
    return AlertDialog(
      title: const Text('Добавить роль'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              key: const ValueKey('person-role-input'),
              controller: _role,
              decoration: const InputDecoration(labelText: 'Роль'),
              onChanged: _load,
            ),
            for (final term in _terms)
              ListTile(
                key: ValueKey('person-role-suggestion-${term.id}'),
                dense: true,
                title: Text(term.displayText),
                onTap: () => _assign(term.displayText),
              ),
            if (typed.isNotEmpty && _searchSettled && _searchFailed)
              TextButton(
                key: const ValueKey('person-role-use'),
                onPressed: () => _assign(_role.text),
                child: Text('Использовать роль «${_role.text.trim()}»'),
              ),
            if (typed.isNotEmpty &&
                _searchSettled &&
                !_searchFailed &&
                _exactMatchTermId == null)
              TextButton(
                key: const ValueKey('person-role-create'),
                onPressed: () => _assign(_role.text),
                child: Text('Создать роль «${_role.text.trim()}»'),
              ),
            TextField(
              key: const ValueKey('person-role-context'),
              controller: _contextText,
              decoration: const InputDecoration(labelText: 'Контекст'),
            ),
            if (_error != null)
              Text(_error!, key: const ValueKey('person-role-error')),
          ],
        ),
      ),
    );
  }
}
