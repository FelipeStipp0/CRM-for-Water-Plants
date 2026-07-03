import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../core/auth/auth_provider.dart';
import '../../../shared/i18n/context_i18n.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();

  final _currentPasswordController = TextEditingController();
  final _newPasswordController = TextEditingController();

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    _currentPasswordController.dispose();
    _newPasswordController.dispose();
    super.dispose();
  }

  Future<void> _submitLogin(AuthProvider auth) async {
    if (!_formKey.currentState!.validate()) return;
    final ok = await auth.login(
      _usernameController.text.trim(),
      _passwordController.text,
    );
    if (!mounted || ok) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(auth.error ?? 'Login failed')),
    );
  }

  Future<void> _submitChangePassword(AuthProvider auth) async {
    final current = _currentPasswordController.text;
    final next = _newPasswordController.text;
    if (current.isEmpty || next.length < 6) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('New password must have at least 6 chars')),
      );
      return;
    }

    final ok = await auth.changePassword(current, next);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(ok ? 'Password updated' : (auth.error ?? 'Failed'))),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<AuthProvider>(
      builder: (_, auth, __) {
        return Scaffold(
          body: SafeArea(
            child: Center(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(20),
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 420),
                  child: Card(
                    child: Padding(
                      padding: const EdgeInsets.all(20),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            context.t('login_title'),
                            style: Theme.of(context).textTheme.headlineSmall,
                          ),
                          const SizedBox(height: 6),
                          Text(context.t('login_subtitle')),
                          const SizedBox(height: 20),
                          Form(
                            key: _formKey,
                            child: Column(
                              children: [
                                TextFormField(
                                  controller: _usernameController,
                                  decoration: InputDecoration(
                                    labelText: context.t('username'),
                                  ),
                                  validator: (value) {
                                    if (value == null || value.trim().isEmpty) {
                                      return 'Required';
                                    }
                                    return null;
                                  },
                                ),
                                const SizedBox(height: 12),
                                TextFormField(
                                  controller: _passwordController,
                                  decoration: InputDecoration(
                                    labelText: context.t('password'),
                                  ),
                                  obscureText: true,
                                  validator: (value) {
                                    if (value == null || value.isEmpty) {
                                      return 'Required';
                                    }
                                    return null;
                                  },
                                ),
                                const SizedBox(height: 16),
                                ElevatedButton(
                                  onPressed: auth.loading ? null : () => _submitLogin(auth),
                                  child: auth.loading
                                      ? const SizedBox(
                                          width: 18,
                                          height: 18,
                                      child: CircularProgressIndicator(strokeWidth: 2),
                                    )
                                      : Text(context.t('sign_in')),
                                ),
                              ],
                            ),
                          ),
                          if (auth.mustChangePassword) ...[
                            const Divider(height: 32),
                            Text(
                              context.t('password_change_required'),
                              style: Theme.of(context).textTheme.titleMedium,
                            ),
                            const SizedBox(height: 8),
                            TextField(
                              controller: _currentPasswordController,
                              decoration: InputDecoration(
                                labelText: context.t('current_password'),
                              ),
                              obscureText: true,
                            ),
                            const SizedBox(height: 8),
                            TextField(
                              controller: _newPasswordController,
                              decoration: InputDecoration(
                                labelText: context.t('new_password'),
                              ),
                              obscureText: true,
                            ),
                            const SizedBox(height: 12),
                            ElevatedButton(
                              onPressed: auth.loading
                                  ? null
                                  : () => _submitChangePassword(auth),
                              child: Text(context.t('update_password')),
                            ),
                          ],
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}
