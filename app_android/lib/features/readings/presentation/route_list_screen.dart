import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../shared/i18n/context_i18n.dart';
import '../../../shared/widgets/sync_indicator.dart';
import '../domain/route_client.dart';
import 'reading_form_screen.dart';
import 'readings_provider.dart';

class RouteListScreen extends StatefulWidget {
  const RouteListScreen({super.key});

  @override
  State<RouteListScreen> createState() => _RouteListScreenState();
}

class _RouteListScreenState extends State<RouteListScreen> {
  late final TextEditingController _mesController;
  late final TextEditingController _anoController;
  late final TextEditingController _manzanaController;

  @override
  void initState() {
    super.initState();
    final provider = context.read<ReadingsProvider>();
    _mesController = TextEditingController(text: provider.mes.toString());
    _anoController = TextEditingController(text: provider.ano.toString());
    _manzanaController = TextEditingController(text: provider.manzana);
  }

  @override
  void dispose() {
    _mesController.dispose();
    _anoController.dispose();
    _manzanaController.dispose();
    super.dispose();
  }

  Future<void> _downloadRoute() async {
    final provider = context.read<ReadingsProvider>();
    final mes = int.tryParse(_mesController.text.trim()) ?? provider.mes;
    final ano = int.tryParse(_anoController.text.trim()) ?? provider.ano;
    provider.setPeriod(mes, ano);
    provider.setManzana(_manzanaController.text);

    final total = await provider.downloadRoute();
    if (!mounted) return;
    final messenger = ScaffoldMessenger.of(context);
    if (provider.error != null) {
      messenger.showSnackBar(
        SnackBar(content: Text(provider.error!)),
      );
      return;
    }
    messenger.showSnackBar(
      SnackBar(content: Text('Route downloaded: $total clients')),
    );
  }

  Future<void> _openReadingForm(RouteClient client) async {
    final provider = context.read<ReadingsProvider>();
    final saved = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => ReadingFormScreen(client: client),
      ),
    );
    if (saved == true && mounted) {
      await provider.loadLocalRoute();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<ReadingsProvider>(
      builder: (_, provider, __) {
        final total = provider.routeClients.length;
        final done = provider.routeClients.where((c) => c.hasReading).length;

        return SafeArea(
          child: RefreshIndicator(
            onRefresh: provider.loadLocalRoute,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      context.t('daily_route'),
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    SyncIndicator(pendingCount: provider.pendingCount),
                  ],
                ),
                const SizedBox(height: 12),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(
                      children: [
                        Row(
                          children: [
                            Expanded(
                              child: TextField(
                                controller: _mesController,
                                keyboardType: TextInputType.number,
                                decoration: InputDecoration(
                                  labelText: context.t('month'),
                                ),
                              ),
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: TextField(
                                controller: _anoController,
                                keyboardType: TextInputType.number,
                                decoration: InputDecoration(
                                  labelText: context.t('year'),
                                ),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 8),
                        TextField(
                          controller: _manzanaController,
                          decoration: InputDecoration(
                            labelText: context.t('manzana_optional'),
                          ),
                        ),
                        const SizedBox(height: 10),
                        ElevatedButton.icon(
                          onPressed: provider.loading
                              ? null
                              : _downloadRoute,
                          icon: const Icon(Icons.download),
                          label: Text(provider.loading
                              ? context.t('downloading')
                              : context.t('download_route')),
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                Text('${context.t('progress')}: $done/$total'),
                const SizedBox(height: 8),
                if (provider.error != null)
                  Text(
                    provider.error!,
                    style: const TextStyle(color: Colors.red),
                  ),
                const SizedBox(height: 8),
                ...provider.routeClients.map((client) {
                  final statusColor = client.hasReading ? Colors.green : Colors.orange;
                  final statusIcon =
                      client.hasReading ? Icons.check_circle : Icons.pause_circle;
                  return Card(
                    child: ListTile(
                      leading: Icon(statusIcon, color: statusColor),
                      title: Text('[${client.manzana}-${client.lote}] ${client.nombre}'),
                      subtitle: Text(
                        '${client.medidor} ${client.readingValue == null ? '' : '| Reading: ${client.readingValue}'}',
                      ),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => _openReadingForm(client),
                    ),
                  );
                }),
              ],
            ),
          ),
        );
      },
    );
  }
}
