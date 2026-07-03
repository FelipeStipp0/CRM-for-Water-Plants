import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:provider/provider.dart';

import '../core/auth/auth_provider.dart';
import '../core/i18n/language_provider.dart';
import '../features/home/presentation/home_shell.dart';
import '../features/login/presentation/login_screen.dart';
import '../shared/i18n/context_i18n.dart';
import '../shared/theme/app_theme.dart';
import 'routes.dart';

class JuntaFieldApp extends StatelessWidget {
  const JuntaFieldApp({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer2<AuthProvider, LanguageProvider>(
      builder: (context, auth, language, _) {
        return MaterialApp(
          title: context.t('app_title'),
          debugShowCheckedModeBanner: false,
          theme: AppTheme.lightTheme(),
          locale: language.locale,
          supportedLocales: const [
            Locale('pt'),
            Locale('es'),
          ],
          localizationsDelegates: GlobalMaterialLocalizations.delegates,
          onGenerateRoute: AppRoutes.onGenerateRoute,
          home: _buildHome(auth),
        );
      },
    );
  }

  Widget _buildHome(AuthProvider auth) {
    if (!auth.initialized) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      );
    }

    if (auth.isAuthenticated && !auth.mustChangePassword) {
      return const HomeShell();
    }

    return const LoginScreen();
  }
}
