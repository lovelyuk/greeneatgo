import 'package:flutter/material.dart';

class AdBadge extends StatelessWidget {
  const AdBadge({super.key});

  @override
  Widget build(BuildContext context) => Container(
        key: const Key('ad-badge'),
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 4),
        decoration: BoxDecoration(
          color: Colors.black.withValues(alpha: .62),
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: Colors.white.withValues(alpha: .55)),
        ),
        child: const Text('광고',
            style: TextStyle(
                color: Colors.white,
                fontSize: 10,
                fontWeight: FontWeight.w700)),
      );
}
