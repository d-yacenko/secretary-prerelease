import 'dart:async';

import 'package:flutter/material.dart';

import 'date_format.dart';

class ShellClock extends StatefulWidget {
  const ShellClock({
    super.key,
    this.now,
    this.tick = const Duration(minutes: 1),
  });

  final DateTime Function()? now;
  final Duration tick;

  @override
  State<ShellClock> createState() => _ShellClockState();
}

class _ShellClockState extends State<ShellClock> {
  late DateTime _now;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _now = (widget.now ?? DateTime.now)().toLocal();
    _timer = Timer.periodic(widget.tick, (_) {
      if (!mounted) {
        return;
      }
      setState(() {
        _now = (widget.now ?? DateTime.now)().toLocal();
      });
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    const ink = Color(0xFF121417);
    const lcdFace = Color(0xFFC5CBD3);
    const lcdInset = Color(0xFF8A9199);
    return Padding(
      padding: const EdgeInsets.fromLTRB(8, 0, 8, 8),
      child: DecoratedBox(
        key: const Key('shell_clock_display'),
        decoration: BoxDecoration(
          color: lcdFace,
          borderRadius: BorderRadius.circular(4),
          border: Border.all(color: lcdInset, width: 1.5),
          boxShadow: const [
            BoxShadow(
              color: Color(0x33000000),
              offset: Offset(0, 1),
              blurRadius: 0,
            ),
          ],
        ),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 5),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              FittedBox(
                fit: BoxFit.scaleDown,
                child: Text(
                  formatRussianClockTime(_now),
                  style: const TextStyle(
                    fontFamily: 'monospace',
                    fontFeatures: [FontFeature.tabularFigures()],
                    fontSize: 27,
                    fontWeight: FontWeight.w800,
                    color: ink,
                    height: 1.0,
                    letterSpacing: 0.4,
                  ),
                ),
              ),
              const SizedBox(height: 2),
              FittedBox(
                fit: BoxFit.scaleDown,
                child: Text(
                  formatRussianNumericDate(_now),
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    fontFamily: 'monospace',
                    fontFeatures: [FontFeature.tabularFigures()],
                    fontSize: 11,
                    height: 1.1,
                    color: ink,
                  ),
                ),
              ),
              FittedBox(
                fit: BoxFit.scaleDown,
                child: Text(
                  formatRussianWeekday(_now),
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    fontFamily: 'monospace',
                    fontSize: 9,
                    height: 1.1,
                    color: ink,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
