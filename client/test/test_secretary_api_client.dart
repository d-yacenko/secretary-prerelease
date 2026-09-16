import 'package:http/testing.dart';
import 'package:personal_secretary/api/secretary_api_client.dart';
import 'package:personal_secretary/timezone/client_timezone_context.dart';

const testTimezoneProvider = FixedClientTimezoneProvider(
  ClientTimezoneContext(zoneId: 'Europe/Amsterdam', utcOffsetMinutes: 120),
);

SecretaryApiClient testSecretaryApiClient(
  MockClient mock, {
  Duration timeout = const Duration(seconds: 2),
}) {
  return SecretaryApiClient(
    httpClient: mock,
    timezoneProvider: testTimezoneProvider,
    timeout: timeout,
  );
}
