import 'dart:io';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../core/auth/auth_provider.dart';
import '../../readings/services/photo_capture_service.dart';
import '../domain/qr_info.dart';
import '../services/cutoff_workflow_service.dart';

class QrConfirmScreen extends StatefulWidget {
  const QrConfirmScreen({
    super.key,
    required this.token,
  });

  final String token;

  @override
  State<QrConfirmScreen> createState() => _QrConfirmScreenState();
}

class _QrConfirmScreenState extends State<QrConfirmScreen> {
  final _responsavelController = TextEditingController();
  final _observacionController = TextEditingController();
  final _photoService = PhotoCaptureService();

  QrInfo? _qrInfo;
  CapturedPhoto? _capturedPhoto;
  bool _loadingInfo = true;
  bool _capturing = false;
  bool _confirming = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _responsavelController.text = (context.read<AuthProvider>().user?['full_name'] ?? '')
        .toString();
    _loadQrInfo();
  }

  @override
  void dispose() {
    _responsavelController.dispose();
    _observacionController.dispose();
    super.dispose();
  }

  Future<void> _loadQrInfo() async {
    setState(() {
      _loadingInfo = true;
      _error = null;
    });

    try {
      final service = context.read<CutoffWorkflowService>();
      final info = await service.getQrInfo(widget.token);
      if (!mounted) return;
      setState(() {
        _qrInfo = info;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
      });
    } finally {
      if (mounted) {
        setState(() {
          _loadingInfo = false;
        });
      }
    }
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

  Future<void> _confirmAction() async {
    final info = _qrInfo;
    if (info == null) return;

    final nome = _responsavelController.text.trim();
    if (nome.length < 2) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Informe nome do responsável')),
      );
      return;
    }

    final requiresEvidence = info.actionType == 'EXECUCAO_CORTE' ||
        info.actionType == 'CONFIRMACAO_REATIVACAO';
    if (requiresEvidence && _capturedPhoto == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Foto de evidência é obrigatória')),
      );
      return;
    }

    setState(() {
      _confirming = true;
      _error = null;
    });

    try {
      final service = context.read<CutoffWorkflowService>();
      final result = await service.confirmByQrAction(
        rawToken: widget.token,
        nomeResponsavel: nome,
        observacion: _observacionController.text,
        photoPath: _capturedPhoto?.path,
        gpsLatitude: _capturedPhoto?.latitude,
        gpsLongitude: _capturedPhoto?.longitude,
        actionType: info.actionType,
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(result.message)),
      );
      Navigator.of(context).pop(true);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
      });
    } finally {
      if (mounted) {
        setState(() {
          _confirming = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loadingInfo) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      );
    }

    final info = _qrInfo;
    return Scaffold(
      appBar: AppBar(title: const Text('Confirm QR action')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            if (_error != null) ...[
              Text(
                _error!,
                style: const TextStyle(color: Colors.red),
              ),
              const SizedBox(height: 10),
            ],
            if (info != null) ...[
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        info.clientNombre,
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      const SizedBox(height: 4),
                      Text('Action: ${_actionLabel(info.actionType)}'),
                      Text('Status: ${info.status}'),
                      Text('CI/RUC: ${info.clientCiRuc}'),
                      Text('Route: ${info.clientManzana}-${info.clientLote}'),
                      Text('Address: ${info.clientDireccion}'),
                      if (info.dividaOriginal != null)
                        Text('Debt: ${info.dividaOriginal!.toStringAsFixed(2)}'),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 10),
            ],
            TextField(
              controller: _responsavelController,
              decoration: const InputDecoration(
                labelText: 'Responsible name',
              ),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _observacionController,
              minLines: 2,
              maxLines: 4,
              decoration: const InputDecoration(
                labelText: 'Observation (optional)',
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
              label: Text(_capturing ? 'Capturing...' : 'Take evidence photo'),
            ),
            if (_capturedPhoto != null) ...[
              const SizedBox(height: 10),
              ClipRRect(
                borderRadius: BorderRadius.circular(12),
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
            ElevatedButton.icon(
              onPressed: _confirming ? null : _confirmAction,
              icon: _confirming
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.verified),
              label: Text(_confirming ? 'Confirming...' : 'Confirm action'),
            ),
          ],
        ),
      ),
    );
  }

  String _actionLabel(String actionType) {
    switch (actionType) {
      case 'ENTREGA_AVISO':
        return 'Notice delivery';
      case 'EXECUCAO_CORTE':
        return 'Cutoff execution';
      case 'CONFIRMACAO_REATIVACAO':
        return 'Reactivation confirmation';
      default:
        return actionType;
    }
  }
}
