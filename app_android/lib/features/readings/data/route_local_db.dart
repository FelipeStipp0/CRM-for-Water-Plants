import '../../../core/storage/app_database.dart';
import '../domain/pending_reading.dart';
import '../domain/route_client.dart';

class RouteLocalDb {
  Future<void> replaceRoute(List<RouteClient> clients) async {
    final db = AppDatabase.instance.db;
    await db.transaction((txn) async {
      await txn.delete('route_clients');
      for (final client in clients) {
        await txn.insert('route_clients', client.toDb());
      }
    });
  }

  Future<List<RouteClient>> getRoute({String? manzana}) async {
    final db = AppDatabase.instance.db;
    final rows = await db.query(
      'route_clients',
      where: manzana == null || manzana.isEmpty ? null : 'manzana = ?',
      whereArgs: manzana == null || manzana.isEmpty ? null : [manzana],
      orderBy: 'manzana ASC, lote ASC',
    );
    return rows.map(RouteClient.fromDb).toList();
  }

  Future<void> markClientAsRead(String clientId, int readingValue) async {
    final db = AppDatabase.instance.db;
    await db.update(
      'route_clients',
      {
        'has_reading': 1,
        'reading_value': readingValue,
        'updated_at': DateTime.now().toIso8601String(),
      },
      where: 'client_id = ?',
      whereArgs: [clientId],
    );
  }

  Future<void> insertPending(PendingReading reading) async {
    final db = AppDatabase.instance.db;
    await db.insert('pending_readings', reading.toDb());
  }

  Future<List<PendingReading>> getPending() async {
    final db = AppDatabase.instance.db;
    final rows = await db.query(
      'pending_readings',
      where: 'status = ?',
      whereArgs: ['pending'],
      orderBy: 'created_at ASC',
    );
    return rows.map(PendingReading.fromDb).toList();
  }

  Future<int> pendingCount() async {
    final db = AppDatabase.instance.db;
    final result = await db.rawQuery(
      'SELECT COUNT(*) as total FROM pending_readings WHERE status = ?',
      ['pending'],
    );
    final value = result.first['total'];
    if (value is int) return value;
    if (value is num) return value.toInt();
    return 0;
  }

  Future<void> markSynced(int id) async {
    final db = AppDatabase.instance.db;
    await db.update(
      'pending_readings',
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
      'pending_readings',
      {
        'last_error': error,
      },
      where: 'id = ?',
      whereArgs: [id],
    );
  }
}
