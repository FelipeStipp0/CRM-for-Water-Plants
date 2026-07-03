import 'package:connectivity_plus/connectivity_plus.dart';

class NetworkStatusService {
  const NetworkStatusService._();

  static Future<bool> isOnline() async {
    final result = await Connectivity().checkConnectivity();
    return !result.contains(ConnectivityResult.none);
  }
}
