from __future__ import annotations

from io import BytesIO
from urllib.parse import unquote

from PIL import Image, ImageOps, UnidentifiedImageError

PRODUCT_IMAGE_SIZE = 800
MAX_PRODUCT_IMAGE_BYTES = 500 * 1024
MAX_SOURCE_PIXELS = 16_000_000
ALLOWED_SOURCE_FORMATS = {"JPEG", "PNG", "WEBP"}


class ProductImageError(ValueError):
    pass


def normalize_product_image(content: bytes) -> bytes:
    """Validate an already-cropped square image and encode it as 800x800 WebP."""
    try:
        with Image.open(BytesIO(content)) as source:
            source_format = (source.format or "").upper()
            if source_format not in ALLOWED_SOURCE_FORMATS:
                raise ProductImageError("JPEG, PNG, WEBP 이미지만 업로드할 수 있어요")
            width, height = source.size
            if width <= 0 or height <= 0 or width * height > MAX_SOURCE_PIXELS:
                raise ProductImageError("이미지 크기는 1,600만 픽셀 이하여야 해요")
            if width != height:
                raise ProductImageError("이미지를 1:1로 크롭한 뒤 적용해 주세요")
            source.load()
            image = ImageOps.exif_transpose(source)
            if image.width != image.height:
                raise ProductImageError("이미지를 1:1로 크롭한 뒤 적용해 주세요")
            has_alpha = image.mode in ("RGBA", "LA") or "transparency" in image.info
            image = image.convert("RGBA" if has_alpha else "RGB")
            image = image.resize((PRODUCT_IMAGE_SIZE, PRODUCT_IMAGE_SIZE), Image.Resampling.LANCZOS)
    except ProductImageError:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError) as exc:
        raise ProductImageError("올바른 이미지 파일이 아니에요") from exc

    for quality in (88, 82, 76, 70, 62, 54, 46, 38):
        output = BytesIO()
        image.save(output, format="WEBP", quality=quality, method=6)
        encoded = output.getvalue()
        if len(encoded) <= MAX_PRODUCT_IMAGE_BYTES:
            return encoded
    raise ProductImageError("이미지를 500KB 이하로 변환할 수 없어요")


def managed_image_path(image_url: str | None, supabase_url: str, bucket: str, merchant_id: str) -> str | None:
    if not image_url:
        return None
    prefix = f"{supabase_url.rstrip('/')}/storage/v1/object/public/{bucket}/"
    if not image_url.startswith(prefix):
        return None
    path = unquote(image_url[len(prefix):])
    if not path.startswith(f"{merchant_id}/") or path.endswith("/"):
        return None
    return path
