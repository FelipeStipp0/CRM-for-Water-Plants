import 'package:dio/dio.dart';

import '../../../core/auth/session_manager.dart';
import '../../../core/network/api_exception.dart';
import '../../../core/network/dio_client.dart';

class CutoffApi {
  CutoffApi({required SessionManager sessionManager})
      : _dio = DioClient.build(sessionManager);

  final Dio _dio;

  Future<List<Map<String, dynamic>>> fetchNotices({
    String? status,
    bool includeExited = false,
    int skip = 0,
    int limit = 50,
  }) async {
    try {
      final response = await _dio.get<List<dynamic>>(
        '/cutoff/notices',
        queryParameters: {
          if (status != null && status.isNotEmpty) 'status': status,
          'include_exited': includeExited,
          'skip': skip,
          'limit': limit,
        },
      );
      return _toMapList(response.data);
    } on DioException catch (e) {
      throw ApiException.fromDio(e);
    }
  }

  Future<List<Map<String, dynamic>>> fetchReadyNotices({
    int limit = 50,
  }) async {
    try {
      final response = await _dio.get<List<dynamic>>(
        '/cutoff/notices/ready',
        queryParameters: {'limit': limit},
      );
      return _toMapList(response.data);
    } on DioException catch (e) {
      throw ApiException.fromDio(e);
    }
  }

  Future<void> processExpiredCountdowns() async {
    try {
      await _dio.post<Map<String, dynamic>>('/cutoff/notices/process-expired');
    } on DioException catch (e) {
      throw ApiException.fromDio(e);
    }
  }

  Future<Map<String, dynamic>> fetchNoticeDetail(String noticeId) async {
    try {
      final response = await _dio.get<Map<String, dynamic>>(
        '/cutoff/notices/$noticeId',
      );
      return response.data ?? <String, dynamic>{};
    } on DioException catch (e) {
      throw ApiException.fromDio(e);
    }
  }

  Future<Map<String, dynamic>> getQrInfo(String token) async {
    try {
      final response = await _dio.get<Map<String, dynamic>>('/cutoff/qr/$token/info');
      return response.data ?? <String, dynamic>{};
    } on DioException catch (e) {
      throw ApiException.fromDio(e);
    }
  }

  Future<Map<String, dynamic>> confirmByQr(
    String token,
    Map<String, dynamic> payload,
  ) async {
    try {
      final response = await _dio.post<Map<String, dynamic>>(
        '/cutoff/qr/$token/confirm',
        data: payload,
      );
      return response.data ?? <String, dynamic>{};
    } on DioException catch (e) {
      throw ApiException.fromDio(e);
    }
  }

  Future<String?> uploadPhoto(
    String filePath, {
    required String tipo,
  }) async {
    try {
      final formData = FormData.fromMap({
        'file': await MultipartFile.fromFile(filePath),
      });

      final response = await _dio.post<Map<String, dynamic>>(
        '/upload/photo',
        queryParameters: {'tipo': tipo},
        data: formData,
      );
      return response.data?['url'] as String?;
    } on DioException catch (e) {
      throw ApiException.fromDio(e);
    }
  }

  List<Map<String, dynamic>> _toMapList(List<dynamic>? raw) {
    if (raw == null) return const [];
    return raw
        .whereType<Map<String, dynamic>>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
  }
}
