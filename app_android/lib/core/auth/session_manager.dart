import '../storage/secure_storage_service.dart';

class SessionManager {
  SessionManager(this._secureStorage);

  final SecureStorageService _secureStorage;
  String? _token;

  String? get token => _token;

  Future<void> load() async {
    _token = await _secureStorage.readToken();
  }

  Future<void> setToken(String token) async {
    _token = token;
    await _secureStorage.writeToken(token);
  }

  Future<void> clearToken() async {
    _token = null;
    await _secureStorage.clearToken();
  }
}
