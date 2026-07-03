import 'package:flutter/foundation.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:sqflite_common_ffi_web/sqflite_ffi_web.dart';

class AppDatabase {
  AppDatabase._();
  static final AppDatabase instance = AppDatabase._();

  static const _dbName = 'junta_field.db';
  static const _dbVersion = 2;

  Database? _db;
  bool _factoryConfigured = false;

  void _configureDatabaseFactoryIfNeeded() {
    if (_factoryConfigured) return;

    if (kIsWeb) {
      databaseFactory = databaseFactoryFfiWeb;
      _factoryConfigured = true;
      return;
    }

    final platform = defaultTargetPlatform;
    final isDesktop = platform == TargetPlatform.windows ||
        platform == TargetPlatform.linux ||
        platform == TargetPlatform.macOS;

    if (isDesktop) {
      sqfliteFfiInit();
      databaseFactory = databaseFactoryFfi;
    }

    _factoryConfigured = true;
  }

  Future<void> init() async {
    if (_db != null) return;
    _configureDatabaseFactoryIfNeeded();

    final dbPath = await getDatabasesPath();
    final fullPath = p.join(dbPath, _dbName);
    _db = await openDatabase(
      fullPath,
      version: _dbVersion,
      onCreate: (db, version) async {
        await _createSchema(db);
      },
      onUpgrade: (db, oldVersion, newVersion) async {
        if (oldVersion < 2) {
          await db.execute('''
            CREATE TABLE IF NOT EXISTS pending_clients (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              payload_json TEXT NOT NULL,
              photo_path TEXT,
              created_at TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending',
              last_error TEXT
            )
          ''');
        }
      },
    );
  }

  Future<void> _createSchema(Database db) async {
    await db.execute('''
      CREATE TABLE route_clients (
        client_id TEXT PRIMARY KEY,
        nombre TEXT NOT NULL,
        medidor TEXT NOT NULL,
        manzana TEXT NOT NULL,
        lote TEXT NOT NULL,
        has_reading INTEGER NOT NULL DEFAULT 0,
        reading_value INTEGER,
        updated_at TEXT NOT NULL
      )
    ''');

    await db.execute('''
      CREATE TABLE pending_readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id TEXT NOT NULL,
        mes INTEGER NOT NULL,
        ano INTEGER NOT NULL,
        valor_leitura INTEGER NOT NULL,
        referencia TEXT,
        observacion TEXT,
        photo_path TEXT,
        gps_latitude REAL,
        gps_longitude REAL,
        created_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        last_error TEXT
      )
    ''');

    await db.execute('''
      CREATE TABLE pending_clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payload_json TEXT NOT NULL,
        photo_path TEXT,
        created_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        last_error TEXT
      )
    ''');
  }

  Database get db {
    final instance = _db;
    if (instance == null) {
      throw StateError('Database not initialized. Call init() first.');
    }
    return instance;
  }
}
