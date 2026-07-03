class RouteClient {
  RouteClient({
    required this.clientId,
    required this.nombre,
    required this.medidor,
    required this.manzana,
    required this.lote,
    required this.hasReading,
    this.readingValue,
    required this.updatedAt,
  });

  final String clientId;
  final String nombre;
  final String medidor;
  final String manzana;
  final String lote;
  final bool hasReading;
  final int? readingValue;
  final DateTime updatedAt;

  factory RouteClient.fromDb(Map<String, Object?> row) {
    final rawValue = row['reading_value'];
    return RouteClient(
      clientId: row['client_id'] as String,
      nombre: row['nombre'] as String,
      medidor: row['medidor'] as String,
      manzana: row['manzana'] as String,
      lote: row['lote'] as String,
      hasReading: (row['has_reading'] as int? ?? 0) == 1,
      readingValue: rawValue is num ? rawValue.toInt() : null,
      updatedAt: DateTime.parse(row['updated_at'] as String),
    );
  }

  Map<String, Object?> toDb() {
    return {
      'client_id': clientId,
      'nombre': nombre,
      'medidor': medidor,
      'manzana': manzana,
      'lote': lote,
      'has_reading': hasReading ? 1 : 0,
      'reading_value': readingValue,
      'updated_at': updatedAt.toIso8601String(),
    };
  }
}
