"""Inspection supporting-document validation.

Reuses `workspace.attachments` — this project's one secure, data-URI-based
file-handling mechanism (itself built on `users.photos`'s original
pattern for profile photographs) — rather than a third implementation of
the same signature-checking logic. The only thing specific to this app is
the accepted format list: PDF/JPG/PNG (task's stated minimum for
inspection documents), a subset of what `workspace.attachments` already
validates, so restricting to it is just a filter, not new logic.
"""

from __future__ import annotations

from workspace.attachments import AttachmentError, validate_attachment

INSPECTION_ACCEPTED_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png"}
INSPECTION_ACCEPTED_LABEL = "PDF, JPG or PNG"


def validate_inspection_attachment(value: str | None, *, filename: str = "") -> tuple[str, str, str]:
    data_uri, safe_name, mime = validate_attachment(value, filename=filename)
    if data_uri and mime not in INSPECTION_ACCEPTED_MIME_TYPES:
        raise AttachmentError(f"That file type is not supported here. Use {INSPECTION_ACCEPTED_LABEL}.")
    return data_uri, safe_name, mime
