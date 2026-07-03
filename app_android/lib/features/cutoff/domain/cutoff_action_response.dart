class CutoffActionResponse {
  CutoffActionResponse({
    required this.success,
    required this.message,
    this.cutoffNoticeId,
  });

  final bool success;
  final String message;
  final String? cutoffNoticeId;

  factory CutoffActionResponse.fromMap(Map<String, dynamic> map) {
    return CutoffActionResponse(
      success: map['success'] == true,
      message: (map['message'] ?? '').toString(),
      cutoffNoticeId: map['cutoff_notice_id']?.toString(),
    );
  }
}
