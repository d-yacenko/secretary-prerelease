import 'package:flutter/material.dart';

import '../api/api_models.dart';
import '../api/role_import_models.dart';

class RoleImportPreviewPanel extends StatelessWidget {
  const RoleImportPreviewPanel({
    super.key,
    required this.loading,
    required this.error,
    required this.preview,
    required this.onExtract,
    this.groundingLoading = false,
    this.groundingError,
    this.grounded,
    this.sourceStale = false,
    this.onGround,
    this.choices = const {},
    this.phase = RoleImportFlowPhase.editing,
    this.plan,
    this.planError,
    this.groundingStale = false,
    this.selectionFrozen = false,
    this.canPrepare = false,
    this.operationsEnabled = true,
    this.onToggleRow,
    this.onChoosePerson,
    this.onChoosePromotion,
    this.onPrepare,
    this.onApprove,
    this.onReject,
    this.onEditSelection,
  });

  final bool loading;
  final String? error;
  final RoleImportPreview? preview;
  final VoidCallback onExtract;
  final bool groundingLoading;
  final String? groundingError;
  final RoleImportGroundedPreview? grounded;
  final bool sourceStale;
  final VoidCallback? onGround;
  final Map<int, RoleImportRowChoice> choices;
  final RoleImportFlowPhase phase;
  final ActionPlanResponse? plan;
  final String? planError;
  final bool groundingStale;
  final bool selectionFrozen;
  final bool canPrepare;
  final bool operationsEnabled;
  final void Function(int rowIndex, bool selected)? onToggleRow;
  final void Function(int rowIndex, String personId)? onChoosePerson;
  final void Function(int rowIndex, String candidateKey)? onChoosePromotion;
  final VoidCallback? onPrepare;
  final VoidCallback? onApprove;
  final VoidCallback? onReject;
  final VoidCallback? onEditSelection;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          TextButton(
            key: const Key('extract_roles_button'),
            onPressed: loading ? null : onExtract,
            child: const Text('Извлечь роли'),
          ),
          if (loading)
            const Padding(
              padding: EdgeInsets.only(top: 8),
              child: CircularProgressIndicator(
                key: Key('role_import_loading'),
              ),
            ),
          if (error != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(error!, key: const Key('role_import_error')),
                  TextButton(
                    key: const Key('role_import_retry'),
                    onPressed: onExtract,
                    child: const Text('Повторить'),
                  ),
                ],
              ),
            ),
          if (preview != null) ...[
            Text(
              'Черновик извлечения ролей',
              key: const Key('role_import_heading'),
            ),
            if (_showsNothingSaved)
              const Text(
                'Ничего не сохранено',
                key: Key('role_import_nothing_saved'),
              ),
            if (_executedChanged)
              const Text(
                'Изменения сохранены',
                key: Key('role_import_saved'),
              ),
            if (_executedUnchanged)
              const Text(
                'Изменений нет',
                key: Key('role_import_no_changes'),
              ),
            if (preview!.items.isEmpty)
              const Text(
                'Роли не найдены',
                key: Key('role_import_empty'),
              ),
            if (preview!.sourceTruncated || preview!.itemsTruncated)
              const Text(
                'Источник или список строк обрезан',
                key: Key('role_import_truncation'),
              ),
            for (final item in preview!.items)
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(item.personName),
                  Text(item.role),
                  if (item.contextText != null) Text(item.contextText!),
                  Text(item.evidenceText),
                  if (item.sourceLocator != null) Text(item.sourceLocator!),
                ],
              ),
            if (preview!.items.isNotEmpty && onGround != null && !sourceStale)
              TextButton(
                key: const Key('ground_roles_button'),
                onPressed: loading || groundingLoading ? null : onGround,
                child: const Text('Сопоставить'),
              ),
            if (sourceStale)
              const Text(
                'Источник изменился — извлеките роли заново',
                key: Key('role_import_source_stale'),
              ),
            if (groundingLoading)
              const Padding(
                padding: EdgeInsets.only(top: 8),
                child: CircularProgressIndicator(
                  key: Key('role_grounding_loading'),
                ),
              ),
            if (groundingError != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(
                  groundingError!,
                  key: const Key('role_grounding_error'),
                ),
              ),
            if (groundingStale)
              const Text(
                'Сопоставление изменилось — сопоставьте роли заново',
                key: Key('role_import_grounding_stale'),
              ),
            if (grounded != null && !sourceStale && !groundingStale) ...[
              const Text(
                'Показаны только люди с подтверждением в сохранённой переписке',
                key: Key('role_import_communication_note'),
              ),
              if (grounded!.items.isEmpty)
                const Text(
                  'Среди извлечённых строк нет людей с подтверждением в сохранённой переписке',
                  key: Key('role_import_no_communication'),
                ),
              for (final item in grounded!.items)
                _GroundedRow(
                  item: item,
                  choice: choices[item.rowIndex],
                  frozen: selectionFrozen,
                  onToggle: onToggleRow,
                  onChoosePerson: onChoosePerson,
                  onChoosePromotion: onChoosePromotion,
                ),
            ],
            if (grounded != null &&
                grounded!.items.isNotEmpty &&
                !sourceStale &&
                !groundingStale &&
                onPrepare != null &&
                phase == RoleImportFlowPhase.editing)
              TextButton(
                key: const Key('prepare_role_import_button'),
                onPressed: canPrepare && operationsEnabled ? onPrepare : null,
                child: const Text('Подготовить изменения'),
              ),
            if (planError != null)
              Text(planError!, key: const Key('role_import_plan_error')),
            if (plan != null) _RoleImportPlanCard(plan: plan!, phase: phase),
            if (phase == RoleImportFlowPhase.pending && operationsEnabled) ...[
              TextButton(
                key: const Key('role_import_confirm'),
                onPressed: onApprove,
                child: const Text('Подтвердить'),
              ),
              TextButton(
                key: const Key('role_import_reject'),
                onPressed: onReject,
                child: const Text('Отклонить'),
              ),
            ],
            if (_canEditSelection)
              TextButton(
                key: const Key('role_import_edit_selection'),
                onPressed: onEditSelection,
                child: const Text('Изменить выбор'),
              ),
          ],
        ],
      ),
    );
  }

  bool get _executedChanged =>
      phase == RoleImportFlowPhase.executed && _batchChanged == true;

  bool get _executedUnchanged =>
      phase == RoleImportFlowPhase.executed && _batchChanged == false;

  bool get _showsNothingSaved =>
      phase != RoleImportFlowPhase.executed;

  bool? get _batchChanged {
    final changed = roleImportBatchOutput(plan)?['changed'];
    return changed is bool ? changed : null;
  }

  bool get _canEditSelection =>
      onEditSelection != null &&
      !sourceStale &&
      !groundingStale &&
      grounded != null &&
      (phase == RoleImportFlowPhase.rejected ||
          phase == RoleImportFlowPhase.expired ||
          phase == RoleImportFlowPhase.failed);
}

class _GroundedRow extends StatelessWidget {
  const _GroundedRow({
    required this.item,
    required this.choice,
    required this.frozen,
    this.onToggle,
    this.onChoosePerson,
    this.onChoosePromotion,
  });

  final RoleImportGroundedItem item;
  final RoleImportRowChoice? choice;
  final bool frozen;
  final void Function(int rowIndex, bool selected)? onToggle;
  final void Function(int rowIndex, String personId)? onChoosePerson;
  final void Function(int rowIndex, String candidateKey)? onChoosePromotion;

  @override
  Widget build(BuildContext context) {
    final person = item.personResolution;
    final role = item.roleResolution;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (person.state == 'resolved') ...[
          Text('Person: ${person.title}', key: const Key('role_person_resolved')),
          if (onToggle != null)
            Checkbox(
              key: Key('role_import_select_${item.rowIndex}'),
              value: choice?.selected ?? false,
              onChanged: frozen
                  ? null
                  : (value) => onToggle!(item.rowIndex, value ?? false),
            ),
        ],
        if (person.state == 'ambiguous') ...[
          const Text('Нужно выбрать Person', key: Key('role_person_ambiguous')),
          for (final candidate in person.candidates)
            TextButton(
              key: Key('role_import_choose_person_${candidate.personId}'),
              onPressed: frozen || onChoosePerson == null
                  ? null
                  : () => onChoosePerson!(item.rowIndex, candidate.personId),
              child: Text(candidate.title),
            ),
          if (onToggle != null)
            Checkbox(
              key: Key('role_import_select_${item.rowIndex}'),
              value: choice?.selected ?? false,
              onChanged: frozen ||
                      choice?.personId == null ||
                      onToggle == null
                  ? null
                  : (value) => onToggle!(item.rowIndex, value ?? false),
            ),
        ],
        if (person.state == 'promotion_candidates') ...[
          if (person.promotionCandidates.any(
            (candidate) => candidate.evidenceKind != 'name_mentions',
          ))
            const Text(
              'После подтверждения будет создан новый Person',
              key: Key('role_person_promotion'),
            ),
          for (final candidate in person.promotionCandidates)
            if (candidate.evidenceKind == 'name_mentions') ...[
              Text(
                'Упомянут в переписке: ${candidate.communicationCount} сообщений',
                key: Key('role_import_mention_count_${item.rowIndex}'),
              ),
              const Text(
                'Контактная личность не установлена',
                key: Key('role_import_mention_unknown'),
              ),
              const Text(
                'После подтверждения будет создан новый Person без привязки контакта',
                key: Key('role_import_mention_create'),
              ),
              TextButton(
                key: Key('role_import_choose_promotion_${candidate.candidateKey}'),
                onPressed: frozen || onChoosePromotion == null
                    ? null
                    : () => onChoosePromotion!(
                          item.rowIndex,
                          candidate.candidateKey,
                        ),
                child: Text(candidate.displayName),
              ),
            ] else
              TextButton(
                key: Key('role_import_choose_promotion_${candidate.candidateKey}'),
                onPressed: frozen || onChoosePromotion == null
                    ? null
                    : () => onChoosePromotion!(
                          item.rowIndex,
                          candidate.candidateKey,
                        ),
                child: Text(
                  '${candidate.displayName} · ${candidate.provider} · ${candidate.directHitCount} в переписке',
                ),
              ),
          if (onToggle != null)
            Checkbox(
              key: Key('role_import_select_${item.rowIndex}'),
              value: choice?.selected ?? false,
              onChanged: frozen || choice?.promotionCandidateKey == null
                  ? null
                  : (value) => onToggle!(item.rowIndex, value ?? false),
            ),
        ],
        if (person.state == 'unresolved')
          const Text('Person не найден', key: Key('role_person_unresolved')),
        if (role.state == 'reuse_existing')
          Text(
            'Использовать существующую роль: ${role.displayText}',
            key: const Key('role_existing'),
          ),
        if (role.state == 'propose_new') ...[
          Text('Новая роль: ${role.displayText}', key: const Key('role_new')),
          if (role.suggestions.isNotEmpty) ...[
            const Text('Похожие термины', key: Key('role_suggestions')),
            for (final suggestion in role.suggestions)
              Text(suggestion, key: Key('role_suggestion_$suggestion')),
          ],
        ],
      ],
    );
  }
}

Map<String, dynamic>? roleImportBatchOutput(ActionPlanResponse? plan) {
  final result = plan?.result;
  if (result == null) {
    return null;
  }
  final actions = result['actions'];
  if (actions is! List || actions.isEmpty || actions.first is! Map) {
    return null;
  }
  final output = (actions.first as Map)['output'];
  if (output is! Map) {
    return null;
  }
  return Map<String, dynamic>.from(output);
}

class _RoleImportPlanCard extends StatelessWidget {
  const _RoleImportPlanCard({required this.plan, required this.phase});

  final ActionPlanResponse plan;
  final RoleImportFlowPhase phase;

  @override
  Widget build(BuildContext context) {
    final presentation = plan.actions.isEmpty
        ? null
        : plan.actions.first.presentation;
    final output = roleImportBatchOutput(plan);
    final rows = presentation?['rows'];
    return Column(
      key: const Key('role_import_plan_card'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (phase == RoleImportFlowPhase.pending ||
            phase == RoleImportFlowPhase.approving ||
            phase == RoleImportFlowPhase.rejecting)
          const Text(
            'Требует подтверждения',
            key: Key('role_import_pending'),
          ),
        if (presentation != null) ...[
          Text(
            '${presentation['source_title'] ?? ''}',
            key: const Key('role_import_source_title'),
          ),
          Text(
            'Выбрано ${presentation['selected_count']} из ${presentation['total_extracted_rows']}',
            key: const Key('role_import_plan_counts'),
          ),
          if (presentation['source_truncated'] == true ||
              presentation['items_truncated'] == true)
            const Text(
              'Источник или список строк обрезан',
              key: Key('role_import_plan_truncation'),
            ),
          if (rows is List)
            for (final row in rows.whereType<Map>())
              Text(
                '${row['target_display']} · ${_targetMode(row['target_mode'])} · ${row['role']}'
                '${row['context'] == null ? '' : ' · ${row['context']}'} · ${_vocabularyMode(row['vocabulary_mode'])}',
              ),
        ],
        if (phase == RoleImportFlowPhase.rejected)
          const Text('Отклонено', key: Key('role_import_rejected')),
        if (phase == RoleImportFlowPhase.expired)
          const Text(
            'Подтверждение истекло',
            key: Key('role_import_expired'),
          ),
        if (phase == RoleImportFlowPhase.failed) ...[
          const Text('Ошибка применения', key: Key('role_import_failed')),
          if (plan.failure != null) Text(plan.failure!),
        ],
        if (output != null && phase == RoleImportFlowPhase.executed) ...[
          Text('Создано людей: ${output['people_created']}'),
          Text('Назначений изменено: ${output['assignments_changed']}'),
          Text('Без изменений: ${output['assignments_no_op']}'),
          Text('Дубликаты: ${output['duplicate_rows']}'),
          for (final row in _outputRows(output))
            Text(_statusLabel(row['status'])),
        ],
      ],
    );
  }

  static String _targetMode(Object? mode) {
    if (mode == 'name_mentions') {
      return 'новый Person без привязки контакта';
    }
    if (mode == 'promote_person') {
      return 'новый Person';
    }
    return 'existing Person';
  }

  static String _vocabularyMode(Object? mode) {
    if (mode == 'create_if_missing') {
      return 'новая роль';
    }
    return 'существующая роль';
  }

  static String _statusLabel(Object? status) {
    switch (status) {
      case 'applied':
        return 'Применено';
      case 'already_active':
        return 'Уже было';
      case 'duplicate_selected_row':
        return 'Дубликат выбранной строки';
      default:
        return '';
    }
  }

  static List<Map> _outputRows(Map<String, dynamic> output) {
    final rows = output['rows'];
    if (rows is! List) {
      return const [];
    }
    return rows.whereType<Map>().toList();
  }
}
