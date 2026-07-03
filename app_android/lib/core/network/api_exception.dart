import 'package:dio/dio.dart';

class ApiException implements Exception {
  ApiException({
    required this.message,
    this.statusCode,
    this.networkError = false,
  });

  final String message;
  final int? statusCode;
  final bool networkError;

  factory ApiException.fromDio(
    DioException e, {
    String fallbackMessage = 'API request failed',
  }) {
    final data = e.response?.data;
    if (data is Map<String, dynamic>) {
      final detail = data['detail'];
      if (detail != null) {
        return ApiException(
          message: detail.toString(),
          statusCode: e.response?.statusCode,
          networkError: _isNetworkErrorType(e.type),
        );
      }
    }

    if (e.response?.statusCode == 401) {
      return ApiException(
        message: 'Unauthorized',
        statusCode: 401,
      );
    }

    if (e.response?.statusCode == 404) {
      return ApiException(
        message: 'Not found',
        statusCode: 404,
      );
    }

    if (_isNetworkErrorType(e.type)) {
      return ApiException(
        message: 'Connection error',
        networkError: true,
      );
    }

    return ApiException(
      message: fallbackMessage,
      statusCode: e.response?.statusCode,
    );
  }

  static bool _isNetworkErrorType(DioExceptionType type) {
    return type == DioExceptionType.connectionTimeout ||
        type == DioExceptionType.receiveTimeout ||
        type == DioExceptionType.sendTimeout ||
        type == DioExceptionType.connectionError;
  }

  @override
  String toString() => message;
}
