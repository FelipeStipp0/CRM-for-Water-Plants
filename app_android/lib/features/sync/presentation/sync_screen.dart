import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../shared/i18n/context_i18n.dart';
import '../../readings/presentation/readings_provider.dart';
import '../../../shared/widgets/sync_indicator.dart';
import 'sync_provider.dart';

class SyncScreen extends StatelessWidget {
  const SyncScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<SyncProvider>(
      builder: (context, sync, _) {
        return RefreshIndicator(
          onRefresh: sync.refreshPendingCount,
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    context.t('synchronization'),
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                  SyncIndicator(pendingCount: sync.pendingCount),
                ],
              ),
              const SizedBox(height: 16),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Pending total: ${sync.pendingCount}'),
                      const SizedBox(height: 6),
                      Text('Pending clients: ${sync.pendingClients}'),
                      const SizedBox(height: 6),
                      Text('Last synced: ${sync.lastSynced}'),
                      const SizedBox(height: 6),
                      Text('Last failed: ${sync.lastFailed}'),
                      if (sync.lastRunAt != null) ...[
                        const SizedBox(height: 6),
                        Text('Last run: ${sync.lastRunAt}'),
                      ],
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 12),
              ElevatedButton.icon(
                onPressed: sync.syncing
                    ? null
                    : () async {
                        await sync.syncNow();
                        if (!context.mounted) return;
                        await context.read<ReadingsProvider>().refreshPendingCount();
                      },
                icon: sync.syncing
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.sync),
                label: Text(
                  sync.syncing
                      ? context.t('synchronizing')
                      : context.t('sync_now'),
                ),
              ),
              if (sync.lastError != null) ...[
                const SizedBox(height: 12),
                Text(
                  sync.lastError!,
                  style: const TextStyle(color: Colors.red),
                ),
              ],
            ],
          ),
        );
      },
    );
  }
}
