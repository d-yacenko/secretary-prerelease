"""PHASE 29A — centralized bounded content extraction policy."""

from app.services.client_intake_constants import (
    MAX_CLIENT_REPRESENTATION_PART_BYTES,
    MAX_CLIENT_REPRESENTATION_PARTS,
    MAX_CLIENT_REPRESENTATION_TOTAL_BYTES,
)

# Reuse client representation limits for persisted mechanical text.
MAX_REPRESENTATION_PARTS = MAX_CLIENT_REPRESENTATION_PARTS
MAX_REPRESENTATION_PART_BYTES = MAX_CLIENT_REPRESENTATION_PART_BYTES
MAX_REPRESENTATION_TOTAL_BYTES = MAX_CLIENT_REPRESENTATION_TOTAL_BYTES

MAX_EXPLICIT_CLOUD_DOWNLOAD_BYTES = 20 * 1024 * 1024

# Parser-specific bounds
MAX_PDF_PAGES = 50
MAX_EXTRACTED_TEXT_CHARS = 512_000
MAX_OOXML_ZIP_ENTRIES = 512
MAX_OOXML_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
MAX_OOXML_COMPRESSION_RATIO = 200
MAX_XLSX_SHEETS = 16
MAX_XLSX_ROWS_PER_SHEET = 200
MAX_XLSX_COLUMNS = 64
MAX_PPTX_SLIDES = 40
MAX_ODF_SHEETS = 16
MAX_ODF_ROWS_PER_SHEET = 200
MAX_ODF_COLUMNS = 64
MAX_ODF_REPEAT_EXPANSION = 64
MAX_ODP_SLIDES = 40

SUPPORTED_BINARY_SUFFIXES = frozenset(
    {
        ".txt",
        ".md",
        ".csv",
        ".pdf",
        ".docx",
        ".xlsx",
        ".pptx",
        ".odt",
        ".ods",
        ".odp",
        ".parquet",
    }
)

TEXT_SUFFIXES = frozenset({".txt", ".md"})
DATASET_SUFFIXES = frozenset({".csv", ".parquet"})
OFFICE_SUFFIXES = frozenset({".docx", ".xlsx", ".pptx"})
ODF_SUFFIXES = frozenset({".odt", ".ods", ".odp"})

DATASET_STRUCTURAL_PARTS = 3

EXTRACTION_VERSION = "format-parity-a-v1"
