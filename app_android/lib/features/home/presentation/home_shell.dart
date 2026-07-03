import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../core/auth/auth_provider.dart';
import '../../../shared/i18n/context_i18n.dart';
import '../../clients/presentation/client_create_screen.dart';
import '../../cutoff/presentation/cutoff_provider.dart';
import '../../cutoff/presentation/cutoff_tasks_screen.dart';
import '../../readings/presentation/readings_provider.dart';
import '../../readings/presentation/route_list_screen.dart';
import '../../sync/presentation/sync_provider.dart';
import '../../sync/presentation/sync_screen.dart';
import '../../account/presentation/account_screen.dart';

class HomeShell extends StatefulWidget {
  const HomeShell({super.key});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int _currentIndex = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<ReadingsProvider>().refreshPendingCount();
      context.read<SyncProvider>().refreshPendingCount();
    });
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();
    final tabs = <_HomeTab>[
      if (auth.hasScope('readings'))
        _HomeTab(
          page: const RouteListScreen(),
          destination: NavigationDestination(
            icon: const Icon(Icons.route),
            label: context.t('tab_route'),
          ),
          onSelected: () => context.read<ReadingsProvider>().refreshPendingCount(),
        ),
      if (auth.hasScope('cutoff'))
        _HomeTab(
          page: const CutoffTasksScreen(),
          destination: NavigationDestination(
            icon: const Icon(Icons.qr_code_scanner),
            label: context.t('tab_cutoff'),
          ),
          onSelected: () => context.read<CutoffProvider>().loadTasks(),
        ),
      if (auth.hasScope('clients'))
        _HomeTab(
          page: const ClientCreateScreen(),
          destination: NavigationDestination(
            icon: const Icon(Icons.person_add_alt_1),
            label: context.t('tab_clients'),
          ),
        ),
      if (auth.hasScope('readings'))
        _HomeTab(
          page: const SyncScreen(),
          destination: NavigationDestination(
            icon: const Icon(Icons.sync),
            label: context.t('tab_sync'),
          ),
          onSelected: () => context.read<SyncProvider>().refreshPendingCount(),
        ),
      _HomeTab(
        page: const AccountScreen(),
        destination: NavigationDestination(
          icon: const Icon(Icons.person),
          label: context.t('tab_account'),
        ),
      ),
    ];

    if (_currentIndex >= tabs.length) {
      _currentIndex = tabs.isEmpty ? 0 : tabs.length - 1;
    }

    return Scaffold(
      body: IndexedStack(
        index: _currentIndex,
        children: tabs.map((tab) => tab.page).toList(),
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _currentIndex,
        onDestinationSelected: (index) {
          setState(() => _currentIndex = index);
          tabs[index].onSelected?.call();
        },
        destinations: tabs.map((tab) => tab.destination).toList(),
      ),
    );
  }
}

class _HomeTab {
  _HomeTab({
    required this.page,
    required this.destination,
    this.onSelected,
  });

  final Widget page;
  final NavigationDestination destination;
  final VoidCallback? onSelected;
}
