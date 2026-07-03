import 'package:dio/dio.dart';

import '../../../core/auth/session_manager.dart';
import '../../../core/network/api_exception.dart';
import '../../../core/network/dio_client.dart';

class ClientsApi {
  ClientsApi({required SessionManager sessionManager})
      : _dio = DioClient.build(sessionManager);

  final Dio _dio;

  Future<Map<String, dynamic>> createClient(Map<String, dynamic> payload) async {
    try {
      final response = await _dio.post<Map<String, dynamic>>(
        '/clients/',
        data: payload,
      );
      return response.data ?? <String, dynamic>{};
    } on DioException catch (e) {
      throw ApiException.fromDio(e);
    }
  }

  Future<String?> uploadMeterPhoto(String filePath) async {
    try {
      final formData = FormData.fromMap({
        'file': await MultipartFile.fromFile(filePath),
      });

      final response = await _dio.post<Map<String, dynamic>>(
        '/upload/photo',
        queryParameters: const {'tipo': 'medidor'},
        data: formData,
      );
      return response.data?['url'] as String?;
    } on DioException catch (e) {
      throw ApiException.fromDio(e);
    }
  }
}
