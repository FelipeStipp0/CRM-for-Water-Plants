import 'dart:convert';

class PendingClient {
  PendingClient({
    this.id,
    required this.payload,
    this.photoPath,
    required this.createdAt,
    this.status = 'pending',
    this.lastError,
  });

  final int? id;
  final Map<String, dynamic> payload;
  final String? photoPath;
  final DateTime createdAt;
  final String status;
  final String? lastError;

  factory PendingClient.fromDb(Map<String, Object?> row) {
    final rawPayload = (row['payload_json'] ?? '{}').toString();
    final decoded = jsonDecode(rawPayload);
    final payload = decoded is Map<String, dynamic>
        ? decoded
        : <String, dynamic>{};

    return PendingClient(
      id: row['id'] as int?,
      payload: payload,
      photoPath: row['photo_path'] as String?,
      createdAt: DateTime.parse((row['created_at'] ?? '').toString()),
      status: (row['status'] ?? 'pending').toString(),
      lastError: row['last_error'] as String?,
    );
  }

  Map<String, Object?> toDb() {
    return {
      'id': id,
      'payload_json': jsonEncode(payload),
      'photo_path': photoPath,
      'created_at': createdAt.toIso8601String(),
      'status': status,
      'last_error': lastError,
    };
  }
}
