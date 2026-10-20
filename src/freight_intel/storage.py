"""Where uploaded files are kept.

Today a folder on disk; at deploy time the same four methods can be backed by S3 without touching the callers.
The caller never chooses a path: it gets a storage KEY that we build ourselves, so a hostile filename
such as "../../etc/passwd" can never decide where a file goes.
"""
import uuid
from functools import lru_cache
from pathlib import Path


class LocalStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    @staticmethod
    def key_for(tenant_id: uuid.UUID, document_id: uuid.UUID, extension: str) -> str:
        """One folder per company: <tenant>/<document>.<ext>. Built from ids and a checked extension only."""
        return f"{tenant_id}/{document_id}{extension}"

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


@lru_cache
def get_storage() -> LocalStorage:
    """One storage object for the whole process. Routes ask for it with Depends(get_storage), so tests can swap it."""
    from freight_intel.config import get_settings  # imported here so LocalStorage itself needs no settings

    return LocalStorage(get_settings().storage_dir)
