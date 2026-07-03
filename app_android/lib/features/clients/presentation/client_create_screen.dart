import 'dart:io';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../shared/i18n/context_i18n.dart';
import '../../readings/services/photo_capture_service.dart';
import '../services/client_registration_service.dart';

class ClientCreateScreen extends StatefulWidget {
  const ClientCreateScreen({super.key});

  @override
  State<ClientCreateScreen> createState() => _ClientCreateScreenState();
}

class _ClientCreateScreenState extends State<ClientCreateScreen> {
  final _formKey = GlobalKey<FormState>();

  final _nombreController = TextEditingController();
  final _ciRucController = TextEditingController();
  final _telefonoController = TextEditingController();
  final _celularController = TextEditingController();
  final _direccionController = TextEditingController();
  final _manzanaController = TextEditingController();
  final _loteController = TextEditingController();
  final _medidorController = TextEditingController();
  final _subsidioController = TextEditingController();

  final _photoService = PhotoCaptureService();
  CapturedPhoto? _capturedPhoto;

  String _categoria = 'RESIDENCIAL';
  bool _saving = false;
  bool _capturing = false;
  String? _error;

  @override
  void dispose() {
    _nombreController.dispose();
    _ciRucController.dispose();
    _telefonoController.dispose();
    _celularController.dispose();
    _direccionController.dispose();
    _manzanaController.dispose();
    _loteController.dispose();
    _medidorController.dispose();
    _subsidioController.dispose();
    super.dispose();
  }

  Future<void> _capturePhoto() async {
    setState(() => _capturing = true);
    final photo = await _photoService.captureMeterPhoto();
    if (!mounted) return;
    setState(() {
      _capturedPhoto = photo;
      _capturing = false;
    });
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() {
      _saving = true;
      _error = null;
    });

    try {
      final service = context.read<ClientRegistrationService>();

      final subsidio = int.tryParse(_subsidioController.text.trim());

      final payload = <String, dynamic>{
        'nombre_completo': _nombreController.text.trim(),
        'ci_ruc': _ciRucController.text.trim(),
        'direccion': _direccionController.text.trim(),
        'manzana': _manzanaController.text.trim(),
        'lote': _loteController.text.trim(),
        'numero_medidor': _medidorController.text.trim(),
        'categoria': _categoria,
        'is_sponsor': false,
        if (_telefonoController.text.trim().isNotEmpty)
          'telefono': _telefonoController.text.trim(),
        if (_celularController.text.trim().isNotEmpty)
          'celular': _celularController.text.trim(),
        if (subsidio != null) 'subsidio_porcentagem': subsidio,
        if (_capturedPhoto?.latitude != null)
          'instalacao_latitude': _capturedPhoto!.latitude,
        if (_capturedPhoto?.longitude != null)
          'instalacao_longitude': _capturedPhoto!.longitude,
      };

      final result = await service.submitClient(
        payload: payload,
        photoPath: _capturedPhoto?.path,
      );
      if (!mounted) return;

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            result.synced
                ? 'Client created successfully'
                : 'No connection. Client queued for automatic sync',
          ),
        ),
      );
      _resetForm();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
      });
    } finally {
      if (mounted) {
        setState(() => _saving = false);
      }
    }
  }

  void _resetForm() {
    _formKey.currentState?.reset();
    _nombreController.clear();
    _ciRucController.clear();
    _telefonoController.clear();
    _celularController.clear();
    _direccionController.clear();
    _manzanaController.clear();
    _loteController.clear();
    _medidorController.clear();
    _subsidioController.clear();
    setState(() {
      _categoria = 'RESIDENCIAL';
      _capturedPhoto = null;
      _error = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            context.t('client_registration'),
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 12),
          Form(
            key: _formKey,
            child: Column(
              children: [
                TextFormField(
                  controller: _nombreController,
                  decoration: const InputDecoration(labelText: 'Full name'),
                  validator: _requiredValidator,
                ),
                const SizedBox(height: 8),
                TextFormField(
                  controller: _ciRucController,
                  decoration: const InputDecoration(labelText: 'CI/RUC'),
                  validator: _requiredValidator,
                ),
                const SizedBox(height: 8),
                TextFormField(
                  controller: _direccionController,
                  decoration: const InputDecoration(labelText: 'Address'),
                  validator: _requiredValidator,
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Expanded(
                      child: TextFormField(
                        controller: _manzanaController,
                        decoration: const InputDecoration(labelText: 'Manzana'),
                        validator: _requiredValidator,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: TextFormField(
                        controller: _loteController,
                        decoration: const InputDecoration(labelText: 'Lote'),
                        validator: _requiredValidator,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                TextFormField(
                  controller: _medidorController,
                  decoration: const InputDecoration(labelText: 'Meter number'),
                  validator: _requiredValidator,
                ),
                const SizedBox(height: 8),
                DropdownButtonFormField<String>(
                  key: ValueKey<String>(_categoria),
                  initialValue: _categoria,
                  decoration: const InputDecoration(labelText: 'Category'),
                  items: const [
                    DropdownMenuItem(value: 'RESIDENCIAL', child: Text('Residencial')),
                    DropdownMenuItem(value: 'COMERCIAL', child: Text('Comercial')),
                    DropdownMenuItem(value: 'SOCIAL', child: Text('Social')),
                  ],
                  onChanged: (value) {
                    if (value == null) return;
                    setState(() => _categoria = value);
                  },
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Expanded(
                      child: TextFormField(
                        controller: _telefonoController,
                        decoration: const InputDecoration(labelText: 'Phone (optional)'),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: TextFormField(
                        controller: _celularController,
                        decoration: const InputDecoration(labelText: 'Cell (optional)'),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                TextFormField(
                  controller: _subsidioController,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(
                    labelText: 'Subsidy % (optional)',
                  ),
                ),
                const SizedBox(height: 12),
                ElevatedButton.icon(
                  onPressed: _capturing ? null : _capturePhoto,
                  icon: _capturing
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.camera_alt),
                  label: Text(
                    _capturing
                        ? context.t('capturing')
                        : context.t('capture_meter_photo_gps'),
                  ),
                ),
                if (_capturedPhoto != null) ...[
                  const SizedBox(height: 10),
                  ClipRRect(
                    borderRadius: BorderRadius.circular(10),
                    child: Image.file(
                      File(_capturedPhoto!.path),
                      height: 170,
                      width: double.infinity,
                      fit: BoxFit.cover,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    _capturedPhoto!.latitude != null && _capturedPhoto!.longitude != null
                        ? 'GPS: ${_capturedPhoto!.latitude}, ${_capturedPhoto!.longitude}'
                        : 'GPS unavailable',
                    style: const TextStyle(fontSize: 12),
                  ),
                ],
                if (_error != null) ...[
                  const SizedBox(height: 10),
                  Text(
                    _error!,
                    style: const TextStyle(color: Colors.red),
                  ),
                ],
                const SizedBox(height: 16),
                ElevatedButton.icon(
                  onPressed: _saving ? null : _submit,
                  icon: _saving
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.save),
                  label: Text(
                    _saving ? context.t('saving') : context.t('create_client'),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  String? _requiredValidator(String? value) {
    if (value == null || value.trim().isEmpty) return 'Required';
    return null;
  }
}
