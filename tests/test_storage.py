"""File storage: keys are built by us, and nothing can be written or read outside the storage folder."""
import uuid
from pathlib import Path

import pytest

from freight_intel.storage import LocalStorage, S3Storage, get_storage

TENANT, DOCUMENT = uuid.uuid4(), uuid.uuid4()


def test_key_has_one_folder_per_company():
    assert LocalStorage.key_for(TENANT, DOCUMENT, ".pdf") == f"{TENANT}/{DOCUMENT}.pdf"


def test_a_saved_file_can_be_found_again_by_its_key(tmp_path):
    storage = LocalStorage(tmp_path)
    key = LocalStorage.key_for(TENANT, DOCUMENT, ".pdf")
    storage.save(key, b"%PDF-1.4 hello")
    assert storage.path(key).read_bytes() == b"%PDF-1.4 hello"
    assert storage.path(key).parent.name == str(TENANT)


@pytest.mark.parametrize("key", ["../outside.pdf", "a/../../outside.pdf", "/etc/passwd", f"{TENANT}/../../x"])
def test_keys_that_escape_the_storage_folder_are_refused(tmp_path, key):
    storage = LocalStorage(tmp_path / "files")
    with pytest.raises(ValueError, match="outside"):
        storage.path(key)
    with pytest.raises(ValueError, match="outside"):
        storage.save(key, b"x")
    assert not (tmp_path / "outside.pdf").exists()


def test_delete_removes_the_file_and_is_safe_to_repeat(tmp_path):
    storage = LocalStorage(tmp_path)
    key = LocalStorage.key_for(TENANT, DOCUMENT, ".xlsx")
    storage.save(key, b"PK\x03\x04")
    storage.delete(key)
    assert not storage.path(key).exists()
    storage.delete(key)  # already gone: no error


# --- the S3 backend, tested with a pretend S3 (no AWS account, no boto3) -------------------------------------------


class FakeS3:
    """Just enough of the boto3 S3 client for these tests: the bucket is a dictionary."""

    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}
        self.downloads = 0

    def put_object(self, *, Bucket, Key, Body):
        self.objects[(Bucket, Key)] = Body

    def download_file(self, Bucket, Key, Filename):
        self.downloads += 1
        Path(Filename).write_bytes(self.objects[(Bucket, Key)])

    def delete_object(self, *, Bucket, Key):
        self.objects.pop((Bucket, Key), None)


@pytest.fixture
def s3(tmp_path):
    fake = FakeS3()
    return fake, S3Storage("demo-bucket", client=fake, cache_dir=tmp_path / "cache")


def test_s3_builds_the_same_keys_as_local():
    assert S3Storage.key_for(TENANT, DOCUMENT, ".pdf") == LocalStorage.key_for(TENANT, DOCUMENT, ".pdf")


def test_s3_save_uploads_the_bytes_under_the_key(s3):
    fake, storage = s3
    key = S3Storage.key_for(TENANT, DOCUMENT, ".pdf")
    storage.save(key, b"%PDF-1.4 hello")
    assert fake.objects == {("demo-bucket", key): b"%PDF-1.4 hello"}


def test_s3_path_downloads_once_and_keeps_the_extension(s3):
    fake, storage = s3
    key = S3Storage.key_for(TENANT, DOCUMENT, ".xlsx")
    storage.save(key, b"PK\x03\x04")
    first = storage.path(key)
    second = storage.path(key)
    assert first == second and first.suffix == ".xlsx"  # the parser chooses how to read a file by its extension
    assert first.read_bytes() == b"PK\x03\x04"
    assert fake.downloads == 1  # the second call reused the downloaded copy
    assert not list(first.parent.glob("*.part"))  # no half-downloaded leftovers


@pytest.mark.parametrize("key", ["../outside.pdf", "a/../../outside.pdf", "/etc/passwd", f"{TENANT}/../../x"])
def test_s3_keys_that_escape_the_cache_folder_are_refused(s3, key):
    fake, storage = s3
    with pytest.raises(ValueError, match="outside"):
        storage.path(key)
    with pytest.raises(ValueError, match="outside"):
        storage.save(key, b"x")
    assert fake.objects == {} and fake.downloads == 0  # nothing was uploaded or downloaded


def test_s3_delete_removes_the_object_and_the_cached_copy_and_is_safe_to_repeat(s3):
    fake, storage = s3
    key = S3Storage.key_for(TENANT, DOCUMENT, ".pdf")
    storage.save(key, b"x")
    cached = storage.path(key)
    storage.delete(key)
    assert fake.objects == {} and not cached.exists()
    storage.delete(key)  # already gone: no error


# --- choosing the backend from settings ------------------------------------------------------------------------------


@pytest.fixture
def settings_env(monkeypatch):
    """Lets a test set STORAGE_BACKEND and friends, and makes sure no cached settings or storage leak in or out."""
    from freight_intel.config import get_settings

    get_settings.cache_clear()
    get_storage.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()
    get_storage.cache_clear()


def test_the_default_backend_is_the_local_folder(settings_env):
    settings_env.delenv("STORAGE_BACKEND", raising=False)
    assert isinstance(get_storage(), LocalStorage)


def test_the_s3_backend_is_chosen_by_settings(settings_env):
    settings_env.setenv("STORAGE_BACKEND", "s3")
    settings_env.setenv("S3_BUCKET", "demo-bucket")
    storage = get_storage()
    assert isinstance(storage, S3Storage) and storage.bucket == "demo-bucket"


def test_s3_without_a_bucket_is_refused(settings_env):
    settings_env.setenv("STORAGE_BACKEND", "s3")
    settings_env.delenv("S3_BUCKET", raising=False)
    with pytest.raises(ValueError, match="S3_BUCKET"):
        get_storage()


def test_an_unknown_backend_is_refused(settings_env):
    settings_env.setenv("STORAGE_BACKEND", "floppy-disk")
    with pytest.raises(ValueError, match="unknown STORAGE_BACKEND"):
        get_storage()
