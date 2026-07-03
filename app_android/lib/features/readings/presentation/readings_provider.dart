import 'package:flutter/foundation.dart';

import '../domain/route_client.dart';
import '../services/photo_capture_service.dart';
import '../services/route_sync_service.dart';

class ReadingsProvider extends ChangeNotifier {
  ReadingsProvider({required RouteSyncService syncService})
      : _syncService = syncService {
    _loadInitial();
  }

  final RouteSyncService _syncService;

  bool _loading = false;
  bool _saving = false;
  String? _error;
  String? _lastSaveMode;
  List<RouteClient> _routeClients = const [];
  int _mes = DateTime.now().month;
  int _ano = DateTime.now().year;
  String _manzana = '';
  int _pendingCount = 0;

  bool get loading => _loading;
  bool get saving => _saving;
  String? get error => _error;
  List<RouteClient> get routeClients => _routeClients;
  int get mes => _mes;
  int get ano => _ano;
  String get manzana => _manzana;
  int get pendingCount => _pendingCount;
  String? get lastSaveMode => _lastSaveMode;

  Future<void> _loadInitial() async {
    await loadLocalRoute();
    await refreshPendingCount();
  }

  void setPeriod(int mes, int ano) {
    _mes = mes;
    _ano = ano;
    notifyListeners();
  }

  void setManzana(String manzana) {
    _manzana = manzana.trim();
    notifyListeners();
  }

  Future<void> loadLocalRoute() async {
    _loading = true;
    _error = null;
    notifyListeners();

    try {
      _routeClients = await _syncService.getLocalRoute(manzana: _manzana);
    } catch (e) {
      _error = e.toString();
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  Future<int> downloadRoute() async {
    _loading = true;
    _error = null;
    notifyListeners();

    try {
      final total = await _syncService.downloadRoute(
        mes: _mes,
        ano: _ano,
        manzana: _manzana.isEmpty ? null : _manzana,
      );
      _routeClients = await _syncService.getLocalRoute(manzana: _manzana);
      return total;
    } catch (e) {
      _error = e.toString();
      return 0;
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  Future<bool> saveReadingOffline({
    required RouteClient client,
    required int valorLeitura,
    String? observacion,
    CapturedPhoto? photo,
  }) async {
    _saving = true;
    _error = null;
    _lastSaveMode = null;
    notifyListeners();

    try {
      final result = await _syncService.submitReading(
        clientId: client.clientId,
        mes: _mes,
        ano: _ano,
        valorLeitura: valorLeitura,
        referencia: '${_mes.toString().padLeft(2, '0')}/$_ano',
        observacion: observacion,
        photoPath: photo?.path,
        gpsLatitude: photo?.latitude,
        gpsLongitude: photo?.longitude,
      );
      _lastSaveMode = result.synced ? 'synced' : 'queued';
      _routeClients = await _syncService.getLocalRoute(manzana: _manzana);
      await refreshPendingCount();
      return true;
    } catch (e) {
      _error = e.toString();
      return false;
    } finally {
      _saving = false;
      notifyListeners();
    }
  }

  Future<void> refreshPendingCount() async {
    _pendingCount = await _syncService.getPendingCount();
    notifyListeners();
  }
}
