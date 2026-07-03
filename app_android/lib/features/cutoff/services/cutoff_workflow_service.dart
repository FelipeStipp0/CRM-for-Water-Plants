import '../data/cutoff_api.dart';
import '../domain/cutoff_action_response.dart';
import '../domain/cutoff_notice_detail.dart';
import '../domain/qr_info.dart';

class CutoffWorkflowService {
  CutoffWorkflowService({required CutoffApi api}) : _api = api;

  final CutoffApi _api;

  Future<List<CutoffNoticeDetail>> fetchTasks({
    String? status,
    int limit = 50,
  }) async {
    List<Map<String, dynamic>> details;
    if (status == null || status == 'PRONTO_PARA_CORTE') {
      // Atualiza no backend os avisos cujo prazo de pagamento ja expirou.
      await _api.processExpiredCountdowns();
      details = await _api.fetchReadyNotices(limit: limit);
    } else {
      final notices = await _api.fetchNotices(
        status: status,
        includeExited: false,
        limit: limit,
      );
      if (notices.isEmpty) return const [];

      final noticeIds = notices
          .map((item) => (item['id'] ?? '').toString())
          .where((id) => id.isNotEmpty)
          .toList();
      details = await Future.wait(
        noticeIds.map(_api.fetchNoticeDetail),
        eagerError: false,
      );
    }

    final tasks = details.map(CutoffNoticeDetail.fromMap).toList();
    tasks.sort((a, b) {
      final byManzana = a.clientManzana.compareTo(b.clientManzana);
      if (byManzana != 0) return byManzana;
      return a.clientLote.compareTo(b.clientLote);
    });
    return tasks;
  }

  Future<QrInfo> getQrInfo(String rawToken) async {
    final token = normalizeQrToken(rawToken);
    final data = await _api.getQrInfo(token);
    return QrInfo.fromMap(data);
  }

  Future<CutoffActionResponse> confirmByQrAction({
    required String rawToken,
    required String nomeResponsavel,
    String? observacion,
    String? photoPath,
    double? gpsLatitude,
    double? gpsLongitude,
    required String actionType,
  }) async {
    final token = normalizeQrToken(rawToken);
    if (token.isEmpty) {
      throw Exception('Invalid QR token');
    }

    String? photoUrl;
    if (photoPath != null && photoPath.isNotEmpty) {
      photoUrl = await _api.uploadPhoto(
        photoPath,
        tipo: _uploadTypeForAction(actionType),
      );
    }

    final payload = <String, dynamic>{
      'nome_responsavel': nomeResponsavel,
      if (observacion != null && observacion.trim().isNotEmpty)
        'observacion': observacion.trim(),
      if (photoUrl != null && photoUrl.isNotEmpty) 'foto_url': photoUrl,
      if (gpsLatitude != null) 'gps_latitude': gpsLatitude,
      if (gpsLongitude != null) 'gps_longitude': gpsLongitude,
    };

    final response = await _api.confirmByQr(token, payload);
    return CutoffActionResponse.fromMap(response);
  }

  static String normalizeQrToken(String raw) {
    final input = raw.trim();
    if (input.isEmpty) return '';
    if (!input.contains('/')) return input;

    final uri = Uri.tryParse(input);
    if (uri == null) return input;

    final tokenFromQuery = uri.queryParameters['token'];
    if (tokenFromQuery != null && tokenFromQuery.isNotEmpty) {
      return tokenFromQuery;
    }

    final segments = uri.pathSegments.where((segment) => segment.isNotEmpty).toList();
    final qrIndex = segments.indexOf('qr');
    if (qrIndex >= 0 && qrIndex + 1 < segments.length) {
      return segments[qrIndex + 1];
    }

    if (segments.isNotEmpty) {
      return segments.last;
    }

    return input;
  }

  String _uploadTypeForAction(String actionType) {
    switch (actionType.toUpperCase()) {
      case 'EXECUCAO_CORTE':
        return 'corte';
      case 'CONFIRMACAO_REATIVACAO':
        return 'reativacao';
      case 'ENTREGA_AVISO':
      default:
        return 'instalacao';
    }
  }
}
