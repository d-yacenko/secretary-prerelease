/// Sanitize extractor-internal metadata before client intake wire requests.
library;

const _allowedMetadataKeys = {
  'source_chunk_index',
  'truncated',
  'page_count',
  'page_truncated',
  'slide_count',
  'sheet_count',
  'dataset_row_count',
  'dataset_rows_represented',
  'dataset_sampling_mode',
  'dataset_sampling_truncated',
  'sampled_row_indices',
  'row_count_in_sample',
  'compact_preview',
  'row_count',
  'rows_sampled',
  'column_count',
  'stats_truncated',
};

const _internalOnlyMetadataKeys = {
  'columns',
};

const _allowedSamplingModes = {'full', 'distributed'};
const _maxSampledRowIndices = 64;

List<Map<String, dynamic>> sanitizeClientRepresentations(
  List<Map<String, dynamic>> representations,
) {
  return [
    for (final rep in representations) _sanitizeRepresentation(rep),
  ];
}

Map<String, dynamic> _sanitizeRepresentation(Map<String, dynamic> rep) {
  final sanitized = Map<String, dynamic>.from(rep);
  final metadata = rep['metadata'];
  if (metadata is Map) {
    sanitized['metadata'] = sanitizeClientMetadata(
      Map<String, dynamic>.from(metadata),
    );
  } else if (metadata != null) {
    sanitized.remove('metadata');
  }
  return sanitized;
}

Map<String, dynamic> sanitizeClientMetadata(Map<String, dynamic> metadata) {
  final sanitized = <String, dynamic>{};
  for (final entry in metadata.entries) {
    if (_internalOnlyMetadataKeys.contains(entry.key)) {
      continue;
    }
    if (!_allowedMetadataKeys.contains(entry.key)) {
      continue;
    }
    final normalized = _normalizeMetadataValue(entry.key, entry.value);
    if (normalized == null) {
      continue;
    }
    sanitized[entry.key] = normalized;
  }
  return sanitized;
}

dynamic _normalizeMetadataValue(String key, dynamic value) {
  switch (key) {
    case 'truncated':
    case 'page_truncated':
    case 'compact_preview':
    case 'dataset_sampling_truncated':
    case 'stats_truncated':
      if (value is! bool) {
        return null;
      }
      if (key == 'truncated' && value == false) {
        return null;
      }
      return value;
    case 'dataset_sampling_mode':
      if (value is! String || !_allowedSamplingModes.contains(value)) {
        return null;
      }
      return value;
    case 'sampled_row_indices':
      if (value is! List) {
        return null;
      }
      final indices = <int>{};
      for (final item in value) {
        if (item is! int || item < 0) {
          return null;
        }
        indices.add(item);
      }
      final sorted = indices.toList()..sort();
      if (sorted.length > _maxSampledRowIndices) {
        return sorted.take(_maxSampledRowIndices).toList();
      }
      return sorted;
    case 'source_chunk_index':
    case 'page_count':
    case 'slide_count':
    case 'sheet_count':
    case 'dataset_row_count':
    case 'dataset_rows_represented':
    case 'row_count_in_sample':
    case 'row_count':
    case 'rows_sampled':
    case 'column_count':
      if (value is! int || value < 0) {
        return null;
      }
      return value;
    default:
      return null;
  }
}
