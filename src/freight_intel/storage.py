"""Where uploaded files are kept.

Two backends with the same four methods, so the callers (routes, services, the pipeline) do not care which one runs:
  LocalStorage  a folder on disk (your laptop, the tests, Docker Compose)
  S3Storage     an S3 bucket (AWS: containers are replaced at any time, so files must live outside them)

The caller never chooses a path: it gets a storage KEY that we build ourselves, so a hostile filename
such as "../../etc/passwd" can never decide where a file goes.
"""
import tempfile
import uuid
from functools import lru_cache
from pathlib import Path


def build_key(tenant_id: uuid.UUID, document_id: uuid.UUID, extension: str) -> str:
    """One folder per company: <tenant>/<document>.<ext>. Built from ids and a checked extension only."""
    return f"{tenant_id}/{document_id}{extension}"


class LocalStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    key_for = staticmethod(build_key)

    def path(self, key: str) -> Path:
        """The real file path for a key (the pipeline needs one). Refuses anything outside the storage folder."""
        resolved = (self.root / key).resolve()
        if self.root not in resolved.parents:
            raise ValueError("storage key points outside the storage folder")
        return resolved

    def save(self, key: str, data: bytes) -> None:
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)


class S3Storage:
    """Files live in an S3 bucket. The pipeline needs a real file on disk, so path() downloads one copy into a
    temporary folder and reuses it. That folder is only a cache: the bucket is the truth.

    The S3 client is a parameter so tests can pass a fake. When none is given, boto3 is imported on first use
    and finds its credentials by itself (on AWS: the container's IAM role, so no key is ever stored in the app).
    """

    def __init__(self, bucket: str, *, client=None, cache_dir: str | Path | None = None, region: str | None = None):
        self.bucket = bucket
        self._client = client
        self._region = region
        # A LocalStorage over the cache folder gives us its "refuse a key that escapes" check for free.
        self._cache = LocalStorage(cache_dir or Path(tempfile.gettempdir()) / "freightlens-s3-cache")

    key_for = staticmethod(build_key)

    @property
    def client(self):
        if self._client is None:
            import boto3  # imported here so laptops and tests that never use S3 do not need it

            self._client = boto3.client("s3", region_name=self._region)
        return self._client

    def path(self, key: str) -> Path:
        """A real local file for a key: downloaded once, then reused. Keeps the extension, which the parser needs."""
        local = self._cache.path(key)
        if not local.exists():
            local.parent.mkdir(parents=True, exist_ok=True)
            partial = local.with_name(f"{local.name}.{uuid.uuid4().hex}.part")
            self.client.download_file(self.bucket, key, str(partial))
            partial.replace(local)  # rename is all-or-nothing: a half-downloaded file is never mistaken for the real one
        return local

    def save(self, key: str, data: bytes) -> None:
        self._cache.path(key)  # refuses a key that would escape, before anything is uploaded
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)

    def delete(self, key: str) -> None:
        self._cache.delete(key)
        self.client.delete_object(Bucket=self.bucket, Key=key)  # S3 does not complain about a missing key


@lru_cache
def get_storage() -> LocalStorage | S3Storage:
    """One storage object for the whole process. Routes ask for it with Depends(get_storage), so tests can swap it."""
    from freight_intel.config import get_settings  # imported here so the classes themselves need no settings

    settings = get_settings()
    if settings.storage_backend == "s3":
        if not settings.s3_bucket:
            raise ValueError("STORAGE_BACKEND=s3 needs S3_BUCKET to be set")
        return S3Storage(settings.s3_bucket, region=settings.aws_region)
    if settings.storage_backend != "local":
        raise ValueError(f"unknown STORAGE_BACKEND {settings.storage_backend!r} (use 'local' or 's3')")
    return LocalStorage(settings.storage_dir)
