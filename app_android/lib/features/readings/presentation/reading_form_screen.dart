import 'dart:io';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../domain/route_client.dart';
import '../services/photo_capture_service.dart';
import 'readings_provider.dart';

class ReadingFormScreen extends StatefulWidget {
  const ReadingFormScreen({
    super.key,
    required this.client,
  });

  final RouteClient client;

  @override
  State<ReadingFormScreen> createState() => _ReadingFormScreenState();
}

class _ReadingFormScreenState extends State<ReadingFormScreen> {
  final _formKey = GlobalKey<FormState>();
  final _readingController = TextEditingController();
  final _obsController = TextEditingController();
  final _photoService = PhotoCaptureService();
  CapturedPhoto? _capturedPhoto;
  bool _capturing = false;

  @override
  void dispose() {
    _readingController.dispose();
    _obsController.dispose();
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

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    final provider = context.read<ReadingsProvider>();
    final valor = int.parse(_readingController.text.trim());
    final ok = await provider.saveReadingOffline(
      client: widget.client,
      valorLeitura: valor,
      observacion: _obsController.text.trim().isEmpty ? null : _obsController.text.trim(),
      photo: _capturedPhoto,
    );
    if (!mounted) return;

    if (!ok) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(provider.error ?? 'Failed to save')),
      );
      return;
    }

    final synced = provider.lastSaveMode == 'synced';
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          synced
              ? 'Reading sent successfully'
              : 'No connection. Reading queued for automatic sync',
        ),
      ),
    );
    Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<ReadingsProvider>();

    return Scaffold(
      appBar: AppBar(
        title: Text('${widget.client.nombre} - ${widget.client.medidor}'),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Form(
          key: _formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Client: ${widget.client.nombre}'),
                      Text('Meter: ${widget.client.medidor}'),
                      Text('Route: ${widget.client.manzana}-${widget.client.lote}'),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _readingController,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'Reading value',
                ),
                validator: (value) {
                  final parsed = int.tryParse(value ?? '');
                  if (parsed == null || parsed < 0) {
                    return 'Invalid reading';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _obsController,
                minLines: 2,
                maxLines: 4,
                decoration: const InputDecoration(
                  labelText: 'Observation (optional)',
                ),
              ),
              const SizedBox(height: 14),
              ElevatedButton.icon(
                onPressed: _capturing ? null : _capturePhoto,
                icon: _capturing
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.camera_alt),
                label: Text(_capturing ? 'Capturing...' : 'Take meter photo'),
              ),
              const SizedBox(height: 10),
              if (_capturedPhoto != null) ...[
                ClipRRect(
                  borderRadius: BorderRadius.circular(10),
                  child: Image.file(
                    File(_capturedPhoto!.path),
                    height: 180,
                    width: double.infinity,
                    fit: BoxFit.cover,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  _capturedPhoto!.latitude != null && _capturedPhoto!.longitude != null
                      ? 'GPS: ${_capturedPhoto!.latitude}, ${_capturedPhoto!.longitude}'
                      : 'GPS: unavailable',
                  style: const TextStyle(fontSize: 12),
                ),
              ],
              const SizedBox(height: 18),
              ElevatedButton(
                onPressed: provider.saving ? null : _save,
                child: provider.saving
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Text('Save reading'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
