import csv
import hashlib
import os
import uuid
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from app.local.constants import (
    CHEAP_HASH_MAX_BYTES,
    HASH_CHUNK_BYTES,
    MAX_CSV_STATS_SAMPLE_ROWS,
    MAX_TEXT_WINDOW_BYTES,
)


def stream_content_hash(path: Path, max_bytes: int = CHEAP_HASH_MAX_BYTES) -> str | None:
    size = path.stat().st_size
    if size > max_bytes:
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(HASH_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def stream_file_to_hashed_path(
    source_path: Path,
    target_dir: Path,
    suffix: str,
) -> tuple[Path, str, bool]:
    """Copy source to upload dir using streaming SHA-256; filename is hash + suffix."""
    target_dir.mkdir(parents=True, exist_ok=True)
    temp_path = target_dir / f".copy-{uuid.uuid4().hex}{suffix}"
    digest = hashlib.sha256()
    try:
        with source_path.open("rb") as src, temp_path.open("wb") as dst:
            while True:
                chunk = src.read(HASH_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
                dst.write(chunk)
            dst.flush()
            os.fsync(dst.fileno())
        content_hash = digest.hexdigest()
        final_path = target_dir / f"{content_hash}{suffix}"
        if final_path.is_file():
            temp_path.unlink(missing_ok=True)
            return final_path, content_hash, False
        temp_path.replace(final_path)
        return final_path, content_hash, True
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def read_bounded_text(path: Path) -> tuple[str, dict[str, Any]]:
    size = path.stat().st_size
    if size <= MAX_TEXT_WINDOW_BYTES:
        with path.open("rb") as handle:
            data = handle.read(size)
        text = data.decode("utf-8", errors="replace")
        return text, {
            "truncated": False,
            "sampled": False,
            "source_bytes": size,
        }

    offsets = [0]
    if size > MAX_TEXT_WINDOW_BYTES:
        mid = max(0, (size // 2) - (MAX_TEXT_WINDOW_BYTES // 2))
        offsets.append(mid)
        offsets.append(max(0, size - MAX_TEXT_WINDOW_BYTES))

    windows: list[str] = []
    with path.open("rb") as handle:
        for offset in offsets:
            handle.seek(offset)
            chunk = handle.read(MAX_TEXT_WINDOW_BYTES)
            windows.append(chunk.decode("utf-8", errors="replace"))

    text = "\n...\n".join(windows)
    return text, {
        "truncated": True,
        "sampled": True,
        "source_bytes": size,
        "window_count": len(windows),
    }


def read_csv_header(path: Path) -> list[str]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or [])


def read_csv_sample_rows(path: Path, limit: int) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows: list[dict[str, str]] = []
        for index, row in enumerate(reader):
            if index >= limit:
                break
            rows.append(row)
        return fieldnames, rows


def stream_csv_stats(
    path: Path,
    fieldnames: list[str],
    max_rows: int = MAX_CSV_STATS_SAMPLE_ROWS,
) -> tuple[dict[str, Any], list[str], dict[str, str]]:
    column_types = {name: "string" for name in fieldnames}
    numeric_values: dict[str, list[float]] = {name: [] for name in fieldnames}
    rows_seen = 0
    truncated = False

    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows_seen += 1
            if rows_seen > max_rows:
                truncated = True
                break
            for name in fieldnames:
                value = row.get(name, "")
                if not value:
                    continue
                if _looks_int(value):
                    if column_types[name] == "string":
                        column_types[name] = "integer"
                elif _looks_float(value) and column_types[name] != "integer":
                    column_types[name] = "float"
                try:
                    numeric_values[name].append(float(value))
                except ValueError:
                    continue

    stats_meta: dict[str, Any] = {
        "row_count": rows_seen if not truncated else None,
        "rows_sampled": min(rows_seen, max_rows),
        "column_count": len(fieldnames),
        "stats_truncated": truncated,
        "columns": {},
    }
    lines = [
        f"rows: {rows_seen if not truncated else 'unknown (sampled)'}",
        f"columns: {len(fieldnames)}",
    ]
    if truncated:
        lines.append(f"rows_sampled: {max_rows}")

    for name in fieldnames:
        numbers = numeric_values[name]
        if not numbers:
            continue
        col_stats = {
            "min": min(numbers),
            "max": max(numbers),
            "mean": sum(numbers) / len(numbers),
            "sampled": truncated,
        }
        stats_meta["columns"][name] = col_stats
        lines.append(
            f"{name}: min={col_stats['min']}, max={col_stats['max']}, mean={col_stats['mean']}"
        )

    return stats_meta, lines, column_types


def read_parquet_schema(path: Path) -> tuple[list[str], dict[str, str], int]:
    parquet_file = pq.ParquetFile(path)
    schema = parquet_file.schema_arrow
    fieldnames = schema.names
    column_types = {name: str(schema.field(name).type) for name in fieldnames}
    row_count = parquet_file.metadata.num_rows if parquet_file.metadata else 0
    return fieldnames, column_types, row_count


def read_parquet_sample_rows(
    path: Path,
    limit: int,
) -> tuple[list[str], list[dict[str, Any]]]:
    parquet_file = pq.ParquetFile(path)
    fieldnames = parquet_file.schema_arrow.names
    rows: list[dict[str, Any]] = []
    for batch in parquet_file.iter_batches(batch_size=min(limit, 1024)):
        batch_rows = batch.to_pylist()
        for row in batch_rows:
            if len(rows) >= limit:
                return fieldnames, rows
            rows.append(row)
    return fieldnames, rows


def bounded_parquet_stats(
    path: Path,
    fieldnames: list[str],
    column_types: dict[str, str],
    row_count: int,
    max_rows: int = MAX_CSV_STATS_SAMPLE_ROWS,
) -> tuple[dict[str, Any], list[str]]:
    parquet_file = pq.ParquetFile(path)
    numeric_sums: dict[str, float] = {}
    numeric_counts: dict[str, int] = {}
    numeric_min: dict[str, float] = {}
    numeric_max: dict[str, float] = {}
    rows_sampled = 0
    truncated = row_count > max_rows

    for batch in parquet_file.iter_batches(batch_size=1024):
        for row in batch.to_pylist():
            rows_sampled += 1
            if rows_sampled > max_rows:
                truncated = True
                break
            for name in fieldnames:
                value = row.get(name)
                if value is None:
                    continue
                col_type = column_types.get(name, "")
                if "int" not in col_type and "float" not in col_type and "double" not in col_type:
                    continue
                number = float(value)
                numeric_sums[name] = numeric_sums.get(name, 0.0) + number
                numeric_counts[name] = numeric_counts.get(name, 0) + 1
                numeric_min[name] = min(numeric_min.get(name, number), number)
                numeric_max[name] = max(numeric_max.get(name, number), number)
        if truncated:
            break

    stats_meta: dict[str, Any] = {
        "row_count": row_count,
        "rows_sampled": min(rows_sampled, max_rows),
        "column_count": len(fieldnames),
        "stats_truncated": truncated,
        "columns": {},
    }
    lines = [f"rows: {row_count}", f"columns: {len(fieldnames)}"]
    if truncated:
        lines.append(f"rows_sampled: {min(rows_sampled, max_rows)}")

    for name in fieldnames:
        if name not in numeric_counts:
            continue
        count = numeric_counts[name]
        col_stats = {
            "min": numeric_min[name],
            "max": numeric_max[name],
            "mean": numeric_sums[name] / count,
            "sampled": truncated,
        }
        stats_meta["columns"][name] = col_stats
        lines.append(
            f"{name}: min={col_stats['min']}, max={col_stats['max']}, mean={col_stats['mean']}"
        )

    return stats_meta, lines


def count_csv_rows(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return sum(1 for _ in reader)


def read_csv_indexed_rows(
    path: Path,
    fieldnames: list[str],
    indices: list[int],
) -> list[tuple[int, dict[str, str]]]:
    if not indices:
        return []
    wanted = set(indices)
    max_index = max(indices)
    rows: dict[int, dict[str, str]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_index, row in enumerate(reader):
            if row_index in wanted:
                rows[row_index] = row
            if row_index >= max_index and len(rows) == len(wanted):
                break
    return [(index, rows[index]) for index in indices if index in rows]


def read_csv_rows_at_indices(
    path: Path,
    fieldnames: list[str],
    indices: list[int],
) -> list[dict[str, str]]:
    return [row for _, row in read_csv_indexed_rows(path, fieldnames, indices)]


def _parquet_row_group_bounds(parquet_file: pq.ParquetFile) -> list[tuple[int, int]]:
    metadata = parquet_file.metadata
    if metadata is None:
        return []
    bounds: list[tuple[int, int]] = []
    offset = 0
    for group_index in range(metadata.num_row_groups):
        row_count = metadata.row_group(group_index).num_rows
        bounds.append((offset, offset + row_count))
        offset += row_count
    return bounds


def _parquet_row_group_for_index(bounds: list[tuple[int, int]], global_index: int) -> tuple[int, int] | None:
    for group_index, (start, end) in enumerate(bounds):
        if start <= global_index < end:
            return group_index, global_index - start
    return None


def read_parquet_indexed_rows(
    path: Path,
    indices: list[int],
) -> tuple[list[str], list[tuple[int, dict[str, Any]]]]:
    parquet_file = pq.ParquetFile(path)
    fieldnames = list(parquet_file.schema_arrow.names)
    if not indices:
        return fieldnames, []

    bounds = _parquet_row_group_bounds(parquet_file)
    wanted = sorted(set(indices))
    by_group: dict[int, list[int]] = {}
    for global_index in wanted:
        located = _parquet_row_group_for_index(bounds, global_index)
        if located is None:
            continue
        group_index, local_index = located
        by_group.setdefault(group_index, []).append(local_index)

    rows: dict[int, dict[str, Any]] = {}
    for group_index, local_indices in by_group.items():
        table = parquet_file.read_row_group(group_index)
        group_rows = table.to_pylist()
        group_start = bounds[group_index][0]
        for local_index in local_indices:
            rows[group_start + local_index] = group_rows[local_index]

    return fieldnames, [(index, rows[index]) for index in indices if index in rows]


def read_parquet_rows_at_indices(
    path: Path,
    indices: list[int],
) -> tuple[list[str], list[dict[str, Any]]]:
    fieldnames, indexed_rows = read_parquet_indexed_rows(path, indices)
    return fieldnames, [row for _, row in indexed_rows]


def query_csv_columns(path: Path, columns: list[str], limit: int) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        available = set(reader.fieldnames or [])
        for name in columns:
            if name not in available:
                raise ValueError(f"column not found: {name}")
        rows: list[dict[str, Any]] = []
        for index, row in enumerate(reader):
            if index >= limit:
                break
            rows.append({name: row.get(name, "") for name in columns})
        return rows


def query_parquet_columns(path: Path, columns: list[str], limit: int) -> list[dict[str, Any]]:
    parquet_file = pq.ParquetFile(path)
    available = set(parquet_file.schema_arrow.names)
    for name in columns:
        if name not in available:
            raise ValueError(f"column not found: {name}")

    rows: list[dict[str, Any]] = []
    for batch in parquet_file.iter_batches(batch_size=min(limit, 1024), columns=columns):
        for row in batch.to_pylist():
            if len(rows) >= limit:
                return rows
            rows.append(row)
    return rows


def _looks_int(value: str) -> bool:
    try:
        int(value)
        return True
    except ValueError:
        return False


def _looks_float(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False
