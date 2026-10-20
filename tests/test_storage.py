"""File storage: keys are built by us, and nothing can be written or read outside the storage folder."""
import uuid

import pytest

from freight_intel.storage import LocalStorage

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
