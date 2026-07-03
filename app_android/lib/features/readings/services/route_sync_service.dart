import '../data/readings_api.dart';
import '../data/route_local_db.dart';
import '../domain/pending_reading.dart';
import '../domain/route_client.dart';
import '../../../core/network/api_exception.dart';
import '../../../core/network/network_status_service.dart';

class SyncSummary {
  SyncSummary({
    required this.total,
    required this.synced,
    required this.failed,
  });

  final int total;
  final int synced;
  final int failed;
}

class ReadingSubmitResult {
  ReadingSubmitResult({
    required this.synced,
    required this.queued,
  });

  final bool synced;
  final bool queued;
}

class RouteSyncService {
  RouteSyncService({
    required ReadingsApi api,
    required RouteLocalDb localDb,
  })  : _api = api,
        _localDb = localDb;

  final ReadingsApi _api;
  final RouteLocalDb _localDb;

  Future<int> downloadRoute({
    required int mes,
    required int ano,
    String? manzana,
  }) async {
    final clients = await _api.fetchClientsByRoute(manzana: manzana);
    final existingReadings = await _api.fetchReadingsByRoute(
      mes: mes,
      ano: ano,
      manzana: manzana,
    );

    final byClient = <String, Map<String, dynamic>>{
      for (final reading in existingReadings)
        (reading['client_id'] ?? '').toString(): reading,
    };

    final now = DateTime.now();
    final route = clients.map((client) {
      final id = (client['id'] ?? '').toString();
      final reading = byClient[id];
      final rawReadingValue = reading?['valor_leitura'];
      final parsedReadingValue = rawReadingValue is int
          ? rawReadingValue
          : int.tryParse(rawReadingValue?.toString() ?? '');

      return RouteClient(
        clientId: id,
        nombre: (client['nombre_completo'] ?? '').toString(),
        medidor: (client['numero_medidor'] ?? '').toString(),
        manzana: (client['manzana'] ?? '').toString(),
        lote: (client['lote'] ?? '').toString(),
        hasReading: reading != null,
        readingValue: parsedReadingValue,
        updatedAt: now,
      );
    }).toList();

    await _localDb.replaceRoute(route);
    return route.length;
  }

  Future<List<RouteClient>> getLocalRoute({String? manzana}) {
    return _localDb.getRoute(manzana: manzana);
  }

  Future<ReadingSubmitResult> submitReading({
    required String clientId,
    required int mes,
    required int ano,
    required int valorLeitura,
    String? referencia,
    String? observacion,
    String? photoPath,
    double? gpsLatitude,
    double? gpsLongitude,
  }) async {
    final online = await NetworkStatusService.isOnline();

    if (online) {
      try {
        String? photoUrl;
        if (photoPath != null && photoPath.isNotEmpty) {
          photoUrl = await _api.uploadPhoto(photoPath);
        }

        await _api.createReading({
          'client_id': clientId,
          'valor_leitura': valorLeitura,
          'mes_referencia': mes,
          'ano_referencia': ano,
          if (referencia != null && referencia.isNotEmpty) 'referencia': referencia,
          if (observacion != null && observacion.isNotEmpty) 'observacion': observacion,
          if (photoUrl != null) 'foto_url': photoUrl,
          if (gpsLatitude != null) 'gps_latitude': gpsLatitude,
          if (gpsLongitude != null) 'gps_longitude': gpsLongitude,
        });
        await _localDb.markClientAsRead(clientId, valorLeitura);
        return ReadingSubmitResult(synced: true, queued: false);
      } on ApiException catch (e) {
        if (!e.networkError) rethrow;
      }
    }

    final pending = PendingReading(
      clientId: clientId,
      mes: mes,
      ano: ano,
      valorLeitura: valorLeitura,
      referencia: referencia,
      observacion: observacion,
      photoPath: photoPath,
      gpsLatitude: gpsLatitude,
      gpsLongitude: gpsLongitude,
      createdAt: DateTime.now(),
    );

    await _localDb.insertPending(pending);
    await _localDb.markClientAsRead(clientId, valorLeitura);
    return ReadingSubmitResult(synced: false, queued: true);
  }

  Future<int> getPendingCount() => _localDb.pendingCount();

  Future<SyncSummary> syncPendingReadings() async {
    final pending = await _localDb.getPending();
    var synced = 0;
    var failed = 0;

    for (final item in pending) {
      final id = item.id;
      if (id == null) continue;
      try {
        String? photoUrl;
        if (item.photoPath != null && item.photoPath!.isNotEmpty) {
          photoUrl = await _api.uploadPhoto(item.photoPath!);
        }

        await _api.createReading({
          'client_id': item.clientId,
          'valor_leitura': item.valorLeitura,
          'mes_referencia': item.mes,
          'ano_referencia': item.ano,
          if (item.referencia != null && item.referencia!.isNotEmpty)
            'referencia': item.referencia,
          if (item.observacion != null && item.observacion!.isNotEmpty)
            'observacion': item.observacion,
          if (photoUrl != null) 'foto_url': photoUrl,
          if (item.gpsLatitude != null) 'gps_latitude': item.gpsLatitude,
          if (item.gpsLongitude != null) 'gps_longitude': item.gpsLongitude,
        });

        await _localDb.markSynced(id);
        synced += 1;
      } catch (e) {
        await _localDb.markError(id, e.toString());
        failed += 1;
      }
    }

    return SyncSummary(
      total: pending.length,
      synced: synced,
      failed: failed,
    );
  }
}
