import 'package:flutter/material.dart';

/// Placeholder body for shell destinations not yet implemented.
class PlaceholderScreen extends StatelessWidget {
  const PlaceholderScreen({super.key, required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Text('$title — coming in a later phase'),
    );
  }
}
