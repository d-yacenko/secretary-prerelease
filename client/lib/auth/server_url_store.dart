import 'package:shared_preferences/shared_preferences.dart';

/// Persists the non-secret Secretary API base URL.
abstract class ServerUrlStore {
  Future<String?> readServerUrl();
  Future<void> writeServerUrl(String url);
  Future<void> deleteServerUrl();
}

class SharedPreferencesServerUrlStore implements ServerUrlStore {
  SharedPreferencesServerUrlStore(this._prefs);

  static const _key = 'secretary_api_base_url';
  final SharedPreferences _prefs;

  @override
  Future<String?> readServerUrl() async => _prefs.getString(_key);

  @override
  Future<void> writeServerUrl(String url) async {
    await _prefs.setString(_key, url);
  }

  @override
  Future<void> deleteServerUrl() async {
    await _prefs.remove(_key);
  }
}

/// In-memory server URL store for tests.
class FakeServerUrlStore implements ServerUrlStore {
  String? _url;

  @override
  Future<String?> readServerUrl() async => _url;

  @override
  Future<void> writeServerUrl(String url) async {
    _url = url;
  }

  @override
  Future<void> deleteServerUrl() async {
    _url = null;
  }
}
