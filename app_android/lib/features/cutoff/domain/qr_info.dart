class QrInfo {
  QrInfo({
    required this.noticeId,
    required this.actionType,
    required this.alreadyDone,
    required this.clientNombre,
    required this.clientCiRuc,
    required this.clientDireccion,
    required this.clientManzana,
    required this.clientLote,
    required this.status,
    this.dividaOriginal,
  });

  final String noticeId;
  final String actionType;
  final bool alreadyDone;
  final String clientNombre;
  final String clientCiRuc;
  final String clientDireccion;
  final String clientManzana;
  final String clientLote;
  final String status;
  final double? dividaOriginal;

  factory QrInfo.fromMap(Map<String, dynamic> map) {
    return QrInfo(
      noticeId: (map['notice_id'] ?? '').toString(),
      actionType: (map['action_type'] ?? '').toString(),
      alreadyDone: map['already_done'] == true,
      clientNombre: (map['client_nombre'] ?? '').toString(),
      clientCiRuc: (map['client_ci_ruc'] ?? '').toString(),
      clientDireccion: (map['client_direccion'] ?? '').toString(),
      clientManzana: (map['client_manzana'] ?? '').toString(),
      clientLote: (map['client_lote'] ?? '').toString(),
      status: (map['status'] ?? '').toString(),
      dividaOriginal: _toDouble(map['divida_original']),
    );
  }
}

double? _toDouble(dynamic value) {
  if (value == null) return null;
  if (value is num) return value.toDouble();
  return double.tryParse(value.toString());
}
