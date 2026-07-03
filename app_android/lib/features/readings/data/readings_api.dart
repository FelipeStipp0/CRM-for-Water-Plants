import 'package:dio/dio.dart';

import '../../../core/auth/session_manager.dart';
import '../../../core/network/api_exception.dart';
import '../../../core/network/dio_client.dart';

class ReadingsApi {
  ReadingsApi({required SessionManager sessionManager})
      : _dio = DioClient.build(sessionManager);

  final Dio _dio;

  Future<List<Map<String, dynamic>>> fetchClientsByRoute({
    String? manzana,
  }) async {
    try {
      final response = await _dio.get<List<dynamic>>(
        '/clients/by-route',
        queryParameters: {
          if (manzana != null && manzana.isNotEmpty) 'manzana': manzana,
        },
      );
      return _toMapList(response.data);
    } on DioException catch (e) {
      throw ApiException.fromDio(e);
    }
  }

  Future<List<Map<String, dynamic>>> fetchReadingsByRoute({
    required int mes,
    required int ano,
    String? manzana,
  }) async {
    try {
      final response = await _dio.get<List<dynamic>>(
        '/readings/by-route',
        queryParameters: {
          'mes': mes,
          'ano': ano,
          if (manzana != null && manzana.isNotEmpty) 'manzana': manzana,
        },
      );
      return _toMapList(response.data);
    } on DioException catch (e) {
      throw ApiException.fromDio(e);
    }
  }

  Future<void> createReading(Map<String, dynamic> payload) async {
    try {
      await _dio.post<Map<String, dynamic>>('/readings/', data: payload);
    } on DioException catch (e) {
      throw ApiException.fromDio(e);
    }
  }

  Future<String?> uploadPhoto(
    String filePath, {
    String tipo = 'lectura',
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
