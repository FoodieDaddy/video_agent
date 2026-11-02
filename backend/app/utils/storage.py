"""Media storage abstraction.

Local filesystem is the default (and what development/tests use).  S3/MinIO is
enabled through ``STORAGE_BACKEND=s3`` and is where production media lives; the
database only ever stores object keys, never binary blobs.
"""

from __future__ import annotations

import hashlib
import mimetypes
import shutil
from pathlib import Path

from app.core.settings import Settings


class StorageError(RuntimeError):
    pass


class LocalStorage:
    backend = "local"

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: str) -> Path:
        target = (self.root / key).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise StorageError(f"Storage key escapes root: {key}") from exc
        return target

    def save_bytes(self, key: str, content: bytes) -> str:
        target = self.path_for(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return key

    def read_bytes(self, key: str) -> bytes:
        return self.path_for(key).read_bytes()

    def open_path(self, key: str) -> Path:
        path = self.path_for(key)
        if not path.is_file():
            raise StorageError(f"Stored object missing: {key}")
        return path

    def exists(self, key: str) -> bool:
        return self.path_for(key).is_file()

    def delete(self, key: str) -> None:
        self.path_for(key).unlink(missing_ok=True)

    def copy_upload(self, source: Path, key: str) -> str:
        target = self.path_for(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return key


class S3Storage:
    """Minimal S3/MinIO adapter; requires ``boto3`` (optional dependency)."""

    backend = "s3"

    def __init__(self, bucket: str, endpoint_url: str | None = None, region: str | None = None) -> None:
        try:
            import boto3  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise StorageError("S3 storage requires the 's3' extra (pip install boto3)") from exc
        self.bucket = bucket
        self.client = boto3.client("s3", endpoint_url=endpoint_url, region_name=region)

    def save_bytes(self, key: str, content: bytes) -> str:
        mime = mimetypes.guess_type(key)[0] or "application/octet-stream"
        self.client.put_object(Bucket=self.bucket, Key=key, Body=content, ContentType=mime)
        return key

    def read_bytes(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def open_path(self, key: str) -> Path:  # pragma: no cover - production only
        import tempfile

        target = Path(tempfile.mkdtemp()) / Path(key).name
        target.write_bytes(self.read_bytes(key))
        return target

    def exists(self, key: str) -> bool:  # pragma: no cover
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def delete(self, key: str) -> None:  # pragma: no cover
        self.client.delete_object(Bucket=self.bucket, Key=key)


def build_storage(settings: Settings) -> LocalStorage | S3Storage:
    if settings.storage_backend == "s3":
        import os

        return S3Storage(
            bucket=os.getenv("S3_BUCKET", "ai-film-studio"),
            endpoint_url=os.getenv("S3_ENDPOINT_URL"),
            region=os.getenv("S3_REGION"),
        )
    return LocalStorage(settings.storage_root)


def checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def guess_mime(filename: str, default: str = "application/octet-stream") -> str:
    return mimetypes.guess_type(filename)[0] or default


def extension_for_mime(mime: str, default: str = "bin") -> str:
    return mimetypes.guess_extension(mime or "") or default
