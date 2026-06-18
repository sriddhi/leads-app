import logging
import mimetypes
import uuid
from pathlib import Path

import aiofiles
from fastapi import HTTPException, UploadFile, status

from app.core.config import settings

logger = logging.getLogger(__name__)

# Allowed MIME types and their canonical extensions
ALLOWED_MIME_TYPES: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}

MAX_FILE_SIZE_BYTES = settings.MAX_UPLOAD_BYTES

_CHUNK = 1024 * 1024  # 1 MB streaming chunks

# Content-based file-type detection (magic bytes) — do NOT trust the client MIME/extension.
_EXT_BY_FAMILY = {"pdf": ".pdf", "docx": ".docx", "doc": ".doc"}


def _sniff_family(head: bytes) -> str | None:
    """Identify the real file family from leading bytes, or None if unrecognised."""
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):  # ZIP container → modern .docx (OOXML)
        return "docx"
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):  # OLE2 → legacy .doc
        return "doc"
    return None


def _get_upload_dir() -> Path:
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def _validate_content_type(content_type: str | None, filename: str) -> str:
    """
    Validate the file's MIME type against the allowed list.
    Falls back to guessing from the filename extension if content_type is absent.
    Returns the validated MIME type string.
    Raises HTTPException 400 if not allowed.
    """
    mime = content_type or ""

    # Normalise: strip charset or boundary parameters (e.g. "application/pdf; charset=utf-8")
    mime = mime.split(";")[0].strip().lower()

    if not mime:
        # Try to guess from filename
        guessed, _ = mimetypes.guess_type(filename)
        mime = guessed or ""

    if mime not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file type '{mime}'. "
                "Only PDF, DOC, and DOCX files are accepted."
            ),
        )
    return mime


async def save_resume(file: UploadFile) -> tuple[str, str]:
    """
    Validate and persist an uploaded resume file to the UPLOAD_DIR.

    Returns:
        (stored_filename, original_filename) — stored_filename is UUID-prefixed.

    Raises:
        HTTPException 400 for invalid type or file too large.
    """
    original_filename = file.filename or "resume"

    # Cheap first gate: reject obviously-wrong declared MIME before reading bytes.
    _validate_content_type(file.content_type, original_filename)

    # Stream the upload in bounded chunks so an oversized file can never be fully
    # buffered into memory (memory-exhaustion DoS). Abort as soon as the cap is passed.
    chunks: list[bytes] = []
    total = 0
    head = b""
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File exceeds maximum allowed size of "
                f"{MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB.",
            )
        if len(head) < 8:
            head = (head + chunk)[:8]
        chunks.append(chunk)

    if total == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    # Content-based validation: the real bytes must be a PDF/DOC/DOCX — not just a
    # file the client *labelled* as one. The stored extension is derived from the
    # sniffed family, never from the (attacker-controlled) original name.
    family = _sniff_family(head)
    if family is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File contents are not a valid PDF, DOC, or DOCX.",
        )

    content = b"".join(chunks)
    stored_filename = f"{uuid.uuid4()}{_EXT_BY_FAMILY[family]}"
    destination = _get_upload_dir() / stored_filename

    async with aiofiles.open(destination, "wb") as out_file:
        await out_file.write(content)

    logger.info("Saved resume: %s -> %s (%s)", original_filename, stored_filename, family)
    return stored_filename, original_filename


def delete_resume(stored_filename: str) -> None:
    """Remove a previously stored resume file. Silently ignores missing files."""
    path = _get_upload_dir() / stored_filename
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Could not delete file %s: %s", stored_filename, exc)
