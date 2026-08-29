from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError


DEFAULT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_BATCH_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_BATCH_FILES = 25
DEFAULT_MAX_PDF_PAGES = 50
DEFAULT_MAX_IMAGE_PIXELS = 40_000_000
UPLOAD_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class UploadLimits:
    max_upload_bytes: int
    max_batch_bytes: int
    max_batch_files: int
    max_pdf_pages: int
    max_image_pixels: int


@dataclass(frozen=True)
class StoredUpload:
    path: Path
    original_filename: str
    media_type: str
    extension: str
    size_bytes: int
    page_count: int


class UploadValidationError(ValueError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _positive_env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be a positive integer") from error
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer")
    return value


def upload_limits() -> UploadLimits:
    return UploadLimits(
        max_upload_bytes=_positive_env_int("MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES),
        max_batch_bytes=_positive_env_int("MAX_BATCH_BYTES", DEFAULT_MAX_BATCH_BYTES),
        max_batch_files=_positive_env_int("MAX_BATCH_FILES", DEFAULT_MAX_BATCH_FILES),
        max_pdf_pages=_positive_env_int("MAX_PDF_PAGES", DEFAULT_MAX_PDF_PAGES),
        max_image_pixels=_positive_env_int("MAX_IMAGE_PIXELS", DEFAULT_MAX_IMAGE_PIXELS),
    )


_TYPE_DETAILS = {
    "pdf": (".pdf", "application/pdf", {".pdf"}),
    "png": (".png", "image/png", {".png"}),
    "jpeg": (".jpg", "image/jpeg", {".jpg", ".jpeg"}),
    "webp": (".webp", "image/webp", {".webp"}),
}


def _detect_type(header: bytes) -> str | None:
    if header.startswith(b"%PDF-"):
        return "pdf"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "webp"
    return None


def _validate_extension(filename: str, detected_type: str) -> None:
    supplied_extension = Path(filename).suffix.lower()
    allowed_extensions = _TYPE_DETAILS[detected_type][2]
    if supplied_extension not in allowed_extensions:
        expected = "/".join(sorted(allowed_extensions))
        raise UploadValidationError(
            415,
            f"File extension does not match its contents. Expected {expected} for this file.",
        )


def _validate_pdf(path: Path, max_pages: int) -> int:
    try:
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            raise UploadValidationError(422, "Password-protected PDFs are not supported")
        page_count = len(reader.pages)
        if page_count < 1:
            raise UploadValidationError(422, "PDF contains no pages")
        if page_count > max_pages:
            raise UploadValidationError(
                413,
                f"PDF contains {page_count} pages; the maximum is {max_pages}",
            )
        for page in reader.pages:
            _ = page.mediabox
        return page_count
    except UploadValidationError:
        raise
    except (PdfReadError, OSError, ValueError, TypeError) as error:
        raise UploadValidationError(422, "PDF is corrupt or cannot be read") from error


def _validate_image(path: Path, detected_type: str, max_pixels: int) -> int:
    expected_format = {"png": "PNG", "jpeg": "JPEG", "webp": "WEBP"}[detected_type]
    try:
        with Image.open(path) as image:
            if image.format != expected_format:
                raise UploadValidationError(422, "Image format does not match its signature")
            width, height = image.size
            if width < 1 or height < 1:
                raise UploadValidationError(422, "Image has invalid dimensions")
            if width * height > max_pixels:
                raise UploadValidationError(
                    413,
                    f"Image has {width * height:,} pixels; the maximum is {max_pixels:,}",
                )
            image.verify()
        with Image.open(path) as image:
            image.load()
        return 1
    except UploadValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as error:
        raise UploadValidationError(422, "Image is corrupt or cannot be decoded") from error


def remove_stored_uploads(uploads: list[StoredUpload] | tuple[StoredUpload, ...]) -> None:
    for upload in uploads:
        try:
            upload.path.unlink(missing_ok=True)
        except OSError:
            # Cleanup is best-effort here; callers still receive the original error.
            pass


async def store_validated_upload(
    upload: UploadFile,
    upload_dir: str | Path,
    *,
    limits: UploadLimits | None = None,
) -> StoredUpload:
    limits = limits or upload_limits()
    destination_dir = Path(upload_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    original_filename = Path(upload.filename or "upload").name
    temporary_path = destination_dir / f".{uuid.uuid4()}.uploading"
    size_bytes = 0
    header = bytearray()

    try:
        with temporary_path.open("xb") as output:
            try:
                os.chmod(temporary_path, 0o600)
            except OSError:
                pass
            while True:
                chunk = await upload.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > limits.max_upload_bytes:
                    raise UploadValidationError(
                        413,
                        f"File exceeds the {limits.max_upload_bytes // (1024 * 1024)} MB upload limit",
                    )
                if len(header) < 16:
                    header.extend(chunk[: 16 - len(header)])
                output.write(chunk)

        if size_bytes == 0:
            raise UploadValidationError(422, "Uploaded file is empty")

        detected_type = _detect_type(bytes(header))
        if not detected_type:
            raise UploadValidationError(415, "Only PDF, PNG, JPEG, and WebP files are accepted")
        _validate_extension(original_filename, detected_type)

        extension, media_type, _ = _TYPE_DETAILS[detected_type]
        page_count = (
            _validate_pdf(temporary_path, limits.max_pdf_pages)
            if detected_type == "pdf"
            else _validate_image(temporary_path, detected_type, limits.max_image_pixels)
        )

        final_path = destination_dir / f"{uuid.uuid4()}{extension}"
        temporary_path.replace(final_path)
        return StoredUpload(
            path=final_path,
            original_filename=original_filename,
            media_type=media_type,
            extension=extension,
            size_bytes=size_bytes,
            page_count=page_count,
        )
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


async def store_validated_batch(
    uploads: list[UploadFile],
    upload_dir: str | Path,
) -> list[StoredUpload]:
    limits = upload_limits()
    if not uploads:
        raise UploadValidationError(422, "At least one file is required")
    if len(uploads) > limits.max_batch_files:
        raise UploadValidationError(
            413,
            f"Batch contains {len(uploads)} files; the maximum is {limits.max_batch_files}",
        )

    stored: list[StoredUpload] = []
    total_bytes = 0
    try:
        for upload in uploads:
            item = await store_validated_upload(upload, upload_dir, limits=limits)
            stored.append(item)
            total_bytes += item.size_bytes
            if total_bytes > limits.max_batch_bytes:
                raise UploadValidationError(
                    413,
                    f"Batch exceeds the {limits.max_batch_bytes // (1024 * 1024)} MB request limit",
                )
        return stored
    except Exception:
        remove_stored_uploads(stored)
        raise
