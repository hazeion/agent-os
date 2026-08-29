"""Bounded hostile-image verification and WebP transformation."""

from __future__ import annotations

from io import BytesIO
import warnings

from PIL import Image, ImageOps, features
from link_preview_webp import valid_transformed_webp


MAXIMUM_ENCODED_IMAGE_BYTES = 2 * 1024 * 1024
MAXIMUM_IMAGE_DIMENSION = 2_048
MAXIMUM_IMAGE_PIXELS = 4_000_000
MAXIMUM_OUTPUT_DIMENSION = 1_200
MAXIMUM_OUTPUT_BYTES = 512 * 1024
_FORMATS = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}


class LinkPreviewImageError(ValueError):
    code = "link_preview.image_invalid"


def _signature(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return None


def transform_image(data: bytes, declared_mime: str) -> bytes | None:
    """Return one metadata-free static WebP, or ``None`` when output is unavailable."""

    if not isinstance(data, bytes) or not 1 <= len(data) <= MAXIMUM_ENCODED_IMAGE_BYTES:
        raise LinkPreviewImageError("preview image invalid")
    if not isinstance(declared_mime, str) or declared_mime not in _FORMATS:
        raise LinkPreviewImageError("preview image unsupported")
    expected = _FORMATS[declared_mime]
    if _signature(data) != expected:
        raise LinkPreviewImageError("preview image type mismatch")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            source = Image.open(BytesIO(data))
            if source.format != expected:
                raise LinkPreviewImageError("preview image type mismatch")
            width, height = source.size
            if (
                width < 1
                or height < 1
                or width > MAXIMUM_IMAGE_DIMENSION
                or height > MAXIMUM_IMAGE_DIMENSION
                or width * height > MAXIMUM_IMAGE_PIXELS
                or getattr(source, "n_frames", 1) != 1
                or bool(getattr(source, "is_animated", False))
            ):
                raise LinkPreviewImageError("preview image dimensions invalid")
            source.verify()
            source = Image.open(BytesIO(data))
            if source.format != expected or getattr(source, "n_frames", 1) != 1:
                raise LinkPreviewImageError("preview image type mismatch")
            source.load()
            oriented = ImageOps.exif_transpose(source)
            mode = "RGBA" if "A" in oriented.getbands() else "RGB"
            converted = oriented.convert(mode)
            clean = Image.new(mode, converted.size)
            clean.paste(converted)
    except LinkPreviewImageError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, SyntaxError, ValueError) as exc:
        raise LinkPreviewImageError("preview image invalid") from exc
    if not features.check("webp"):
        return None
    clean.thumbnail(
        (MAXIMUM_OUTPUT_DIMENSION, MAXIMUM_OUTPUT_DIMENSION),
        Image.Resampling.LANCZOS,
        reducing_gap=3.0,
    )
    output = BytesIO()
    try:
        if clean.mode == "RGBA":
            clean.save(output, "WEBP", lossless=True, method=6, exact=True)
        else:
            clean.save(output, "WEBP", quality=80, method=6)
    except (OSError, ValueError) as exc:
        raise LinkPreviewImageError("preview image transform unavailable") from exc
    result = output.getvalue()
    if not result or len(result) > MAXIMUM_OUTPUT_BYTES or not valid_transformed_webp(result):
        return None
    try:
        verified = Image.open(BytesIO(result))
        if (
            verified.format != "WEBP"
            or getattr(verified, "n_frames", 1) != 1
            or verified.width > MAXIMUM_OUTPUT_DIMENSION
            or verified.height > MAXIMUM_OUTPUT_DIMENSION
        ):
            raise LinkPreviewImageError("preview image transform invalid")
        verified.verify()
    except (OSError, SyntaxError, ValueError) as exc:
        raise LinkPreviewImageError("preview image transform invalid") from exc
    return result


__all__ = ["LinkPreviewImageError", "transform_image"]
