import 'package:flutter/material.dart';

import '../auth/auth_controller.dart';

const String kClientDisconnectConfirmationWord = 'delete';

bool clientDisconnectConfirmationMatches(String value) {
  return value == kClientDisconnectConfirmationWord;
}

/// Destructive local-session disconnect. Does not call the server.
class ClientDisconnectControl extends StatelessWidget {
  const ClientDisconnectControl({
    super.key,
    required this.authController,
  });

  final AuthController authController;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        OutlinedButton(
          key: const Key('client_disconnect_button'),
          style: OutlinedButton.styleFrom(
            foregroundColor: scheme.error,
            side: BorderSide(color: scheme.error),
          ),
          onPressed: () => _openConfirmDialog(context),
          child: const Text('Отключить этот клиент'),
        ),
        const SizedBox(height: 8),
        Text(
          key: const Key('client_disconnect_explanation'),
          'Удалит сохранённый токен на этом устройстве. Данные на сервере не удаляются.',
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
            color: scheme.onSurfaceVariant,
          ),
        ),
      ],
    );
  }

  Future<void> _openConfirmDialog(BuildContext context) async {
    final accountNavigator = Navigator.of(context);
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => ClientDisconnectConfirmDialog(
        onCancel: () => Navigator.of(dialogContext).pop(false),
        onConfirm: () => Navigator.of(dialogContext).pop(true),
      ),
    );
    if (confirmed != true) {
      return;
    }
    await authController.forgetToken();
    if (accountNavigator.canPop()) {
      accountNavigator.pop();
    }
  }
}

class ClientDisconnectConfirmDialog extends StatefulWidget {
  const ClientDisconnectConfirmDialog({
    super.key,
    required this.onCancel,
    required this.onConfirm,
  });

  final VoidCallback onCancel;
  final VoidCallback onConfirm;

  @override
  State<ClientDisconnectConfirmDialog> createState() =>
      _ClientDisconnectConfirmDialogState();
}

class _ClientDisconnectConfirmDialogState
    extends State<ClientDisconnectConfirmDialog> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  bool get _matches => clientDisconnectConfirmationMatches(_controller.text);

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return AlertDialog(
      key: const Key('client_disconnect_dialog'),
      title: const Text('Отключить этот клиент?'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text(
            'Сохранённый токен на этом устройстве будет удалён. Для входа потребуется аутентификация заново. Данные на сервере не удаляются.',
          ),
          const SizedBox(height: 16),
          const Text('Для подтверждения введите delete'),
          const SizedBox(height: 8),
          TextField(
            key: const Key('client_disconnect_confirm_field'),
            controller: _controller,
            autocorrect: false,
            enableSuggestions: false,
            onChanged: (_) => setState(() {}),
          ),
        ],
      ),
      actions: [
        TextButton(
          key: const Key('client_disconnect_cancel'),
          onPressed: widget.onCancel,
          child: const Text('Отмена'),
        ),
        OutlinedButton(
          key: const Key('client_disconnect_confirm'),
          style: OutlinedButton.styleFrom(
            foregroundColor: scheme.error,
            side: BorderSide(color: scheme.error),
          ),
          onPressed: _matches ? widget.onConfirm : null,
          child: const Text('Отключить клиент'),
        ),
      ],
    );
  }
}
