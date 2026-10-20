"""Upload checks. The positive cases are the real generated documents, so the rules can't drift away from real files."""
import io
import zipfile

import pytest

from freight_intel.services.uploads import UploadRejected, check_upload, display_name
from freight_intel.synth.writer import write_dataset

MB = 1024 * 1024


@pytest.fixture(scope="module")
def real_files(tmp_path_factory):
    pytest.importorskip("reportlab")
    pytest.importorskip("openpyxl")
    out = tmp_path_factory.mktemp("dataset")
    write_dataset(45, 42, out)
    return sorted(f for f in (out / "cases").glob("*/*.*") if f.stem in ("quote", "invoice"))  # not truth.json


def rejected(filename, data, **kw) -> UploadRejected:
    with pytest.raises(UploadRejected) as info:
        check_upload(filename, data, max_bytes=kw.get("max_bytes", MB))
    return info.value


def make_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:  # compressed, like a real .xlsx
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_every_generated_document_is_accepted(real_files):
    kinds = set()
    for path in real_files:
        checked = check_upload(path.name, path.read_bytes(), max_bytes=10 * MB)
        assert checked.extension == path.suffix
        kinds.add(checked.extension)
    assert len(real_files) == 90 and kinds == {".pdf", ".xlsx", ".eml"}


def test_extension_is_case_insensitive_and_the_name_is_cleaned():
    checked = check_upload("  Q-1.PDF ", b"%PDF-1.4 x", max_bytes=MB)
    assert (checked.extension, checked.display_name) == (".pdf", "Q-1.PDF")


@pytest.mark.parametrize("raw, shown", [
    ("../../etc/passwd.pdf", "passwd.pdf"),
    ("C:\\Users\\bob\\invoice.pdf", "invoice.pdf"),
    ("a/b/c.pdf", "c.pdf"),
    ("bad\x00name\n.pdf", "badname.pdf"),
    ("x" * 500 + ".pdf", ("x" * 500 + ".pdf")[:200]),
])
def test_display_name_never_keeps_folders_or_control_characters(raw, shown):
    assert display_name(raw) == shown


@pytest.mark.parametrize("filename", [None, "", "   ", "/", ".pdf", "noextension"])
def test_missing_or_nameless_files_are_rejected(filename):
    assert rejected(filename, b"%PDF-1.4").code in ("missing_filename", "unsupported_type")


@pytest.mark.parametrize("filename", ["malware.exe", "invoice.pdf.exe", "notes.txt", "archive.zip", "page.html", "macro.xlsm"])
def test_other_types_are_rejected_by_extension(filename):
    assert rejected(filename, b"%PDF-1.4 anything").code == "unsupported_type"


def test_empty_and_oversized_files_are_rejected():
    assert rejected("a.pdf", b"").code == "empty"
    assert rejected("a.pdf", b"%PDF-" + b"0" * 1000, max_bytes=500).code == "too_large"
    check_upload("a.pdf", b"%PDF-" + b"0" * 495, max_bytes=500)  # exactly at the limit is fine


@pytest.mark.parametrize("filename, data", [
    ("renamed.pdf", b"MZ\x90\x00 this is a program"),
    ("renamed.xlsx", b"%PDF-1.4 this is a pdf"),
    ("renamed.eml", b"PK\x03\x04\x00\x00"),
    ("renamed.eml", b"From: a@b.c\x00\x01\x02 binary"),
    ("empty-ish.eml", b"just some text without headers"),
])
def test_content_must_match_the_extension(filename, data):
    assert rejected(filename, data).code == "content_mismatch"


def test_a_zip_that_is_not_a_workbook_is_rejected():
    assert rejected("fake.xlsx", make_zip({"readme.txt": b"hello"})).code == "content_mismatch"
    assert rejected("fake.xlsx", b"PK\x03\x04 broken").code == "content_mismatch"


def test_a_zip_that_unpacks_to_far_too_much_is_rejected():
    bomb = make_zip({"[Content_Types].xml": b"<x/>", "xl/workbook.xml": b"<x/>", "xl/big.bin": b"0" * (101 * MB)})
    assert len(bomb) < MB  # tiny to upload, huge to unpack
    assert rejected("bomb.xlsx", bomb, max_bytes=10 * MB).code == "content_mismatch"


def test_a_minimal_mail_message_is_accepted():
    check_upload("m.eml", b"Subject: Quote Q-1\r\nTo: x@y.z\r\n\r\nbody", max_bytes=MB)
