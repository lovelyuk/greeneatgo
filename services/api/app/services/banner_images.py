from __future__ import annotations

from io import BytesIO
import warnings
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BANNER_IMAGE_BYTES = 2 * 1024 * 1024
MAX_BANNER_DIMENSION = 6000
MAX_BANNER_PIXELS = 20_000_000
_RATIOS = {"home_bottom": 3.0, "event_page": 2.0}


class BannerImageError(ValueError):
    pass


def convert_banner_image(data: bytes, content_type: str | None, placement: str) -> bytes:
    """Validate and normalize an uploaded banner; originals are never persisted."""
    if not data or len(data) > MAX_BANNER_IMAGE_BYTES:
        raise BannerImageError("IMAGE_SIZE_INVALID")
    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise BannerImageError("IMAGE_TYPE_INVALID")
    target = _RATIOS.get(placement)
    if target is None:
        raise BannerImageError("PLACEMENT_INVALID")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"}:
                    raise BannerImageError("IMAGE_TYPE_INVALID")
                width, height = source.size
                if (width < 2 or height < 2 or width > MAX_BANNER_DIMENSION
                        or height > MAX_BANNER_DIMENSION or width * height > MAX_BANNER_PIXELS):
                    raise BannerImageError("IMAGE_DIMENSIONS_INVALID")
                if abs((width / height) - target) > target * 0.10:
                    raise BannerImageError("IMAGE_RATIO_INVALID")
                source.load()
                image = ImageOps.exif_transpose(source)
                image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise BannerImageError("IMAGE_INVALID") from exc
    width, height = image.size
    if abs((width / height) - target) > target * 0.10:
        raise BannerImageError("IMAGE_RATIO_INVALID")
    if width > 2400:
        image.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA" if "transparency" in image.info else "RGB")
    output = BytesIO()
    image.save(output, "WEBP", quality=86, method=6)
    result = output.getvalue()
    if len(result) > MAX_BANNER_IMAGE_BYTES:
        raise BannerImageError("IMAGE_SIZE_INVALID")
    return result
