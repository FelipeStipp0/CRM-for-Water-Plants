class ApiConfig {
  // Defina a URL da API no build/run (obrigatório em produção):
  // --dart-define=JUNTA_API_URL=https://seu-host-da-api
  static const baseUrl = String.fromEnvironment(
    'JUNTA_API_URL',
    defaultValue: 'http://localhost:8000',
  );

  static const connectTimeoutMs = 8000;
  static const receiveTimeoutMs = 12000;
}
