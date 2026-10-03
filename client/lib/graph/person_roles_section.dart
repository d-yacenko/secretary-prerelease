import 'package:flutter/material.dart';

import '../api/api_models.dart';
import '../api/secretary_api_client.dart';

String normalizePersonRoleText(String value) {
  return value.trim().replaceAll(RegExp(r'\s+'), ' ').toLowerCase();
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

class PersonRolesSection extends StatelessWidget {
  const PersonRolesSection({
    super.key,
    required this.person,
    required this.apiClient,
    required this.onChanged,
  });

  final PersonPresentation person;
  final SecretaryApiClient apiClient;
  final Future<void> Function() onChanged;

  @override
  Widget build(BuildContext context) {
    final active = person.roleAssignments.where((item) => item.state == 'active').toList();
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
                onPressed: () async {
                  await apiClient.retractPersonRole(
                    personId: person.personId,
                    assignmentId: role.id,
                  );
                  await onChanged();
                },
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
          personId: person.personId,
          apiClient: apiClient,
          onChanged: onChanged,
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
  final Future<void> Function() onChanged;

  @override
  State<_AddPersonRoleDialog> createState() => _AddPersonRoleDialogState();
}

class _AddPersonRoleDialogState extends State<_AddPersonRoleDialog> {
  final _role = TextEditingController();
  final _contextText = TextEditingController();
  List<PersonRoleTerm> _terms = const [];

  @override
  void initState() {
    super.initState();
    _load('');
  }

  @override
  void dispose() {
    _role.dispose();
    _contextText.dispose();
    super.dispose();
  }

  Future<void> _load(String value) async {
    final next = await widget.apiClient.searchPersonRoleTerms(query: value);
    if (mounted) {
      setState(() => _terms = next);
    }
  }

  Future<void> _assign(String role) async {
    await widget.apiClient.assignPersonRole(
      personId: widget.personId,
      role: role,
      context: _contextText.text,
    );
    if (mounted) {
      Navigator.of(context).pop();
    }
    await widget.onChanged();
  }

  @override
  Widget build(BuildContext context) {
    final typed = normalizePersonRoleText(_role.text);
    final exact = _terms.any(
      (term) => normalizePersonRoleText(term.displayText) == typed && typed.isNotEmpty,
    );
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
            if (typed.isNotEmpty && !exact)
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
          ],
        ),
      ),
    );
  }
}
