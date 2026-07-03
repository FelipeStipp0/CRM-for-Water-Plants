import 'package:flutter/foundation.dart';

import '../domain/cutoff_notice_detail.dart';
import '../services/cutoff_workflow_service.dart';

class CutoffProvider extends ChangeNotifier {
  CutoffProvider({required CutoffWorkflowService service}) : _service = service;

  final CutoffWorkflowService _service;

  bool _loading = false;
  String? _error;
  String? _statusFilter = 'PRONTO_PARA_CORTE';
  String _search = '';
  List<CutoffNoticeDetail> _tasks = const [];

  bool get loading => _loading;
  String? get error => _error;
  String? get statusFilter => _statusFilter;
  String get search => _search;
  List<CutoffNoticeDetail> get tasks => _filterTasks();

  static const statusOptions = <String>[
    'EM_LISTA',
    'EM_AVISO',
    'EM_CONTAGEM',
    'PRONTO_PARA_CORTE',
    'CORTADO',
  ];

  Future<void> loadTasks() async {
    _loading = true;
    _error = null;
    notifyListeners();

    try {
      _tasks = await _service.fetchTasks(status: _statusFilter);
    } catch (e) {
      _error = e.toString();
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  Future<void> setStatusFilter(String? status) async {
    _statusFilter = status;
    notifyListeners();
    await loadTasks();
  }

  void setSearch(String value) {
    _search = value.trim().toLowerCase();
    notifyListeners();
  }

  List<CutoffNoticeDetail> _filterTasks() {
    if (_search.isEmpty) return _tasks;
    return _tasks.where((task) {
      final text = [
        task.clientNombre,
        task.clientCiRuc,
        task.clientManzana,
        task.clientLote,
        task.clientDireccion,
      ].join(' ').toLowerCase();
      return text.contains(_search);
    }).toList();
  }

  static String statusLabel(String status) {
    switch (status) {
      case 'EM_LISTA':
        return 'Em lista';
      case 'EM_AVISO':
        return 'Em aviso';
      case 'EM_CONTAGEM':
        return 'Em contagem';
      case 'PRONTO_PARA_CORTE':
        return 'Pronto p/ corte';
      case 'CORTADO':
        return 'Cortado';
      default:
        return status;
    }
  }
}
