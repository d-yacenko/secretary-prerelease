import 'package:flutter/material.dart';

import '../api/api_error.dart';
import '../api/api_models.dart';
import '../api/secretary_api_client.dart';
import '../auth/auth_controller.dart';
import '../ui/domain_labels.dart';

bool canAttachTaskDependency(String taskId, String candidateId) {
  return candidateId.isNotEmpty && candidateId != taskId;
}

Widget? _cue(String? first, String second) {
  final parts = [
    if (first != null && first.isNotEmpty) first,
    if (second.isNotEmpty) second,
  ];
  if (parts.isEmpty) {
    return null;
  }
  return Text(parts.join(' • '));
}

const List<(String, String)> _actorRoles = [
  ('requested_by', 'Запросил'),
  ('delegated_to', 'Поручено'),
  ('waiting_on', 'Ждём'),
  ('involves', 'Участвует'),
];

class TaskProfileSection extends StatefulWidget {
  const TaskProfileSection({
    super.key,
    required this.taskId,
    required this.apiClient,
    required this.authController,
    required this.onOpenPerson,
    required this.onOpenTask,
    required this.onOpenEvidence,
  });

  final String taskId;
  final SecretaryApiClient apiClient;
  final AuthController authController;
  final Future<void> Function(String personId) onOpenPerson;
  final Future<void> Function(String taskId) onOpenTask;
  final Future<void> Function(String objectId) onOpenEvidence;

  @override
  State<TaskProfileSection> createState() => _TaskProfileSectionState();
}

class _TaskProfileSectionState extends State<TaskProfileSection> {
  TaskProfile? _profile;
  Object? _error;
  bool _loading = false;
  int _requestId = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(TaskProfileSection oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.taskId != widget.taskId) {
      _profile = null;
      _error = null;
      _load();
    }
  }

  Future<void> _load() async {
    final requestId = ++_requestId;
    final taskId = widget.taskId;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final profile = await widget.apiClient.getTaskProfile(taskId);
      if (!mounted || requestId != _requestId) {
        return;
      }
      setState(() {
        _profile = profile;
        _loading = false;
      });
    } on AuthenticationException {
      if (!mounted || requestId != _requestId) {
        return;
      }
      widget.authController.handleAuthenticationFailure();
      setState(() => _loading = false);
    } catch (error) {
      if (!mounted || requestId != _requestId) {
        return;
      }
      setState(() {
        _error = error;
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Профиль задачи', style: Theme.of(context).textTheme.titleSmall),
        if (_loading)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 8),
            child: Text('Загрузка профиля'),
          ),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Row(
              children: [
                const Expanded(
                  child: Text('Не удалось загрузить профиль задачи'),
                ),
                TextButton(onPressed: _load, child: const Text('Повторить')),
              ],
            ),
          ),
        if (_profile != null) ...[
          _actorGroup('Запросил', _profile!.requestedBy, _profile!.requestedByTruncated),
          _actorGroup('Поручено', _profile!.delegatedTo, _profile!.delegatedToTruncated),
          _actorGroup('Ждём', _profile!.waitingOn, _profile!.waitingOnTruncated),
          _actorGroup('Участвует', _profile!.involves, _profile!.involvesTruncated),
          _linkGroup(
            'Зависит от',
            _profile!.dependsOn,
            truncated: _profile!.dependsOnTruncated,
            removable: true,
            onOpen: widget.onOpenTask,
            onRemove: (edgeId) => widget.apiClient.removeTaskDependency(
              taskId: widget.taskId,
              edgeId: edgeId,
            ),
          ),
          _linkGroup(
            dependentTasksLabel,
            _profile!.dependentTasks,
            truncated: _profile!.dependentTasksTruncated,
            removable: false,
            onOpen: widget.onOpenTask,
          ),
          _linkGroup(
            taskEvidenceSectionLabel,
            _profile!.evidence,
            truncated: _profile!.evidenceTruncated,
            removable: false,
            onOpen: widget.onOpenEvidence,
          ),
          const SizedBox(height: 4),
          Wrap(
            spacing: 8,
            children: [
              TextButton(
                onPressed: _addPerson,
                child: const Text('Добавить человека'),
              ),
              TextButton(
                onPressed: _addDependency,
                child: const Text('Добавить зависимость'),
              ),
            ],
          ),
        ],
      ],
    );
  }

  Widget _actorGroup(String label, List<TaskActorItem> items, bool truncated) {
    if (items.isEmpty) {
      return const SizedBox.shrink();
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SizedBox(height: 8),
        Text(label, style: Theme.of(context).textTheme.labelLarge),
        ...items.map((item) => _actorTile(item)),
        if (truncated)
          const Text('Показаны не все'),
      ],
    );
  }

  Widget _actorTile(TaskActorItem item) {
    final proposal = taskRelationProposalLabel(item.edgeOrigin, item.edgeState);
    return ListTile(
      dense: true,
      contentPadding: EdgeInsets.zero,
      title: Text(item.title),
      subtitle: _cue(item.contactCue, proposal),
      onTap: () => widget.onOpenPerson(item.personId),
      trailing: _relationActions(
        edgeId: item.edgeId,
        origin: item.edgeOrigin,
        state: item.edgeState,
        removeTooltip: 'Убрать роль',
        onRemove: () => widget.apiClient.removeTaskActor(
          taskId: widget.taskId,
          edgeId: item.edgeId,
        ),
      ),
    );
  }

  Widget _linkGroup(
    String label,
    List<TaskLinkItem> items, {
    required bool truncated,
    required bool removable,
    required Future<void> Function(String objectId) onOpen,
    Future<TaskRelationMutation> Function(String edgeId)? onRemove,
  }) {
    if (items.isEmpty) {
      return const SizedBox.shrink();
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SizedBox(height: 8),
        Text(label, style: Theme.of(context).textTheme.labelLarge),
        ...items.map((item) {
          final proposal = taskRelationProposalLabel(item.edgeOrigin, item.edgeState);
          return ListTile(
            dense: true,
            contentPadding: EdgeInsets.zero,
            title: Text(item.title),
            subtitle: _cue(objectKindLabel(item.kind), proposal),
            onTap: () => onOpen(item.objectId),
            trailing: _relationActions(
              edgeId: item.edgeId,
              origin: item.edgeOrigin,
              state: item.edgeState,
              removeTooltip: 'Убрать зависимость',
              onRemove: removable && onRemove != null
                  ? () => onRemove(item.edgeId)
                  : null,
            ),
          );
        }),
        if (truncated)
          const Text('Показаны не все'),
      ],
    );
  }

  Widget? _relationActions({
    required String edgeId,
    required String origin,
    required String state,
    required String removeTooltip,
    required Future<TaskRelationMutation> Function()? onRemove,
  }) {
    if (state == 'proposed') {
      return Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          IconButton(
            tooltip: 'Подтвердить',
            icon: const Icon(Icons.check_circle_outline),
            onPressed: () => _decide(edgeId, 'confirm'),
          ),
          IconButton(
            tooltip: 'Отклонить',
            icon: const Icon(Icons.cancel_outlined),
            onPressed: () => _decide(edgeId, 'reject'),
          ),
        ],
      );
    }
    if (state == 'confirmed' &&
        (origin == 'user' || origin == 'agent') &&
        onRemove != null) {
      return IconButton(
        tooltip: removeTooltip,
        icon: const Icon(Icons.close),
        onPressed: () => _mutate(onRemove),
      );
    }
    return null;
  }

  Future<void> _decide(String edgeId, String decision) async {
    try {
      await widget.apiClient.decideRelation(edgeId: edgeId, decision: decision);
      await _load();
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (error) {
      _showError(error.message);
    }
  }

  Future<void> _mutate(Future<TaskRelationMutation> Function() action) async {
    try {
      await action();
      await _load();
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (error) {
      _showError(error.message);
    }
  }

  Future<void> _addPerson() async {
    String role = 'waiting_on';
    SecretaryObject? person;
    final queryController = TextEditingController();
    List<SecretaryObject> options = [];
    final selected = await showDialog<({String role, String personId})>(
      context: context,
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setState) {
            return AlertDialog(
              title: const Text('Добавить человека'),
              content: SizedBox(
                width: 360,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    DropdownButtonFormField<String>(
                      value: role,
                      items: [
                        for (final item in _actorRoles)
                          DropdownMenuItem(value: item.$1, child: Text(item.$2)),
                      ],
                      onChanged: (value) {
                        if (value != null) {
                          setState(() => role = value);
                        }
                      },
                    ),
                    TextField(
                      controller: queryController,
                      decoration: const InputDecoration(labelText: 'Поиск человека'),
                      onSubmitted: (value) async {
                        final workspace = await widget.apiClient.getPeopleWorkspace(
                          query: value,
                        );
                        setState(() {
                          options = workspace.nodes
                              .where((node) => node.kind == 'person')
                              .toList();
                        });
                      },
                    ),
                    ...options.map(
                      (item) => ListTile(
                        title: Text(item.title),
                        selected: person?.id == item.id,
                        onTap: () => setState(() => person = item),
                      ),
                    ),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text('Отмена'),
                ),
                FilledButton(
                  onPressed: person == null
                      ? null
                      : () => Navigator.pop(
                            context,
                            (role: role, personId: person!.id),
                          ),
                  child: const Text('Добавить'),
                ),
              ],
            );
          },
        );
      },
    );
    queryController.dispose();
    if (selected == null) {
      return;
    }
    await _mutate(
      () => widget.apiClient.addTaskActor(
        taskId: widget.taskId,
        personId: selected.personId,
        role: selected.role,
      ),
    );
  }

  Future<void> _addDependency() async {
    SecretaryObject? target;
    final queryController = TextEditingController();
    List<SecretaryObject> options = [];
    final selectedId = await showDialog<String>(
      context: context,
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setState) {
            return AlertDialog(
              title: const Text('Добавить зависимость'),
              content: SizedBox(
                width: 360,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    TextField(
                      decoration: const InputDecoration(labelText: 'Поиск задачи'),
                      controller: queryController,
                      onSubmitted: (value) async {
                        final results = await widget.apiClient.searchObjects(
                          query: value,
                          kind: 'task',
                        );
                        setState(() {
                          options = results
                              .where(
                                (item) => canAttachTaskDependency(widget.taskId, item.id),
                              )
                              .toList();
                        });
                      },
                    ),
                    ...options.map(
                      (item) => ListTile(
                        title: Text(item.title),
                        selected: target?.id == item.id,
                        onTap: () => setState(() => target = item),
                      ),
                    ),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text('Отмена'),
                ),
                FilledButton(
                  onPressed: target == null ||
                          !canAttachTaskDependency(widget.taskId, target!.id)
                      ? null
                      : () => Navigator.pop(context, target!.id),
                  child: const Text('Добавить'),
                ),
              ],
            );
          },
        );
      },
    );
    queryController.dispose();
    if (selectedId == null || !canAttachTaskDependency(widget.taskId, selectedId)) {
      return;
    }
    await _mutate(
      () => widget.apiClient.addTaskDependency(
        taskId: widget.taskId,
        dependsOnTaskId: selectedId,
      ),
    );
  }

  void _showError(String message) {
    if (!mounted) {
      return;
    }
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }
}
