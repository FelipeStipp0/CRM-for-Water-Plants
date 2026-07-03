class CutoffNoticeDetail {
  CutoffNoticeDetail({
    required this.id,
    required this.clientId,
    required this.status,
    required this.clientNombre,
    required this.clientCiRuc,
    required this.clientDireccion,
    required this.clientManzana,
    required this.clientLote,
    this.dividaOriginal,
    this.dividaAtual,
    required this.hasQrEntrega,
    required this.hasQrCorte,
    required this.hasQrReativacao,
    this.fechaLimitePago,
    this.fechaCorte,
  });

  final String id;
  final String clientId;
  final String status;
  final String clientNombre;
  final String clientCiRuc;
  final String clientDireccion;
  final String clientManzana;
  final String clientLote;
  final double? dividaOriginal;
  final double? dividaAtual;
  final bool hasQrEntrega;
  final bool hasQrCorte;
  final bool hasQrReativacao;
  final DateTime? fechaLimitePago;
  final DateTime? fechaCorte;

  factory CutoffNoticeDetail.fromMap(Map<String, dynamic> map) {
    return CutoffNoticeDetail(
      id: _asString(map['id']),
      clientId: _asString(map['client_id']),
      status: _asString(map['status']),
      clientNombre: _asString(map['client_nombre']),
      clientCiRuc: _asString(map['client_ci_ruc']),
      clientDireccion: _asString(map['client_direccion']),
      clientManzana: _asString(map['client_manzana']),
      clientLote: _asString(map['client_lote']),
      dividaOriginal: _asDouble(map['divida_original']),
      dividaAtual: _asDouble(map['divida_atual']),
      hasQrEntrega: map['has_qr_entrega'] == true,
      hasQrCorte: map['has_qr_corte'] == true,
      hasQrReativacao: map['has_qr_reativacao'] == true,
      fechaLimitePago: _asDateTime(map['fecha_limite_pago']),
      fechaCorte: _asDateTime(map['fecha_corte']),
    );
  }
}

String _asString(dynamic value) => (value ?? '').toString();

double? _asDouble(dynamic value) {
  if (value == null) return null;
  if (value is num) return value.toDouble();
  return double.tryParse(value.toString());
}

DateTime? _asDateTime(dynamic value) {
  if (value == null) return null;
  return DateTime.tryParse(value.toString());
}
