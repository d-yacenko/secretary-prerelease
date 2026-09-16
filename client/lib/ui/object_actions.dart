import 'package:flutter/material.dart';

import 'app_spacing.dart';

class ObjectActionButton extends StatelessWidget {
  const ObjectActionButton({
    super.key,
    required this.icon,
    required this.label,
    required this.onPressed,
  });

  final IconData icon;
  final String label;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    final compact = isWideLayout(context);
    if (compact) {
      return TextButton.icon(
        onPressed: onPressed,
        icon: Icon(icon, size: 18),
        label: Text(label),
        style: TextButton.styleFrom(
          visualDensity: VisualDensity.compact,
          tapTargetSize: MaterialTapTargetSize.shrinkWrap,
        ),
      );
    }
    return IconButton(
      tooltip: label,
      onPressed: onPressed,
      icon: Icon(icon),
    );
  }
}

class AskSecretaryAction extends StatelessWidget {
  const AskSecretaryAction({super.key, required this.onPressed});

  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return ObjectActionButton(
      icon: Icons.smart_toy_outlined,
      label: 'Спросить секретаря',
      onPressed: onPressed,
    );
  }
}

class OpenInGraphAction extends StatelessWidget {
  const OpenInGraphAction({super.key, required this.onPressed});

  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return ObjectActionButton(
      icon: Icons.hub_outlined,
      label: 'Открыть в графе',
      onPressed: onPressed,
    );
  }
}

class OpenSourceAction extends StatelessWidget {
  const OpenSourceAction({
    super.key,
    required this.onPressed,
    this.label = 'Открыть в источнике',
  });

  final VoidCallback? onPressed;
  final String label;

  @override
  Widget build(BuildContext context) {
    return ObjectActionButton(
      icon: Icons.open_in_new,
      label: label,
      onPressed: onPressed,
    );
  }
}
