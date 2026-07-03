import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/i18n/language_provider.dart';
import 'app_strings.dart';

extension ContextI18n on BuildContext {
  String t(String key) {
    final language = watch<LanguageProvider>().locale.languageCode;
    final byLanguage = appStrings[language] ?? appStrings['pt']!;
    return byLanguage[key] ?? appStrings['pt']![key] ?? key;
  }
}
