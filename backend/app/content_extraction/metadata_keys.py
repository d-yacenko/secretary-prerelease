"""Object.metadata keys for PHASE 29A content extraction state."""

CONTENT_EXTRACTION_STATUS = "content_extraction_status"
CONTENT_EXTRACTION_VERSION = "content_extraction_version"
CONTENT_EXTRACTED_AT = "content_extracted_at"
CONTENT_FORMAT = "content_format"
CONTENT_TRUNCATED = "content_truncated"
CONTENT_SOURCE_BYTES = "content_source_bytes"
CONTENT_EXTRACTED_CHARS = "content_extracted_chars"
MECHANICAL_REPRESENTATION_COUNT = "mechanical_representation_count"
CONTENT_EXTRACTION_ERROR = "content_extraction_error"

DATASET_ROW_COUNT = "dataset_row_count"
DATASET_ROWS_REPRESENTED = "dataset_rows_represented"
DATASET_SAMPLING_MODE = "dataset_sampling_mode"
DATASET_SAMPLING_TRUNCATED = "dataset_sampling_truncated"
DATASET_SAMPLED_ROW_INDICES = "sampled_row_indices"

STATUS_PENDING = "pending"
STATUS_READY = "ready"
STATUS_METADATA_ONLY = "metadata_only"
STATUS_UNSUPPORTED = "unsupported"
STATUS_TOO_LARGE = "too_large"
STATUS_FAILED = "failed"

MECHANICAL_REPRESENTATION_KINDS = frozenset(
    {"full", "chunk", "schema", "sample", "statistics"}
)
