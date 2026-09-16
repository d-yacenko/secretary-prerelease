import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/config/url_utils.dart';

void main() {
  group('parseApiBaseUrl', () {
    test('normalizes trailing slashes', () {
      expect(parseApiBaseUrl('https://host/')?.toString(), 'https://host');
      expect(parseApiBaseUrl('https://host///')?.toString(), 'https://host');
      expect(parseApiBaseUrl('https://host/api/')?.toString(), 'https://host/api');
    });

    test('preserves intentional base path prefix', () {
      expect(parseApiBaseUrl('https://host/api')?.pathSegments, ['api']);
    });

    test('rejects query and fragment base URLs', () {
      expect(parseApiBaseUrl('https://host?x=1'), isNull);
      expect(parseApiBaseUrl('https://host#frag'), isNull);
      expect(parseApiBaseUrl('https://host/api?x=1'), isNull);
    });

    test('rejects non-http schemes', () {
      expect(parseApiBaseUrl('ftp://host'), isNull);
    });
  });

  group('buildApiEndpointUri', () {
    final base = parseApiBaseUrl('https://host/api')!;

    test('resolves API endpoints under base path', () {
      expect(
        buildApiEndpointUri(base, '/me').toString(),
        'https://host/api/me',
      );
      expect(
        buildApiEndpointUri(base, '/connections').toString(),
        'https://host/api/connections',
      );
      expect(
        buildApiEndpointUri(base, '/capture/task').toString(),
        'https://host/api/capture/task',
      );
    });

    test('resolves root-hosted endpoints', () {
      final root = parseApiBaseUrl('https://host/')!;
      expect(buildApiEndpointUri(root, '/me').toString(), 'https://host/me');
    });
  });
}
