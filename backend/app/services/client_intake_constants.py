"""PHASE 26B / Format Parity Pass B client-assisted intake bounds."""

CLIENT_REPRESENTATION_KINDS = frozenset(
    {"full", "chunk", "schema", "sample", "statistics"}
)

DOCUMENT_REPRESENTATION_KINDS = frozenset({"full", "chunk"})
DATASET_REPRESENTATION_KINDS = frozenset(
    {"schema", "sample", "statistics", "full", "chunk"}
)

# Representation-policy categories (not the same as canonical object kind).
DOCUMENT_LIKE_SUFFIXES = frozenset(
    {".txt", ".md", ".pdf", ".docx", ".pptx", ".odt", ".odp"}
)
DATASET_LIKE_SUFFIXES = frozenset(
    {".csv", ".xlsx", ".ods", ".parquet"}
)
LEGACY_METADATA_ONLY_SUFFIXES = frozenset({".doc", ".xls", ".ppt"})

TEXT_FILE_SUFFIXES = DOCUMENT_LIKE_SUFFIXES
DATASET_FILE_SUFFIXES = DATASET_LIKE_SUFFIXES
DOCUMENT_FILE_SUFFIXES = DOCUMENT_LIKE_SUFFIXES

CLIENT_INDEXABLE_SUFFIXES = DOCUMENT_LIKE_SUFFIXES | DATASET_LIKE_SUFFIXES

UNSUPPORTED_INDEX_SUFFIXES = frozenset(
    {
        ".zip",
        ".gz",
        ".tar",
        ".7z",
        ".rar",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".bmp",
        ".svg",
        ".ico",
    }
)

MAX_CLIENT_REPRESENTATION_PARTS = 64
MAX_CLIENT_REPRESENTATION_PART_BYTES = 16 * 1024
MAX_CLIENT_REPRESENTATION_TOTAL_BYTES = 256 * 1024
MAX_CLIENT_INTAKE_REQUEST_BYTES = 384 * 1024

CLIENT_REP_METADATA_ALLOWLIST = frozenset(
    {
        "source_chunk_index",
        "truncated",
        "page_count",
        "page_truncated",
        "slide_count",
        "sheet_count",
        "dataset_row_count",
        "dataset_rows_represented",
        "dataset_sampling_mode",
        "dataset_sampling_truncated",
        "sampled_row_indices",
        "row_count_in_sample",
        "compact_preview",
        "row_count",
        "rows_sampled",
        "column_count",
        "stats_truncated",
    }
)

ALLOWED_DATASET_SAMPLING_MODES = frozenset({"full", "distributed"})
MAX_SAMPLED_ROW_INDICES = 64

MAX_EMAIL_ATTACHMENTS_PER_MESSAGE = 20
MAX_EMAIL_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_EMAIL_ATTACHMENT_BYTES_PER_MESSAGE = 20 * 1024 * 1024

ATTACHMENT_TEXT_SUFFIXES = frozenset({".txt", ".md", ".csv"})
