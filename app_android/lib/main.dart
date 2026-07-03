import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'app/app.dart';
import 'core/auth/auth_provider.dart';
import 'core/auth/auth_service.dart';
import 'core/auth/session_manager.dart';
import 'core/i18n/language_provider.dart';
import 'core/storage/app_database.dart';
import 'core/storage/secure_storage_service.dart';
import 'features/clients/data/clients_api.dart';
import 'features/clients/data/client_local_queue.dart';
import 'features/clients/services/client_registration_service.dart';
import 'features/cutoff/data/cutoff_api.dart';
import 'features/cutoff/presentation/cutoff_provider.dart';
import 'features/cutoff/services/cutoff_workflow_service.dart';
import 'features/readings/data/readings_api.dart';
import 'features/readings/data/route_local_db.dart';
import 'features/readings/presentation/readings_provider.dart';
import 'features/readings/services/route_sync_service.dart';
import 'features/sync/presentation/sync_provider.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await AppDatabase.instance.init();

  final secureStorage = SecureStorageService();
  final sessionManager = SessionManager(secureStorage);
  final authService = AuthService(sessionManager: sessionManager);
  final readingsApi = ReadingsApi(sessionManager: sessionManager);
  final cutoffApi = CutoffApi(sessionManager: sessionManager);
  final cutoffWorkflowService = CutoffWorkflowService(api: cutoffApi);
  final clientsApi = ClientsApi(sessionManager: sessionManager);
  final clientLocalQueue = ClientLocalQueue();
  final clientRegistrationService = ClientRegistrationService(
    api: clientsApi,
    localQueue: clientLocalQueue,
  );
  final routeLocalDb = RouteLocalDb();
  final routeSyncService = RouteSyncService(api: readingsApi, localDb: routeLocalDb);

  final authProvider = AuthProvider(
    authService: authService,
    sessionManager: sessionManager,
  );
  final languageProvider = LanguageProvider(secureStorage);
  await authProvider.initialize();
  await languageProvider.initialize();

  runApp(
    MultiProvider(
      providers: [
        Provider<ClientsApi>.value(value: clientsApi),
        Provider<ClientRegistrationService>.value(value: clientRegistrationService),
        Provider<CutoffWorkflowService>.value(value: cutoffWorkflowService),
        ChangeNotifierProvider<AuthProvider>.value(value: authProvider),
        ChangeNotifierProvider<LanguageProvider>.value(value: languageProvider),
        ChangeNotifierProvider<CutoffProvider>(
          create: (_) => CutoffProvider(service: cutoffWorkflowService),
        ),
        ChangeNotifierProvider<ReadingsProvider>(
          create: (_) => ReadingsProvider(syncService: routeSyncService),
        ),
        ChangeNotifierProvider<SyncProvider>(
          create: (_) => SyncProvider(
            syncService: routeSyncService,
            clientRegistrationService: clientRegistrationService,
          ),
        ),
      ],
      child: const JuntaFieldApp(),
    ),
  );
}
