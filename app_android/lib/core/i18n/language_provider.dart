import 'dart:ui';

import 'package:flutter/material.dart';

import '../storage/secure_storage_service.dart';

class LanguageProvider extends ChangeNotifier {
  LanguageProvider(this._storage);

  final SecureStorageService _storage;
  Locale _locale = const Locale('pt');
  bool _initialized = false;

  Locale get locale => _locale;
  bool get initialized => _initialized;

  Future<void> initialize() async {
    final storedCode = await _storage.readLanguageCode();
    if (storedCode == 'pt' || storedCode == 'es') {
      _locale = Locale(storedCode!);
    } else {
      final systemCode = PlatformDispatcher.instance.locale.languageCode.toLowerCase();
      _locale = Locale(systemCode == 'es' ? 'es' : 'pt');
    }
    _initialized = true;
    notifyListeners();
  }

  Future<void> setLanguage(String code) async {
    if (code != 'pt' && code != 'es') return;
    if (_locale.languageCode == code) return;
    _locale = Locale(code);
    await _storage.writeLanguageCode(code);
    notifyListeners();
  }
}
