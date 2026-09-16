import 'package:flutter_timezone/flutter_timezone.dart';

class ClientTimezoneContext {
  const ClientTimezoneContext({
    required this.zoneId,
    required this.utcOffsetMinutes,
  });

  final String? zoneId;
  final int utcOffsetMinutes;

  Map<String, String> queryParameters() {
    final params = <String, String>{
      'client_utc_offset_minutes': utcOffsetMinutes.toString(),
    };
    if (zoneId != null && zoneId!.isNotEmpty) {
      params['client_timezone_id'] = zoneId!;
    }
    return params;
  }

  Map<String, dynamic> jsonFields() {
    final fields = <String, dynamic>{
      'client_utc_offset_minutes': utcOffsetMinutes,
    };
    if (zoneId != null && zoneId!.isNotEmpty) {
      fields['client_timezone_id'] = zoneId;
    }
    return fields;
  }
}

abstract class ClientTimezoneProvider {
  Future<ClientTimezoneContext> current();
}

class SystemClientTimezoneProvider implements ClientTimezoneProvider {
  const SystemClientTimezoneProvider();

  @override
  Future<ClientTimezoneContext> current() async {
    String? zoneId;
    try {
      zoneId = await FlutterTimezone.getLocalTimezone().timeout(
        const Duration(milliseconds: 500),
      );
    } catch (_) {
      zoneId = null;
    }
    return ClientTimezoneContext(
      zoneId: zoneId,
      utcOffsetMinutes: DateTime.now().timeZoneOffset.inMinutes,
    );
  }
}

class FixedClientTimezoneProvider implements ClientTimezoneProvider {
  const FixedClientTimezoneProvider(this.context);

  final ClientTimezoneContext context;

  @override
  Future<ClientTimezoneContext> current() async => context;
}
