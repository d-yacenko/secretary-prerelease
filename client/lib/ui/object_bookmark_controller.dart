import 'package:flutter/foundation.dart';

import '../api/api_error.dart';
import '../api/secretary_api_client.dart';
import '../auth/auth_controller.dart';
import 'assigned_bookmarks_loader.dart';

class ObjectBookmarkController extends ChangeNotifier {
  ObjectBookmarkController({
    required SecretaryApiClient apiClient,
    required AuthController authController,
  })  : _apiClient = apiClient,
        _authController = authController;

  final SecretaryApiClient _apiClient;
  final AuthController _authController;
  final Map<String, String> _colors = {};
  final Map<String, int> _generations = {};

  String? colorFor(String objectId) => _colors[objectId];

  Map<String, String> get colors => Map.unmodifiable(_colors);

  int _bump(String objectId) {
    final next = (_generations[objectId] ?? 0) + 1;
    _generations[objectId] = next;
    return next;
  }

  /// Returns whether the visible-id batch read succeeded.
  ///
  /// An empty ID set is success. Auth/API/network failure returns false and
  /// leaves the existing cache unchanged.
  Future<bool> reconcileVisible(Iterable<String> objectIds) async {
    final unique = uniqueObjectIds(objectIds);
    if (unique.isEmpty) {
      return true;
    }
    final snapshot = <String, int>{
      for (final id in unique) id: _generations[id] ?? 0,
    };
    final loaded = await loadBookmarksByObjects(
      apiClient: _apiClient,
      onAuthFailure: _authController.handleAuthenticationFailure,
      objectIds: unique,
    );
    if (!loaded.succeeded) {
      return false;
    }
    final fetched = loaded.bookmarks;
    var changed = false;
    for (final id in unique) {
      if ((_generations[id] ?? 0) != snapshot[id]) {
        continue;
      }
      final serverColor = fetched[id];
      if (serverColor == null) {
        if (_colors.remove(id) != null) {
          changed = true;
        }
      } else if (_colors[id] != serverColor) {
        _colors[id] = serverColor;
        changed = true;
      }
    }
    if (changed) {
      notifyListeners();
    }
    return true;
  }

  Future<void> setColor(String objectId, String color) async {
    final previous = _colors[objectId];
    final gen = _bump(objectId);
    _colors[objectId] = color;
    notifyListeners();
    try {
      final saved = await _apiClient.putObjectBookmark(objectId, color);
      if (_generations[objectId] != gen) {
        return;
      }
      if (_colors[objectId] != saved) {
        _colors[objectId] = saved;
        notifyListeners();
      }
    } on AuthenticationException {
      _authController.handleAuthenticationFailure();
    } on ApiException {
      if (_generations[objectId] != gen) {
        return;
      }
      if (previous == null) {
        _colors.remove(objectId);
      } else {
        _colors[objectId] = previous;
      }
      notifyListeners();
    }
  }

  Future<void> clear(String objectId) async {
    final previous = _colors[objectId];
    final gen = _bump(objectId);
    _colors.remove(objectId);
    notifyListeners();
    try {
      await _apiClient.deleteObjectBookmark(objectId);
    } on AuthenticationException {
      _authController.handleAuthenticationFailure();
    } on ApiException {
      if (_generations[objectId] != gen) {
        return;
      }
      if (previous != null) {
        _colors[objectId] = previous;
        notifyListeners();
      }
    }
  }

  void forget(String objectId) {
    _bump(objectId);
    if (_colors.remove(objectId) != null) {
      notifyListeners();
    }
  }

  void resetSession() {
    if (_colors.isEmpty && _generations.isEmpty) {
      return;
    }
    _colors.clear();
    _generations.clear();
    notifyListeners();
  }
}
