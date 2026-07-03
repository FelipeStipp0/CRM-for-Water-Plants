import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../core/auth/auth_provider.dart';
import '../../../core/i18n/language_provider.dart';
import '../../../shared/i18n/context_i18n.dart';
import '../../../shared/widgets/sync_indicator.dart';
import '../../readings/presentation/readings_provider.dart';

class AccountScreen extends StatelessWidget {
  const AccountScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer2<AuthProvider, ReadingsProvider>(
      builder: (_, auth, readings, __) {
        final user = auth.user ?? const <String, dynamic>{};
        final fullName = (user['full_name'] ?? '-') as String;
        final username = (user['username'] ?? '-') as String;
        final scopes = ((user['scopes'] ?? const <dynamic>[]) as List<dynamic>)
            .map((e) => e.toString())
            .join(', ');
        final languageProvider = context.watch<LanguageProvider>();
        final languageCode = languageProvider.locale.languageCode;

        return SafeArea(
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Text(
                context.t('account'),
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 16),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(fullName, style: Theme.of(context).textTheme.titleMedium),
                      const SizedBox(height: 4),
                      Text(username),
                      const SizedBox(height: 8),
                      Text('Scopes: ${scopes.isEmpty ? '-' : scopes}'),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 12),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        context.t('language'),
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      const SizedBox(height: 8),
                      SegmentedButton<String>(
                        segments: [
                          ButtonSegment<String>(
                            value: 'pt',
                            label: Text(context.t('lang_pt')),
                          ),
                          ButtonSegment<String>(
                            value: 'es',
                            label: Text(context.t('lang_es')),
                          ),
                        ],
                        selected: <String>{languageCode},
                        onSelectionChanged: (selection) {
                          final code = selection.first;
                          languageProvider.setLanguage(code);
                        },
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 12),
              SyncIndicator(pendingCount: readings.pendingCount),
              const SizedBox(height: 24),
              ElevatedButton.icon(
                onPressed: auth.loading ? null : auth.logout,
                icon: const Icon(Icons.logout),
                label: Text(context.t('logout')),
              ),
            ],
          ),
        );
      },
    );
  }
}
