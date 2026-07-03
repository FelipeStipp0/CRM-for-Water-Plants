import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/foundation.dart';

import '../../clients/services/client_registration_service.dart';
import '../../readings/services/route_sync_service.dart';

class SyncProvider extends ChangeNotifier {
  SyncProvider({
    required RouteSyncService syncService,
    required ClientRegistrationService clientRegistrationService,
  })  : _syncService = syncService,
        _clientRegistrationService = clientRegistrationService {
    _init();
  }

  final RouteSyncService _syncService;
  final ClientRegistrationService _clientRegistrationService;
  final Connectivity _connectivity = Connectivity();
  StreamSubscription<List<ConnectivityResult>>? _connectivitySub;

  bool _syncing = false;
  int _pendingReadings = 0;
  int _pendingClients = 0;
  int _lastSynced = 0;
  int _lastFailed = 0;
  String? _lastError;
  DateTime? _lastRunAt;

  Future<void> _init() async {
    await refreshPendingCount();
    final initial = await _connectivity.checkConnectivity();
    if (_isOnline(initial) && pendingCount > 0) {
      await syncNow();
    }

    _connectivitySub = _connectivity.onConnectivityChanged.listen((result) {
      if (_isOnline(result) && pendingCount > 0 && !_syncing) {
        syncNow();
      }
    });
  }

  bool get syncing => _syncing;
  int get pendingReadings => _pendingReadings;
  int get pendingClients => _pendingClients;
  int get pendingCount => _pendingReadings + _pendingClients;
  int get lastSynced => _lastSynced;
  int get lastFailed => _lastFailed;
  String? get lastError => _lastError;
  DateTime? get lastRunAt => _lastRunAt;

  Future<void> refreshPendingCount() async {
    _pendingReadings = await _syncService.getPendingCount();
    _pendingClients = await _clientRegistrationService.getPendingCount();
    notifyListeners();
  }

  Future<void> syncNow() async {
    if (_syncing) return;
    _syncing = true;
    _lastError = null;
    notifyListeners();

    try {
      final readingResult = await _syncService.syncPendingReadings();
      final clientResult = await _clientRegistrationService.syncPendingClients();

      _lastSynced = readingResult.synced + clientResult.synced;
      _lastFailed = readingResult.failed + clientResult.failed;
      _lastRunAt = DateTime.now();
      await refreshPendingCount();
    } catch (e) {
      _lastError = e.toString();
    } finally {
      _syncing = false;
      notifyListeners();
    }
  }

  bool _isOnline(List<ConnectivityResult> result) {
    return !result.contains(ConnectivityResult.none);
  }

  @override
  void dispose() {
    _connectivitySub?.cancel();
    super.dispose();
  }
}
