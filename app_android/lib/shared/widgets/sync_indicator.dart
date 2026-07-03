import 'package:flutter/material.dart';

class SyncIndicator extends StatelessWidget {
  const SyncIndicator({
    super.key,
    required this.pendingCount,
  });

  final int pendingCount;

  @override
  Widget build(BuildContext context) {
    final isSynced = pendingCount == 0;
    final color = isSynced ? Colors.green : Colors.orange;
    final icon = isSynced ? Icons.cloud_done : Icons.cloud_upload;
    final label = isSynced ? 'Synced' : '$pendingCount pending';

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 16, color: color),
          const SizedBox(width: 6),
          Text(
            label,
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: color,
            ),
          ),
        ],
      ),
    );
  }
}
