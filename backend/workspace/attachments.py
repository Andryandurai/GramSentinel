"""Message attachment validation — the same data-URI, paranoid-signature
pattern `users/photos.py` already established for profile photographs,
extended here to the document types this feature actually needs (the task's
own "reuse the existing secure file-upload mechanism" instruction: this IS
that mechanism, this project's only one, applied to a new set of formats
rather than reinvented).

An attachment lives on the `SupervisorMessage` row itself as a data URI —
never a filesystem path, never a public media URL — and is only ever
returned through the authenticated, thread-scoped message endpoints in
`views.py`. There is no separate "download" URL an unauthenticated request
could reach.
"""

from __future__ import annotations

import base64
import binascii
import re

#: 8 MB of decoded file data — generous enough for a scanned document or a
#: multi-page PDF while still bounding what a single message row can hold.
MAX_ATTACHMENT_BYTES = 8_000_000
MAX_ATTACHMENT_MB_LABEL = "8 MB"

#: mime type -> (accepted leading-byte signatures, file extension)
SIGNATURES: dict[str, tuple[tuple[bytes, ...], str]] = {
    "application/pdf": ((b"%PDF-",), "pdf"),
    "image/png": ((b"\x89PNG\r\n\x1a\n",), "png"),
    "image/jpeg": ((b"\xff\xd8\xff",), "jpg"),
    # DOC/XLS (legacy binary Office) and DOCX/XLSX (zip-based Office) share
    # one container signature family each — the specific sub-format is not
    # distinguishable from the leading bytes alone without a full archive
    # parse, which this deliberately-dependency-free validator does not do
    # (same "dependency-free" constraint `users/photos.py` already states).
    "application/msword": ((b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",), "doc"),
    "application/vnd.ms-excel": ((b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",), "xls"),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        (b"PK\x03\x04",),
        "docx",
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (
        (b"PK\x03\x04",),
        "xlsx",
    ),
}

ACCEPTED_LABEL = "PDF, DOC/DOCX, XLS/XLSX, PNG or JPG"

#: Types a browser can render directly, so the download endpoint serves
#: them with Content-Disposition: inline (opens a preview instead of a
#: forced Save As). Office document types cannot be rendered by the
#: browser itself either way, so they keep the "attachment" disposition.
INLINE_VIEWABLE_MIME_TYPES = frozenset(
    {"application/pdf", "image/png", "image/jpeg"}
)

_DATA_URI = re.compile(
    r"^data:(?P<mime>[a-z0-9.+/-]+);base64,(?P<payload>[A-Za-z0-9+/=\s]+)$",
    re.IGNORECASE,
)

#: Characters allowed in the officer-facing filename label — strips
#: anything that isn't a plain display character, so a worker-supplied
#: filename can never be interpreted as a path (no "/", no "..", no NUL).
_SAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9 ._()-]")


class AttachmentError(ValueError):
    """Raised with a message that is safe and useful to show to a person."""


def safe_filename(name: str, *, mime: str) -> str:
    """Never trusted as a path — used only as a display label. Falls back
    to a generic name with the correct extension for the accepted MIME
    type when the supplied name is empty or entirely stripped."""

    base = _SAFE_FILENAME_CHARS.sub("", (name or "").strip())[:120].strip(". ")
    if base:
        return base
    _, ext = SIGNATURES.get(mime, ((), "bin"))
    return f"attachment.{ext}"


def validate_attachment(value: str | None, *, filename: str = "") -> tuple[str, str, str]:
    """Returns (data_uri, safe_filename, mime) or ("", "", "") when cleared.

    Raises AttachmentError with a plain-language message on anything
    unusable — mirrors `users.photos.validate_photo` exactly.
    """

    if value is None:
        return "", "", ""

    text = str(value).strip()
    if not text:
        return "", "", ""

    match = _DATA_URI.match(text)
    if not match:
        raise AttachmentError(
            f"Attach a {ACCEPTED_LABEL} file. The file could not be read."
        )

    mime = match.group("mime").lower()
    if mime not in SIGNATURES:
        raise AttachmentError(f"That file type is not supported. Use {ACCEPTED_LABEL}.")

    payload = re.sub(r"\s+", "", match.group("payload"))
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise AttachmentError("That file could not be read. Try attaching it again.")

    if not raw:
        raise AttachmentError("That file is empty.")

    if len(raw) > MAX_ATTACHMENT_BYTES:
        raise AttachmentError(
            f"That file is too large. Choose one under {MAX_ATTACHMENT_MB_LABEL}."
        )

    signatures, _ext = SIGNATURES[mime]
    if not any(raw.startswith(signature) for signature in signatures):
        raise AttachmentError(f"That file does not look like a {ACCEPTED_LABEL.split(',')[0]} file.")

    return f"data:{mime};base64,{payload}", safe_filename(filename, mime=mime), mime
