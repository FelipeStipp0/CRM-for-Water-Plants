import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../shared/i18n/context_i18n.dart';
import '../domain/cutoff_notice_detail.dart';
import 'cutoff_provider.dart';
import 'qr_scanner_screen.dart';

class CutoffTasksScreen extends StatefulWidget {
  const CutoffTasksScreen({super.key});

  @override
  State<CutoffTasksScreen> createState() => _CutoffTasksScreenState();
}

class _CutoffTasksScreenState extends State<CutoffTasksScreen> {
  final _searchController = TextEditingController();

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _openScanner() async {
    final confirmed = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => const QrScannerScreen()),
    );
    if (!mounted) return;
    if (confirmed == true) {
      await context.read<CutoffProvider>().loadTasks();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<CutoffProvider>(
      builder: (_, provider, __) {
        return SafeArea(
          child: RefreshIndicator(
            onRefresh: provider.loadTasks,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      context.t('today_cutoff_tasks'),
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    IconButton(
                      onPressed: provider.loading ? null : provider.loadTasks,
                      icon: const Icon(Icons.refresh),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                TextField(
                  controller: _searchController,
                  decoration: InputDecoration(
                    labelText: context.t('search_cutoff'),
                    prefixIcon: Icon(Icons.search),
                  ),
                  onChanged: provider.setSearch,
                ),
                const SizedBox(height: 10),
                ElevatedButton.icon(
                  onPressed: _openScanner,
                  icon: const Icon(Icons.qr_code_scanner),
                  label: Text(context.t('scan_qr_action')),
                ),
                const SizedBox(height: 12),
                if (provider.loading)
                  const Center(
                    child: Padding(
                      padding: EdgeInsets.all(20),
                      child: CircularProgressIndicator(),
                    ),
                  ),
                if (!provider.loading && provider.error != null)
                  Text(
                    provider.error!,
                    style: const TextStyle(color: Colors.red),
                  ),
                if (!provider.loading && provider.tasks.isEmpty)
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Text(context.t('no_cutoff_tasks')),
                    ),
                  ),
                ...provider.tasks.map(_buildTaskCard),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _buildTaskCard(CutoffNoticeDetail task) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    task.clientNombre,
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                ),
                _statusChip(task.status),
              ],
            ),
            const SizedBox(height: 4),
            Text('CI/RUC: ${task.clientCiRuc}'),
            const SizedBox(height: 2),
            Text('Route: ${task.clientManzana}-${task.clientLote}'),
            const SizedBox(height: 2),
            Text(task.clientDireccion),
            const SizedBox(height: 6),
            Text(
              'Debt: ${_money(task.dividaAtual ?? task.dividaOriginal)}',
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
          ],
        ),
      ),
    );
  }

  Widget _statusChip(String status) {
    final color = switch (status) {
      'PRONTO_PARA_CORTE' => Colors.red,
      'EM_CONTAGEM' => Colors.orange,
      'EM_AVISO' => Colors.blue,
      'EM_LISTA' => Colors.teal,
      'CORTADO' => Colors.grey,
      _ => Colors.black54,
    };

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        CutoffProvider.statusLabel(status),
        style: TextStyle(
          color: color,
          fontWeight: FontWeight.w600,
          fontSize: 12,
        ),
      ),
    );
  }

  String _money(double? value) {
    if (value == null) return '-';
    return value.toStringAsFixed(2);
  }
}
