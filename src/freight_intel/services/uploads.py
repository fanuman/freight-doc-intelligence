"""Checks on a file someone uploads, before we store it or read it. Pure functions: no database, no disk.

An upload is untrusted input. The rules (from the design doc):
  - only the three types we can read (.pdf, .xlsx, .eml), decided by the extension AND confirmed by the content,
  - a size cap,
  - the client's filename is only ever shown to people; it never decides a path.
"""
import io
import re
import zipfile
from dataclasses import dataclass

ALLOWED_EXTENSIONS = (".pdf", ".xlsx", ".eml")
MAX_UNPACKED_BYTES = 100 * 1024 * 1024  # an .xlsx is a zip: refuse one that claims to unpack to more than this
MAX_NAME_CHARS = 200
_EML_HEADER = re.compile(rb"^[A-Za-z][A-Za-z0-9-]*:", re.M)


class UploadRejected(Exception):
    """The file is not acceptable. `code` says why (the API turns it into an HTTP status), `message` is for the person."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CheckedUpload:
    display_name: str  # safe to show; never used as a path
    extension: str  # one of ALLOWED_EXTENSIONS, lower case
    data: bytes


def display_name(filename: str | None) -> str:
    """The file's own name without any folders, control characters or excessive length."""
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    return name[:MAX_NAME_CHARS]


def _extension(name: str) -> str:
    dot = name.rfind(".")
    return name[dot:].lower() if dot > 0 else ""


def _looks_like_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"


def _looks_like_xlsx(data: bytes) -> bool:
    if data[:4] != b"PK\x03\x04":
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:  # reads only the table of contents
            names = set(archive.namelist())
            unpacked = sum(info.file_size for info in archive.infolist())
    except zipfile.BadZipFile:
        return False
    return "[Content_Types].xml" in names and "xl/workbook.xml" in names and unpacked <= MAX_UNPACKED_BYTES


def _looks_like_eml(data: bytes) -> bool:
    head = data[:8192]
    if b"\x00" in head:  # a binary file, not a mail message
        return False
    headers = {m.group(0).lower() for m in _EML_HEADER.finditer(head)}
    return b"from:" in headers or b"subject:" in headers


_CONTENT_CHECKS = {".pdf": _looks_like_pdf, ".xlsx": _looks_like_xlsx, ".eml": _looks_like_eml}


def check_upload(filename: str | None, data: bytes, *, max_bytes: int) -> CheckedUpload:
    """Return the cleaned-up upload, or raise UploadRejected."""
    name = display_name(filename)
    if not name:
        raise UploadRejected("missing_filename", "the file has no name")
    extension = _extension(name)
    if extension not in ALLOWED_EXTENSIONS:
        raise UploadRejected("unsupported_type", f"only {', '.join(ALLOWED_EXTENSIONS)} files are accepted")
    if not data:
        raise UploadRejected("empty", "the file is empty")
    if len(data) > max_bytes:
        raise UploadRejected("too_large", f"the file is larger than {max_bytes // (1024 * 1024)} MB")
    if not _CONTENT_CHECKS[extension](data):
        raise UploadRejected("content_mismatch", f"the content does not look like a real {extension} file")
    return CheckedUpload(name, extension, data)
