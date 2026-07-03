class PendingReading {
  PendingReading({
    this.id,
    required this.clientId,
    required this.mes,
    required this.ano,
    required this.valorLeitura,
    this.referencia,
    this.observacion,
    this.photoPath,
    this.gpsLatitude,
    this.gpsLongitude,
    required this.createdAt,
    this.status = 'pending',
    this.lastError,
  });

  final int? id;
  final String clientId;
  final int mes;
  final int ano;
  final int valorLeitura;
  final String? referencia;
  final String? observacion;
  final String? photoPath;
  final double? gpsLatitude;
  final double? gpsLongitude;
  final DateTime createdAt;
  final String status;
  final String? lastError;

  factory PendingReading.fromDb(Map<String, Object?> row) {
    final rawLat = row['gps_latitude'];
    final rawLon = row['gps_longitude'];
    return PendingReading(
      id: row['id'] as int?,
      clientId: row['client_id'] as String,
      mes: row['mes'] as int,
      ano: row['ano'] as int,
      valorLeitura: row['valor_leitura'] as int,
      referencia: row['referencia'] as String?,
      observacion: row['observacion'] as String?,
      photoPath: row['photo_path'] as String?,
      gpsLatitude: rawLat is num ? rawLat.toDouble() : null,
      gpsLongitude: rawLon is num ? rawLon.toDouble() : null,
      createdAt: DateTime.parse(row['created_at'] as String),
      status: row['status'] as String? ?? 'pending',
      lastError: row['last_error'] as String?,
    );
  }

  Map<String, Object?> toDb() {
    return {
      'id': id,
      'client_id': clientId,
      'mes': mes,
      'ano': ano,
      'valor_leitura': valorLeitura,
      'referencia': referencia,
      'observacion': observacion,
      'photo_path': photoPath,
      'gps_latitude': gpsLatitude,
      'gps_longitude': gpsLongitude,
      'created_at': createdAt.toIso8601String(),
      'status': status,
      'last_error': lastError,
    };
  }
}
