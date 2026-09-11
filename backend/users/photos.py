"""Profile photograph validation.

A photograph is stored as a data URI on the user record and served only
through the authenticated profile endpoints, so an uploaded image is never
reachable from a public media URL.

Validation is deliberately paranoid and dependency-free: the declared type has
to be one we accept, the payload has to actually decode, the decoded bytes have
to start with that format's real signature, and the whole thing has to fit
inside the size limit. A file that merely *claims* to be a PNG is refused.
"""

from __future__ import annotations

import base64
import binascii
import re

#: 1.5 MB of decoded image data. The portal downscales before uploading, so a
#: normal profile photograph lands far below this; the limit exists to stop a
#: large file being posted straight at the API.
MAX_PHOTO_BYTES = 1_500_000

MAX_PHOTO_MB_LABEL = "1.5 MB"

#: mime type -> accepted leading bytes
SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/webp": (b"RIFF",),
}

ACCEPTED_LABEL = "PNG, JPG or WebP"

_DATA_URI = re.compile(
    r"^data:(?P<mime>image/[a-z0-9.+-]+);base64,(?P<payload>[A-Za-z0-9+/=\s]+)$",
    re.IGNORECASE,
)


class PhotoError(ValueError):
    """Raised with a message that is safe and useful to show to a person."""


def validate_photo(value: str | None) -> str:
    """Return a normalised data URI, or '' when the photograph is cleared.

    Raises PhotoError with a plain-language message on anything unusable.
    """

    if value is None:
        return ""

    text = str(value).strip()
    if not text:
        # An explicit empty value removes the current photograph.
        return ""

    match = _DATA_URI.match(text)
    if not match:
        raise PhotoError(
            f"Upload a {ACCEPTED_LABEL} image. The file could not be read as an image."
        )

    mime = match.group("mime").lower()
    if mime == "image/jpg":  # some browsers report it this way
        mime = "image/jpeg"
    if mime not in SIGNATURES:
        raise PhotoError(f"That image type is not supported. Use {ACCEPTED_LABEL}.")

    payload = re.sub(r"\s+", "", match.group("payload"))
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise PhotoError("That image could not be read. Try uploading it again.")

    if not raw:
        raise PhotoError("That image file is empty.")

    if len(raw) > MAX_PHOTO_BYTES:
        raise PhotoError(
            f"That image is too large. Choose one under {MAX_PHOTO_MB_LABEL}."
        )

    if not any(raw.startswith(signature) for signature in SIGNATURES[mime]):
        raise PhotoError(
            f"That file does not look like a {ACCEPTED_LABEL} image."
        )

    if mime == "image/webp" and not (len(raw) > 12 and raw[8:12] == b"WEBP"):
        raise PhotoError("That file does not look like a WebP image.")

    return f"data:{mime};base64,{payload}"
