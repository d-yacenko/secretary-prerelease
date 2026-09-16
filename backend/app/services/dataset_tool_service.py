from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Object, Representation
from app.local.bounded_io import (
    bounded_parquet_stats,
    query_csv_columns,
    query_parquet_columns,
    read_csv_header,
    read_csv_sample_rows,
    read_parquet_sample_rows,
    read_parquet_schema,
    stream_csv_stats,
)
from app.local.constants import MAX_DATASET_QUERY_ROWS, PROVIDER_LOCAL_DEVICE
from app.local.errors import LocalFileError
from app.local.paths import LocalPathResolver
from app.resources.upload_paths import validate_object_upload_path
from app.services.errors import NotFoundError, ValidationError
from app.services.representation_service import (
    KIND_SAMPLE,
    KIND_SCHEMA,
    KIND_STATISTICS,
)


class DatasetToolService:
    def __init__(
        self,
        session: Session,
        user_id: UUID,
        path_resolver: LocalPathResolver,
        upload_root: Path | None = None,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._path_resolver = path_resolver
        self._upload_root = upload_root

    def get_schema(self, object_id: UUID) -> dict:
        obj = self._get_dataset_object(object_id)
        rep = self._find_representation(obj.id, KIND_SCHEMA)
        if rep is not None and rep.text:
            return {
                "object_id": str(object_id),
                "schema_text": rep.text,
                "columns": (rep.metadata_ or {}).get("columns", []),
            }
        path = self._resolve_dataset_path(obj)
        return self._read_schema_from_path(path, object_id)

    def get_sample(self, object_id: UUID, limit: int = 5) -> dict:
        if limit < 1 or limit > MAX_DATASET_QUERY_ROWS:
            raise ValidationError("sample limit out of bounds")
        obj = self._get_dataset_object(object_id)
        rep = self._find_representation(obj.id, KIND_SAMPLE)
        if rep is not None and rep.text:
            return {
                "object_id": str(object_id),
                "sample_text": rep.text,
                "row_count_in_sample": (rep.metadata_ or {}).get("row_count_in_sample", 0),
            }
        path = self._resolve_dataset_path(obj)
        return self._read_sample_from_path(path, object_id, limit)

    def get_basic_stats(self, object_id: UUID) -> dict:
        obj = self._get_dataset_object(object_id)
        rep = self._find_representation(obj.id, KIND_STATISTICS)
        if rep is not None and rep.text:
            return {
                "object_id": str(object_id),
                "statistics_text": rep.text,
                "statistics": rep.metadata_ or {},
            }
        path = self._resolve_dataset_path(obj)
        return self._read_stats_from_path(path, object_id)

    def query_columns(
        self,
        object_id: UUID,
        columns: list[str],
        limit: int = 20,
    ) -> dict:
        if not columns:
            raise ValidationError("columns must not be empty")
        if limit < 1 or limit > MAX_DATASET_QUERY_ROWS:
            raise ValidationError("query limit out of bounds")
        obj = self._get_dataset_object(object_id)
        path = self._resolve_dataset_path(obj)
        suffix = path.suffix.lower()
        try:
            if suffix == ".csv":
                rows = query_csv_columns(path, columns, limit)
            elif suffix == ".parquet":
                rows = query_parquet_columns(path, columns, limit)
            else:
                raise ValidationError(f"unsupported dataset format: {suffix}")
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        return {
            "object_id": str(object_id),
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
        }

    def _get_dataset_object(self, object_id: UUID) -> Object:
        obj = self._session.scalar(
            select(Object).where(Object.id == object_id, Object.user_id == self._user_id)
        )
        if obj is None:
            raise NotFoundError("object", object_id)
        if obj.kind != "dataset":
            raise ValidationError("dataset tools require kind=dataset")
        return obj

    def _find_representation(self, object_id: UUID, kind: str) -> Representation | None:
        return self._session.scalar(
            select(Representation).where(
                Representation.object_id == object_id,
                Representation.kind == kind,
            )
        )

    def _resolve_dataset_path(self, obj: Object) -> Path:
        metadata = obj.metadata_ or {}
        upload_path = metadata.get("upload_path")
        if upload_path and self._upload_root is not None:
            return validate_object_upload_path(
                self._upload_root,
                self._user_id,
                obj.id,
                str(upload_path),
            )
        if obj.provider == PROVIDER_LOCAL_DEVICE:
            return self._resolve_local_object_path(obj)
        raise LocalFileError("dataset source file is not available")

    def _resolve_local_object_path(self, obj: Object) -> Path:
        metadata = obj.metadata_ or {}
        device_key = metadata.get("device_key")
        root_path = metadata.get("local_root_path")
        relative_path = metadata.get("local_relative_path")
        if not device_key or not root_path or not relative_path:
            raise LocalFileError("object is missing local path metadata")
        return self._path_resolver.resolve_file_path(
            self._user_id,
            str(device_key),
            str(root_path),
            str(relative_path),
        )

    def _read_schema_from_path(self, path: Path, object_id: UUID) -> dict:
        suffix = path.suffix.lower()
        if suffix == ".csv":
            fieldnames = read_csv_header(path)
            columns = [{"name": name, "type": "string"} for name in fieldnames]
            schema_text = "schema\n" + "\n".join(f"{name}: string" for name in fieldnames)
        elif suffix == ".parquet":
            fieldnames, column_types, _ = read_parquet_schema(path)
            columns = [{"name": name, "type": column_types[name]} for name in fieldnames]
            schema_text = "schema\n" + "\n".join(
                f"{name}: {column_types[name]}" for name in fieldnames
            )
        else:
            raise ValidationError(f"unsupported dataset format: {suffix}")
        return {
            "object_id": str(object_id),
            "schema_text": schema_text,
            "columns": columns,
        }

    def _read_sample_from_path(self, path: Path, object_id: UUID, limit: int) -> dict:
        suffix = path.suffix.lower()
        if suffix == ".csv":
            fieldnames, rows = read_csv_sample_rows(path, limit)
        elif suffix == ".parquet":
            fieldnames, rows = read_parquet_sample_rows(path, limit)
        else:
            raise ValidationError(f"unsupported dataset format: {suffix}")

        lines = ["sample", ",".join(fieldnames)]
        for row in rows:
            lines.append(",".join(str(row.get(name, "")) for name in fieldnames))
        return {
            "object_id": str(object_id),
            "sample_text": "\n".join(lines),
            "row_count_in_sample": len(rows),
        }

    def _read_stats_from_path(self, path: Path, object_id: UUID) -> dict:
        suffix = path.suffix.lower()
        if suffix == ".csv":
            fieldnames = read_csv_header(path)
            stats_meta, stats_lines, _ = stream_csv_stats(path, fieldnames)
        elif suffix == ".parquet":
            fieldnames, column_types, row_count = read_parquet_schema(path)
            stats_meta, stats_lines = bounded_parquet_stats(
                path, fieldnames, column_types, row_count
            )
        else:
            raise ValidationError(f"unsupported dataset format: {suffix}")
        return {
            "object_id": str(object_id),
            "statistics_text": "\n".join(stats_lines),
            "statistics": stats_meta,
        }
