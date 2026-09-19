import 'package:flutter/material.dart';

import '../api/api_error.dart';
import '../api/api_models.dart';
import '../api/secretary_api_client.dart';
import '../auth/auth_controller.dart';
import 'account_layout.dart';

enum _TelegramMtprotoAuthStep { phone, code, password }

/// Account-only Telegram MTProto setup. It intentionally keeps challenges in
/// memory and talks only to the Secretary API.
class TelegramMtprotoAccountSection extends StatefulWidget {
  const TelegramMtprotoAccountSection({
    super.key,
    required this.apiClient,
    required this.authController,
  });

  final SecretaryApiClient apiClient;
  final AuthController authController;

  @override
  State<TelegramMtprotoAccountSection> createState() =>
      _TelegramMtprotoAccountSectionState();
}

class _TelegramMtprotoAccountSectionState
    extends State<TelegramMtprotoAccountSection> {
  final _phoneController = TextEditingController();
  final _codeController = TextEditingController();
  final _passwordController = TextEditingController();
  TelegramMtprotoStatus? _status;
  TelegramMtprotoFolderList? _availableFolders;
  TelegramMtprotoScopePreview? _preview;
  TelegramMtprotoScopeReconcile? _reconcile;
  TelegramMtprotoGroupList? _groups;
  TelegramMtprotoHistorySync? _lastSync;
  String? _challengeId;
  String? _error;
  bool _configured = true;
  bool _loading = true;
  bool _busy = false;
  bool _scopeBusy = false;
  bool _groupsBusy = false;
  bool _ignoreMuted = true;
  _TelegramMtprotoAuthStep _authStep = _TelegramMtprotoAuthStep.phone;
  final Set<String> _selectedFolderNames = {};

  @override
  void initState() {
    super.initState();
    _loadStatus();
  }

  @override
  void dispose() {
    _clearChallenge();
    _phoneController.dispose();
    _codeController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  void _clearChallenge() {
    _challengeId = null;
    _codeController.clear();
    _passwordController.clear();
    _authStep = _TelegramMtprotoAuthStep.phone;
  }

  Future<void> _loadStatus() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final status = await widget.apiClient.getTelegramMtprotoStatus();
      if (!mounted) {
        return;
      }
      setState(() {
        _configured = status.configured;
        _status = status;
        _loading = false;
        _clearChallenge();
      });
      if (status.connected) await _loadScopeData();
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _configured = !error.message.toLowerCase().contains('not configured');
        _loading = false;
        _error = error.message;
      });
    } on StateError {
      if (mounted) {
        setState(() {
          _configured = false;
          _loading = false;
        });
      }
    }
  }

  Future<void> _startAuth() async {
    if (_busy || _phoneController.text.trim().isEmpty) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final result = await widget.apiClient.startTelegramMtprotoAuth(
        phone: _phoneController.text.trim(),
      );
      if (!mounted) return;
      setState(() {
        _challengeId = result.challengeId;
        _authStep = _TelegramMtprotoAuthStep.code;
        _codeController.clear();
        _passwordController.clear();
        _error = null;
      });
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _submitCode() async {
    final challengeId = _challengeId;
    if (_busy || challengeId == null || _codeController.text.trim().isEmpty) {
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final result = await widget.apiClient.submitTelegramMtprotoCode(
        challengeId: challengeId,
        code: _codeController.text.trim(),
      );
      if (!mounted) return;
      _codeController.clear();
      if (result.status == 'password_required') {
        setState(() {
          _authStep = _TelegramMtprotoAuthStep.password;
          _error = null;
        });
      } else {
        _clearChallenge();
        await _loadStatus();
      }
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _submitPassword() async {
    final challengeId = _challengeId;
    if (_busy || challengeId == null || _passwordController.text.isEmpty) {
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.apiClient.submitTelegramMtprotoPassword(
        challengeId: challengeId,
        password: _passwordController.text,
      );
      if (!mounted) return;
      _clearChallenge();
      await _loadStatus();
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _loadScopeData() async {
    setState(() => _scopeBusy = true);
    try {
      final results = await Future.wait([
        widget.apiClient.getTelegramMtprotoFolders(),
        widget.apiClient.getTelegramMtprotoSyncFolders(),
        widget.apiClient.getTelegramMtprotoGroups(),
      ]);
      if (!mounted) return;
      final configured = results[1] as TelegramMtprotoConfiguredFolders;
      setState(() {
        _availableFolders = results[0] as TelegramMtprotoFolderList;
        _groups = results[2] as TelegramMtprotoGroupList;
        _selectedFolderNames
          ..clear()
          ..addAll(configured.folders.map((folder) => folder.name));
        _ignoreMuted = configured.ignoreMuted;
        _scopeBusy = false;
      });
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (error) {
      if (mounted) {
        setState(() {
          _scopeBusy = false;
          _error = error.message;
        });
      }
    }
  }

  Future<void> _saveFolders() async {
    if (_scopeBusy) return;
    setState(() {
      _scopeBusy = true;
      _error = null;
    });
    try {
      await widget.apiClient.putTelegramMtprotoSyncFolders(
        folderNames: _selectedFolderNames.toList(),
        ignoreMuted: _ignoreMuted,
      );
      if (mounted) {
        setState(() {
          _scopeBusy = false;
        });
      }
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (error) {
      if (mounted) {
        setState(() {
          _scopeBusy = false;
          _error = error.message;
        });
      }
    }
  }

  Future<void> _previewScope() async {
    if (_scopeBusy) return;
    setState(() {
      _scopeBusy = true;
      _error = null;
    });
    try {
      final result = await widget.apiClient.previewTelegramMtprotoScope();
      if (mounted) {
        setState(() {
          _preview = result;
          _scopeBusy = false;
        });
      }
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (error) {
      if (mounted) {
        setState(() {
          _scopeBusy = false;
          _error = error.message;
        });
      }
    }
  }

  Future<void> _reconcileScope() async {
    if (_scopeBusy) return;
    setState(() {
      _scopeBusy = true;
      _error = null;
    });
    try {
      final result = await widget.apiClient.reconcileTelegramMtprotoScope();
      if (mounted) {
        setState(() {
          _reconcile = result;
          _scopeBusy = false;
        });
      }
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (error) {
      if (mounted) {
        setState(() {
          _scopeBusy = false;
          _error = error.message;
        });
      }
    }
  }

  Future<void> _toggleGroup(TelegramMtprotoGroup group, bool selected) async {
    if (_groupsBusy || !group.available) return;
    setState(() {
      _groupsBusy = true;
      _error = null;
    });
    try {
      await widget.apiClient.setTelegramMtprotoGroupSelected(
        peerId: group.peerId,
        selected: selected,
      );
      await _loadScopeData();
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _groupsBusy = false);
    }
  }

  Future<void> _syncPeer(int peerId) async {
    if (_groupsBusy) return;
    setState(() {
      _groupsBusy = true;
      _error = null;
    });
    try {
      final result = await widget.apiClient.syncTelegramMtprotoScopePeer(
        peerId,
      );
      if (mounted) setState(() => _lastSync = result);
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _groupsBusy = false);
    }
  }

  Future<void> _syncGroup(int peerId) async {
    if (_groupsBusy) return;
    setState(() {
      _groupsBusy = true;
      _error = null;
    });
    try {
      final result = await widget.apiClient.syncTelegramMtprotoGroup(peerId);
      if (mounted) setState(() => _lastSync = result);
    } on AuthenticationException {
      widget.authController.handleAuthenticationFailure();
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _groupsBusy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AccountSectionCard(
      key: const Key('telegram_mtproto_account_section'),
      title: 'Telegram MTProto',
      children: [
        if (_loading)
          const Center(child: CircularProgressIndicator())
        else if (!_configured)
          const Text('Telegram MTProto не настроен на сервере.')
        else ...[
          if (_error != null)
            Text(
              _error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          if (_status?.connected == true)
            _buildConnected(context)
          else
            _buildAuth(context),
        ],
      ],
    );
  }

  Widget _buildAuth(BuildContext context) {
    final challenge = _challengeId;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text('Аккаунт Telegram MTProto не подключён.'),
        const SizedBox(height: 8),
        TextField(
          key: const Key('telegram_mtproto_phone'),
          controller: _phoneController,
          keyboardType: TextInputType.phone,
          decoration: const InputDecoration(labelText: 'Телефон'),
          enabled: challenge == null && !_busy,
        ),
        const SizedBox(height: 8),
        FilledButton(
          key: const Key('telegram_mtproto_start_auth'),
          onPressed: challenge == null && !_busy ? _startAuth : null,
          child: Text(_busy ? 'Отправка…' : 'Получить код'),
        ),
        if (challenge != null &&
            _authStep == _TelegramMtprotoAuthStep.code) ...[
          const SizedBox(height: 12),
          TextField(
            key: const Key('telegram_mtproto_code'),
            controller: _codeController,
            decoration: const InputDecoration(labelText: 'Код Telegram'),
            enabled: !_busy,
          ),
          FilledButton(
            key: const Key('telegram_mtproto_submit_code'),
            onPressed: _busy ? null : _submitCode,
            child: const Text('Подтвердить код'),
          ),
          TextButton(
            key: const Key('telegram_mtproto_abandon'),
            onPressed: _busy ? null : () => setState(_clearChallenge),
            child: const Text('Отменить подключение'),
          ),
        ],
        if (challenge != null &&
            _authStep == _TelegramMtprotoAuthStep.password) ...[
          const SizedBox(height: 12),
          TextField(
            key: const Key('telegram_mtproto_password'),
            controller: _passwordController,
            obscureText: true,
            decoration: const InputDecoration(
              labelText: 'Пароль двухэтапной проверки',
            ),
            enabled: !_busy,
          ),
          FilledButton(
            key: const Key('telegram_mtproto_submit_password'),
            onPressed: _busy ? null : _submitPassword,
            child: const Text('Подтвердить пароль'),
          ),
          TextButton(
            key: const Key('telegram_mtproto_abandon'),
            onPressed: _busy ? null : () => setState(_clearChallenge),
            child: const Text('Отменить подключение'),
          ),
        ],
      ],
    );
  }

  Widget _buildConnected(BuildContext context) {
    final account = _status!.account!;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('Подключён: ${account.displayName ?? 'Без имени'}'),
        if (account.username != null) Text('@${account.username}'),
        Text('Telegram user id: ${account.telegramUserId}'),
        const Divider(height: 24),
        if (_scopeBusy && _availableFolders == null)
          const Center(child: CircularProgressIndicator())
        else ...[
          _buildFolders(context),
          const SizedBox(height: 12),
          _buildPreviewAndReconcile(context),
          const Divider(height: 24),
          _buildGroups(context),
        ],
      ],
    );
  }

  Widget _buildFolders(BuildContext context) {
    final folders =
        _availableFolders?.folders ?? const <TelegramMtprotoFolder>[];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          'Папки синхронизации',
          style: Theme.of(context).textTheme.titleSmall,
        ),
        if (_availableFolders?.truncated == true)
          const Text('Список папок ограничен провайдером.'),
        if (folders.isEmpty) const Text('Папки не выбраны.'),
        for (final folder in folders)
          CheckboxListTile(
            key: Key('telegram_mtproto_folder_${folder.folderId}'),
            contentPadding: EdgeInsets.zero,
            title: Text(folder.name),
            value: _selectedFolderNames.contains(folder.name),
            onChanged: _scopeBusy
                ? null
                : (value) => setState(() {
                    if (value == true) {
                      _selectedFolderNames.add(folder.name);
                    } else {
                      _selectedFolderNames.remove(folder.name);
                    }
                  }),
          ),
        SwitchListTile(
          key: const Key('telegram_mtproto_ignore_muted'),
          contentPadding: EdgeInsets.zero,
          title: const Text('Исключать заглушенные чаты'),
          value: _ignoreMuted,
          onChanged: _scopeBusy
              ? null
              : (value) => setState(() => _ignoreMuted = value),
        ),
        OutlinedButton(
          key: const Key('telegram_mtproto_save_folders'),
          onPressed: _scopeBusy ? null : _saveFolders,
          child: const Text('Сохранить папки'),
        ),
      ],
    );
  }

  Widget _buildPreviewAndReconcile(BuildContext context) {
    final preview = _preview;
    final reconcile = _reconcile;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Wrap(
          spacing: 8,
          children: [
            OutlinedButton(
              key: const Key('telegram_mtproto_preview_scope'),
              onPressed: _scopeBusy ? null : _previewScope,
              child: const Text('Предпросмотр области'),
            ),
            FilledButton(
              key: const Key('telegram_mtproto_reconcile_scope'),
              onPressed: _scopeBusy ? null : _reconcileScope,
              child: const Text('Применить область'),
            ),
          ],
        ),
        if (preview != null) ...[
          Text(
            'В области: ${preview.dialogs.length}; папок: ${preview.configuredFolderCount}',
          ),
          Text('Пропущено: ${preview.skippedCounts}'),
          if (preview.truncated) const Text('Предпросмотр усечён.'),
          for (final dialog in preview.dialogs) _peerRow(dialog),
        ],
        if (reconcile != null) ...[
          Text(
            'Область: ${reconcile.active}; добавлено ${reconcile.activated}; '
            'убрано ${reconcile.deactivated}; без изменений ${reconcile.unchanged}',
          ),
          for (final dialog in _scopeDialogs(reconcile)) _peerRow(dialog),
        ],
      ],
    );
  }

  List<TelegramMtprotoDialog> _scopeDialogs(
    TelegramMtprotoScopeReconcile reconcile,
  ) {
    final byPeer = <int, TelegramMtprotoDialog>{};
    for (final dialog in _preview?.dialogs ?? const <TelegramMtprotoDialog>[]) {
      byPeer[dialog.peerId] = dialog;
    }
    for (final dialog in reconcile.peers) {
      byPeer[dialog.peerId] = dialog;
    }
    return byPeer.values.toList();
  }

  Widget _peerRow(TelegramMtprotoDialog dialog) {
    return ListTile(
      dense: true,
      title: Text(dialog.title),
      subtitle: Text('${dialog.kind}${dialog.isMuted ? ' · muted' : ''}'),
      trailing: TextButton(
        key: Key('telegram_mtproto_sync_peer_${dialog.peerId}'),
        onPressed: _groupsBusy ? null : () => _syncPeer(dialog.peerId),
        child: const Text('Синхронизировать'),
      ),
    );
  }

  Widget _buildGroups(BuildContext context) {
    final groups = _groups?.groups ?? const <TelegramMtprotoGroup>[];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('Группы', style: Theme.of(context).textTheme.titleSmall),
        if (_groups?.truncated == true)
          const Text('Список групп ограничен провайдером.'),
        for (final group in groups)
          ListTile(
            title: Text(group.title),
            subtitle: Text(
              '${group.kind}${group.username == null ? '' : ' · @${group.username}'}'
              '${group.isForum ? ' · forum' : ''}'
              '${group.available ? '' : ' · недоступна'}',
            ),
            trailing: Wrap(
              children: [
                Checkbox(
                  key: Key('telegram_mtproto_group_${group.peerId}'),
                  value: group.selected,
                  onChanged: group.available
                      ? (value) => _toggleGroup(group, value == true)
                      : null,
                ),
                TextButton(
                  key: Key('telegram_mtproto_sync_group_${group.peerId}'),
                  onPressed: group.available && group.selected && !_groupsBusy
                      ? () => _syncGroup(group.peerId)
                      : null,
                  child: const Text('Синхронизировать'),
                ),
              ],
            ),
          ),
        if (_lastSync != null) _buildSyncSummary(_lastSync!),
      ],
    );
  }

  Widget _buildSyncSummary(TelegramMtprotoHistorySync result) {
    return Text(
      'Синхронизация ${result.peerId}: scanned ${result.scanned}, '
      'materialized ${result.materialized}, created ${result.created}, '
      'updated ${result.updated}, unchanged ${result.unchanged}, '
      'skipped ${result.skipped}; history_complete=${result.historyComplete}',
    );
  }
}
