import 'package:geolocator/geolocator.dart';
import 'package:image_picker/image_picker.dart';

class CapturedPhoto {
  CapturedPhoto({
    required this.path,
    this.latitude,
    this.longitude,
  });

  final String path;
  final double? latitude;
  final double? longitude;
}

class PhotoCaptureService {
  final ImagePicker _picker = ImagePicker();

  Future<CapturedPhoto?> captureMeterPhoto() async {
    final photo = await _picker.pickImage(
      source: ImageSource.camera,
      imageQuality: 85,
      preferredCameraDevice: CameraDevice.rear,
    );
    if (photo == null) {
      return null;
    }

    final position = await _tryGetCurrentPosition();
    return CapturedPhoto(
      path: photo.path,
      latitude: position?.latitude,
      longitude: position?.longitude,
    );
  }

  Future<Position?> _tryGetCurrentPosition() async {
    final serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) return null;

    LocationPermission permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }

    if (permission == LocationPermission.denied ||
        permission == LocationPermission.deniedForever) {
      return null;
    }

    try {
      return await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(accuracy: LocationAccuracy.high),
      );
    } catch (_) {
      return null;
    }
  }
}
