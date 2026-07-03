import '../../../core/network/api_exception.dart';
import '../../../core/network/network_status_service.dart';
import '../data/client_local_queue.dart';
import '../data/clients_api.dart';
import '../domain/pending_client.dart';

class ClientSubmitResult {
  ClientSubmitResult({
    required this.synced,
    required this.queued,
  });

  final bool synced;
  final bool queued;
}

class ClientSyncSummary {
  ClientSyncSummary({
    required this.total,
    required this.synced,
    required this.failed,
  });

  final int total;
  final int synced;
  final int failed;
}

class ClientRegistrationService {
  ClientRegistrationService({
    required ClientsApi api,
    required ClientLocalQueue localQueue,
  })  : _api = api,
        _localQueue = localQueue;

  final ClientsApi _api;
  final ClientLocalQueue _localQueue;

  Future<ClientSubmitResult> submitClient({
    required Map<String, dynamic> payload,
    String? photoPath,
  }) async {
    final online = await NetworkStatusService.isOnline();

    if (!online) {
      await _queueClient(payload: payload, photoPath: photoPath);
      return ClientSubmitResult(synced: false, queued: true);
    }

    try {
      await _sendClient(payload: payload, photoPath: photoPath);
      return ClientSubmitResult(synced: true, queued: false);
    } on ApiException catch (e) {
      if (e.networkError) {
        await _queueClient(payload: payload, photoPath: photoPath);
        return ClientSubmitResult(synced: false, queued: true);
      }
      rethrow;
    }
  }

  Future<int> getPendingCount() => _localQueue.pendingCount();

  Future<ClientSyncSummary> syncPendingClients() async {
    final pending = await _localQueue.getPending();
    var synced = 0;
    var failed = 0;

    for (final item in pending) {
      final id = item.id;
      if (id == null) continue;

      try {
        await _sendClient(payload: item.payload, photoPath: item.photoPath);
        await _localQueue.markSynced(id);
        synced += 1;
      } catch (e) {
        await _localQueue.markError(id, e.toString());
        failed += 1;
      }
    }

    return ClientSyncSummary(
      total: pending.length,
      synced: synced,
      failed: failed,
    );
  }

  Future<void> _sendClient({
    required Map<String, dynamic> payload,
    String? photoPath,
  }) async {
    final requestPayload = Map<String, dynamic>.from(payload);

    if (photoPath != null && photoPath.isNotEmpty) {
      final photoUrl = await _api.uploadMeterPhoto(photoPath);
      if (photoUrl != null && photoUrl.isNotEmpty) {
        requestPayload['foto_medidor_url'] = photoUrl;
      }
    }

    await _api.createClient(requestPayload);
  }

  Future<void> _queueClient({
    required Map<String, dynamic> payload,
    String? photoPath,
  }) async {
    await _localQueue.insertPending(
      PendingClient(
        payload: payload,
        photoPath: photoPath,
        createdAt: DateTime.now(),
      ),
    );
  }
}
