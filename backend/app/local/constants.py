PROVIDER_LOCAL_DEVICE = "local_device"

POLICY_METADATA_ONLY = "metadata_only"
POLICY_INDEX_TEXT = "index_text"
POLICY_UPLOAD_COPY = "upload_copy"

LOCAL_POLICIES = frozenset(
    {POLICY_METADATA_ONLY, POLICY_INDEX_TEXT, POLICY_UPLOAD_COPY}
)
DEFAULT_LOCAL_POLICY = POLICY_METADATA_ONLY

MAX_SCAN_DEPTH = 8
MAX_SCAN_SUPPORTED_ITEMS = 200
MAX_SCAN_INSPECTION_ITEMS = 2000
MAX_REPORT_BATCH = 100
MAX_DATASET_QUERY_ROWS = 50
CHEAP_HASH_MAX_BYTES = 256 * 1024
MAX_TEXT_WINDOW_BYTES = 8000
MAX_CSV_STATS_SAMPLE_ROWS = 5000
HASH_CHUNK_BYTES = 64 * 1024

DATASET_SUFFIXES = frozenset({".csv", ".parquet"})
DOCUMENT_SUFFIXES = frozenset(
    {
        ".txt",
        ".md",
        ".pdf",
        ".docx",
        ".xlsx",
        ".pptx",
        ".odt",
        ".ods",
        ".odp",
    }
)
TEXT_SUFFIXES = DOCUMENT_SUFFIXES
SUPPORTED_LOCAL_SUFFIXES = DATASET_SUFFIXES | DOCUMENT_SUFFIXES

PERSONAL_URI_PREFIX = "personal://device/"


def build_personal_file_uri(device_key: str, object_id: str) -> str:
    return f"{PERSONAL_URI_PREFIX}{device_key}/file/{object_id}"


def build_local_logical_path(root_path: str, relative_path: str) -> str:
    from app.local.paths import normalize_relative_path

    root_norm = normalize_relative_path(root_path)
    rel_norm = normalize_relative_path(relative_path)
    return f"{root_norm}/{rel_norm}"


def build_local_external_id(device_key: str, root_path: str, relative_path: str) -> str:
    return f"{device_key}:{build_local_logical_path(root_path, relative_path)}"


def infer_local_kind(suffix: str) -> str:
    lowered = suffix.lower()
    if lowered in DATASET_SUFFIXES:
        return "dataset"
    if lowered in DOCUMENT_SUFFIXES:
        return "document"
    return "file"
