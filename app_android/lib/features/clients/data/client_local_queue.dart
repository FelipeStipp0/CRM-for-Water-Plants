import '../../../core/storage/app_database.dart';
import '../domain/pending_client.dart';

class ClientLocalQueue {
  Future<void> insertPending(PendingClient client) async {
    final db = AppDatabase.instance.db;
    await db.insert('pending_clients', client.toDb());
  }

  Future<List<PendingClient>> getPending() async {
    final db = AppDatabase.instance.db;
    final rows = await db.query(
      'pending_clients',
      where: 'status = ?',
      whereArgs: const ['pending'],
      orderBy: 'created_at ASC',
    );
    return rows.map(PendingClient.fromDb).toList();
  }

  Future<int> pendingCount() async {
    final db = AppDatabase.instance.db;
    final result = await db.rawQuery(
      'SELECT COUNT(*) as total FROM pending_clients WHERE status = ?',
      const ['pending'],
    );
    final value = result.first['total'];
    if (value is int) return value;
    if (value is num) return value.toInt();
    return 0;
  }

  Future<void> markSynced(int id) async {
    final db = AppDatabase.instance.db;
    await db.update(
      'pending_clients',
      {
        'status': 'synced',
        'last_error': null,
      },
      where: 'id = ?',
      whereArgs: [id],
    );
  }

  Future<void> markError(int id, String error) async {
    final db = AppDatabase.instance.db;
    await db.update(
      'pending_clients',
      {
        'last_error': error,
      },
      where: 'id = ?',
      whereArgs: [id],
    );
  }
}
