import 'package:flutter/material.dart';

import 'auth_controller.dart';

class AuthSetupScreen extends StatefulWidget {
  const AuthSetupScreen({super.key, required this.controller});

  final AuthController controller;

  @override
  State<AuthSetupScreen> createState() => _AuthSetupScreenState();
}

class _AuthSetupScreenState extends State<AuthSetupScreen> {
  late final TextEditingController _urlController;
  late final TextEditingController _tokenController;
  bool _submitting = false;

  @override
  void initState() {
    super.initState();
    _urlController = TextEditingController(text: widget.controller.serverUrl ?? '');
    _tokenController = TextEditingController();
    widget.controller.addListener(_onControllerChanged);
  }

  void _onControllerChanged() {
    if (widget.controller.status != AuthStatus.loading) {
      setState(() {
        _submitting = false;
      });
    }
  }

  @override
  void dispose() {
    widget.controller.removeListener(_onControllerChanged);
    _urlController.dispose();
    _tokenController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() => _submitting = true);
    await widget.controller.connect(
      serverUrlInput: _urlController.text,
      token: _tokenController.text,
    );
    setState(() => _submitting = false);
  }

  @override
  Widget build(BuildContext context) {
    final controller = widget.controller;
    final isLoading = controller.status == AuthStatus.loading || _submitting;

    return Scaffold(
      appBar: AppBar(title: const Text('Подключение к Secretary')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (controller.status == AuthStatus.transientError &&
                controller.errorMessage != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Text(
                  controller.errorMessage!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
            TextField(
              controller: _urlController,
              decoration: const InputDecoration(
                labelText: 'URL сервера',
                hintText: 'https://your-secretary.example',
              ),
              keyboardType: TextInputType.url,
              enabled: !isLoading,
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _tokenController,
              decoration: InputDecoration(
                labelText: 'Токен Bearer',
                errorText: controller.errorMessage != null &&
                        controller.status == AuthStatus.needsAuth
                    ? controller.errorMessage
                    : null,
              ),
              obscureText: true,
              autocorrect: false,
              enableSuggestions: false,
              enabled: !isLoading,
            ),
            const SizedBox(height: 24),
            FilledButton(
              onPressed: isLoading ? null : _submit,
              child: isLoading
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Text('Подключиться'),
            ),
            if (controller.status == AuthStatus.transientError)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: OutlinedButton(
                  onPressed: isLoading ? null : controller.initialize,
                  child: const Text('Повторить с сохранёнными учётными данными'),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
