# Junta CRM - Mobile Field App (Flutter)

This folder contains the Android field app client (V1.0 start) for Junta CRM.

## Scope implemented

- Authentication with `POST /auth/token` and JWT persistence.
- Token/session restore on app startup.
- Route download for field work:
  - `GET /clients/by-route`
  - `GET /readings/by-route`
- Offline reading save in local SQLite queue.
- Camera capture + GPS capture for reading evidence.
- Sync screen:
  - Upload photo with `POST /upload/photo?tipo=lectura`
  - Send reading with `POST /readings/`
  - Track synced/failed counts

## Project status

Flutter SDK is not installed in the current machine shell, so this was bootstrapped manually.

When Flutter is available, run from this folder:

```bash
flutter create .
flutter pub get
flutter run --dart-define=JUNTA_API_URL=http://YOUR_API_HOST:8000
```

Important:
- Android emulator uses `http://10.0.2.2:8000` for local backend.
- Physical device must use your LAN IP.

## Android permissions required

Ensure these are present in `android/app/src/main/AndroidManifest.xml`:

```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.CAMERA" />
<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
<uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />
```

## V1.0 notes

- The app is offline-first for readings and route usage.
- Sync retry is manual via Sync tab in this initial version.
- EXIF GPS writing is not yet enforced; GPS coordinates are captured and sent in payload.
