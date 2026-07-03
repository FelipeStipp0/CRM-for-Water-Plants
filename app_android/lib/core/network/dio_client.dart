import 'package:dio/dio.dart';

import '../auth/session_manager.dart';
import '../config/api_config.dart';
import 'auth_interceptor.dart';

class DioClient {
  static Dio build(SessionManager sessionManager) {
    final dio = Dio(
      BaseOptions(
        baseUrl: ApiConfig.baseUrl,
        connectTimeout: const Duration(milliseconds: ApiConfig.connectTimeoutMs),
        receiveTimeout: const Duration(milliseconds: ApiConfig.receiveTimeoutMs),
      ),
    );

    dio.interceptors.add(AuthInterceptor(sessionManager));
    return dio;
  }
}
