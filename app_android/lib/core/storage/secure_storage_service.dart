import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class SecureStorageService {
  static const _tokenKey = 'auth_token';
  static const _languageKey = 'app_language';
  final FlutterSecureStorage _storage = const FlutterSecureStorage();

  Future<void> writeToken(String token) async {
    await _storage.write(key: _tokenKey, value: token);
  }

  Future<String?> readToken() async {
    return _storage.read(key: _tokenKey);
  }

  Future<void> clearToken() async {
    await _storage.delete(key: _tokenKey);
  }

  Future<void> writeLanguageCode(String languageCode) async {
    await _storage.write(key: _languageKey, value: languageCode);
  }

  Future<String?> readLanguageCode() async {
    return _storage.read(key: _languageKey);
  }
}
