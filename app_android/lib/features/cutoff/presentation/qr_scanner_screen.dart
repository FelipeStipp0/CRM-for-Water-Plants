import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../services/cutoff_workflow_service.dart';
import 'qr_confirm_screen.dart';

class QrScannerScreen extends StatefulWidget {
  const QrScannerScreen({super.key});

  @override
  State<QrScannerScreen> createState() => _QrScannerScreenState();
}

class _QrScannerScreenState extends State<QrScannerScreen> {
  final _manualTokenController = TextEditingController();
  final _scannerController = MobileScannerController();
  bool _handling = false;

  @override
  void dispose() {
    _manualTokenController.dispose();
    _scannerController.dispose();
    super.dispose();
  }

  Future<void> _openConfirmScreen(String rawValue) async {
    if (_handling) return;

    final token = CutoffWorkflowService.normalizeQrToken(rawValue);
    if (token.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Invalid QR token')),
      );
      return;
    }

    setState(() => _handling = true);
    final confirmed = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => QrConfirmScreen(token: token),
      ),
    );
    if (!mounted) return;
    if (confirmed == true) {
      Navigator.of(context).pop(true);
      return;
    }
    setState(() => _handling = false);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Scan QR')),
      body: Column(
        children: [
          Expanded(
            child: MobileScanner(
              controller: _scannerController,
              onDetect: (capture) {
                if (_handling) return;
                for (final barcode in capture.barcodes) {
                  final rawValue = barcode.rawValue;
                  if (rawValue != null && rawValue.trim().isNotEmpty) {
                    _openConfirmScreen(rawValue);
                    break;
                  }
                }
              },
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
            child: Column(
              children: [
                TextField(
                  controller: _manualTokenController,
                  decoration: const InputDecoration(
                    labelText: 'Manual token',
                    hintText: 'Paste token or QR URL',
                  ),
                ),
                const SizedBox(height: 8),
                ElevatedButton.icon(
                  onPressed: _handling
                      ? null
                      : () => _openConfirmScreen(_manualTokenController.text),
                  icon: const Icon(Icons.send),
                  label: Text(_handling ? 'Opening...' : 'Open token'),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
