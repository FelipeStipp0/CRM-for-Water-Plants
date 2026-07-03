import 'package:flutter/foundation.dart';

import 'auth_service.dart';
import 'session_manager.dart';

class AuthProvider extends ChangeNotifier {
  AuthProvider({
    required AuthService authService,
    required SessionManager sessionManager,
  })  : _authService = authService,
        _sessionManager = sessionManager;

  final AuthService _authService;
  final SessionManager _sessionManager;

  bool _initialized = false;
  bool _loading = false;
  bool _authenticated = false;
  bool _mustChangePassword = false;
  Map<String, dynamic>? _user;
  String? _error;

  bool get initialized => _initialized;
  bool get loading => _loading;
  bool get isAuthenticated => _authenticated;
  bool get mustChangePassword => _mustChangePassword;
  Map<String, dynamic>? get user => _user;
  String? get error => _error;
  Set<String> get scopes {
    final raw = (_user?['scopes'] as List<dynamic>?) ?? const <dynamic>[];
    return raw.map((e) => e.toString()).toSet();
  }
  bool get isSuperuser => (_user?['is_superuser'] as bool?) ?? false;

  bool hasScope(String scope) {
    if (isSuperuser) return true;
    final set = scopes;
    return set.contains('*') || set.contains(scope);
  }

  Future<void> initialize() async {
    _loading = true;
    notifyListeners();

    await _sessionManager.load();
    final token = _sessionManager.token;
    if (token == null || _authService.isTokenExpired(token)) {
      await _authService.logout();
      _authenticated = false;
      _mustChangePassword = false;
      _user = null;
      _error = null;
      _initialized = true;
      _loading = false;
      notifyListeners();
      return;
    }

    try {
      final me = await _authService.me();
      _authenticated = true;
      _mustChangePassword = (me['must_change_password'] as bool?) ?? false;
      _user = me;
      _error = null;
    } catch (e) {
      await _authService.logout();
      _authenticated = false;
      _mustChangePassword = false;
      _user = null;
      _error = e.toString();
    }

    _initialized = true;
    _loading = false;
    notifyListeners();
  }

  Future<bool> login(String username, String password) async {
    _loading = true;
    _error = null;
    notifyListeners();

    try {
      final tokenPayload = await _authService.login(
        username: username,
        password: password,
      );
      _mustChangePassword =
          (tokenPayload['must_change_password'] as bool?) ?? false;
      _authenticated = true;
      _user = await _authService.me();
      _error = null;
      return true;
    } catch (e) {
      _authenticated = false;
      _mustChangePassword = false;
      _user = null;
      _error = e.toString();
      return false;
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  Future<bool> changePassword(String currentPassword, String newPassword) async {
    _loading = true;
    _error = null;
    notifyListeners();
    try {
      await _authService.changePassword(
        currentPassword: currentPassword,
        newPassword: newPassword,
      );
      _mustChangePassword = false;
      _user = await _authService.me();
      return true;
    } catch (e) {
      _error = e.toString();
      return false;
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  Future<void> logout() async {
    _loading = true;
    notifyListeners();
    await _authService.logout();
    _authenticated = false;
    _mustChangePassword = false;
    _user = null;
    _error = null;
    _loading = false;
    notifyListeners();
  }
}
