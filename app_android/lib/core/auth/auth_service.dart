import 'dart:convert';

import 'package:dio/dio.dart';

import '../network/dio_client.dart';
import 'session_manager.dart';

class AuthService {
  AuthService({required SessionManager sessionManager})
      : _sessionManager = sessionManager,
        _dio = DioClient.build(sessionManager);

  final SessionManager _sessionManager;
  final Dio _dio;

  Future<Map<String, dynamic>> login({
    required String username,
    required String password,
  }) async {
    try {
      final response = await _dio.post<Map<String, dynamic>>(
        '/auth/token',
        data: {
          'username': username,
          'password': password,
        },
        options: Options(
          contentType: Headers.formUrlEncodedContentType,
        ),
      );

      final payload = response.data ?? <String, dynamic>{};
      final token = payload['access_token'] as String?;
      if (token == null || token.isEmpty) {
        throw Exception('Missing access_token in response');
      }

      await _sessionManager.setToken(token);
      return payload;
    } on DioException catch (e) {
      throw Exception(_dioErrorMessage(e));
    }
  }

  Future<Map<String, dynamic>> me() async {
    try {
      final response = await _dio.get<Map<String, dynamic>>('/auth/me');
      return response.data ?? <String, dynamic>{};
    } on DioException catch (e) {
      throw Exception(_dioErrorMessage(e));
    }
  }

  Future<void> changePassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    try {
      await _dio.post<Map<String, dynamic>>(
        '/auth/change-password',
        data: {
          'current_password': currentPassword,
          'new_password': newPassword,
        },
      );
    } on DioException catch (e) {
      throw Exception(_dioErrorMessage(e));
    }
  }

  bool isTokenExpired(String token) {
    try {
      final parts = token.split('.');
      if (parts.length != 3) {
        return true;
      }

      final payloadJson = utf8.decode(base64Url.decode(base64Url.normalize(parts[1])));
      final payload = jsonDecode(payloadJson) as Map<String, dynamic>;
      final exp = payload['exp'];
      if (exp is! int) {
        return true;
      }

      final expDate = DateTime.fromMillisecondsSinceEpoch(exp * 1000, isUtc: true);
      return DateTime.now().toUtc().isAfter(expDate);
    } catch (_) {
      return true;
    }
  }

  Future<void> logout() => _sessionManager.clearToken();

  String _dioErrorMessage(DioException e) {
    final data = e.response?.data;
    if (data is Map<String, dynamic>) {
      final detail = data['detail'];
      if (detail != null) {
        return detail.toString();
      }
    }

    if (e.response?.statusCode == 401) {
      return 'Invalid credentials';
    }

    if (e.type == DioExceptionType.connectionTimeout ||
        e.type == DioExceptionType.receiveTimeout) {
      return 'Connection timeout';
    }

    return 'Request failed';
  }
}
