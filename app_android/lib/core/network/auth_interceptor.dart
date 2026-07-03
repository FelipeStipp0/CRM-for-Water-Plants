import 'package:dio/dio.dart';

import '../auth/session_manager.dart';

class AuthInterceptor extends Interceptor {
  AuthInterceptor(this._sessionManager);

  final SessionManager _sessionManager;

  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) {
    final token = _sessionManager.token;
    if (token != null && token.isNotEmpty) {
      options.headers['Authorization'] = 'Bearer $token';
    }
    handler.next(options);
  }

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) async {
    if (err.response?.statusCode == 401) {
      await _sessionManager.clearToken();
    }
    handler.next(err);
  }
}
