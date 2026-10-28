from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from investiq.core.errors import AppError

MAX_UPLOAD = 1024 * 1024


def normalize_photo(raw: bytes) -> bytes:
    if not raw or len(raw) > MAX_UPLOAD:
        raise AppError(413, "photo_too_large", "Choose a photo under 1 MB after cropping")
    try:
        with Image.open(BytesIO(raw), formats=["JPEG", "PNG", "WEBP"]) as image:
            if image.width * image.height > 16_000_000 or max(image.size) > 8192:
                raise ValueError("Image dimensions are too large")
            if getattr(image, "n_frames", 1) != 1:
                raise ValueError("Animated photos are not supported")
            image.load()
            cropped = ImageOps.fit(ImageOps.exif_transpose(image).convert("RGBA"), (256, 256))
            # A fresh RGB image strips EXIF, location data and other original metadata.
            clean = Image.new("RGB", (256, 256), "white")
            clean.paste(cropped, mask=cropped.getchannel("A"))
            output = BytesIO()
            clean.save(output, format="JPEG", quality=88, optimize=True)
            return output.getvalue()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise AppError(
            422, "invalid_photo", "Choose a valid, still JPEG, PNG, or WebP photo"
        ) from exc
