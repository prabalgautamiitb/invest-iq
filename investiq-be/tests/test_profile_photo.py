from io import BytesIO

import pytest
from PIL import Image

from investiq.core.config import Settings
from investiq.core.errors import AppError
from investiq.main import create_app
from investiq.services.profile_photo import MAX_UPLOAD, normalize_photo
from tests.conftest import CapturedMailer
from tests.helpers import test_client as api_client
from tests.test_identity import csrf, register


def picture(color: str = "red", size: tuple[int, int] = (400, 240), kind: str = "PNG") -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format=kind)
    return output.getvalue()


def test_photo_is_normalized_and_original_metadata_is_removed() -> None:
    original = Image.new("RGB", (400, 240), "blue")
    metadata = Image.Exif()
    metadata[315] = "Private camera owner"
    output = BytesIO()
    original.save(output, format="JPEG", exif=metadata)
    result = normalize_photo(output.getvalue())
    with Image.open(BytesIO(result)) as stored:
        assert stored.format == "JPEG"
        assert stored.size == (256, 256)
        assert stored.mode == "RGB"
        assert not stored.getexif()
    assert b"Private camera owner" not in result


@pytest.mark.parametrize(
    "raw",
    [
        b"not a photo",
        b'<svg xmlns="http://www.w3.org/2000/svg"/>',
        picture(kind="GIF"),
        picture(size=(8193, 1)),
    ],
)
def test_rejects_invalid_formats_and_dimensions(raw: bytes) -> None:
    with pytest.raises(AppError) as error:
        normalize_photo(raw)
    assert error.value.status == 422


def test_rejects_empty_oversized_and_animated_images() -> None:
    for raw in [b"", b"x" * (MAX_UPLOAD + 1)]:
        with pytest.raises(AppError) as error:
            normalize_photo(raw)
        assert error.value.status == 413
    output = BytesIO()
    Image.new("RGB", (20, 20), "red").save(
        output, format="PNG", save_all=True, append_images=[Image.new("RGB", (20, 20), "blue")]
    )
    with pytest.raises(AppError):
        normalize_photo(output.getvalue())


@pytest.mark.integration
async def test_photo_upload_replace_delete_csrf_and_account_isolation(
    identity_settings: Settings,
) -> None:
    mailer = CapturedMailer()
    async with (
        api_client(create_app(identity_settings, mailer)) as alice,
        api_client(create_app(identity_settings, mailer)) as bob,
    ):
        user = await register(alice)
        assert user["photo_version"] is None
        await register(bob)
        assert (await alice.get("/api/v1/me/photo")).status_code == 404
        assert (await alice.put("/api/v1/me/photo", content=picture())).status_code == 403
        headers = {**await csrf(alice), "Content-Type": "image/png"}
        saved = await alice.put("/api/v1/me/photo", content=picture(), headers=headers)
        assert saved.status_code == 200, saved.text
        version = saved.json()["photo_version"]
        assert version
        result = await alice.get("/api/v1/me/photo")
        assert result.headers["content-type"] == "image/jpeg"
        assert "no-store" in result.headers["cache-control"]
        assert Image.open(BytesIO(result.content)).size == (256, 256)
        assert (await bob.get("/api/v1/me/photo")).status_code == 404
        for content, mime, status in [
            (b"bad", "image/jpeg", 422),
            (b"bad", "text/html", 415),
            (b"x" * (MAX_UPLOAD + 1), "image/png", 413),
        ]:
            response = await alice.put(
                "/api/v1/me/photo", content=content, headers={**headers, "Content-Type": mime}
            )
            assert response.status_code == status
            assert (await alice.get("/api/v1/me")).json()["photo_version"] == version
        replaced = await alice.put("/api/v1/me/photo", content=picture("green"), headers=headers)
        assert replaced.json()["photo_version"] != version
        other = await bob.put(
            "/api/v1/me/photo",
            content=picture("blue"),
            headers={**await csrf(bob), "Content-Type": "image/png"},
        )
        assert other.status_code == 200
        assert (await alice.get("/api/v1/me/photo")).content != (
            await bob.get("/api/v1/me/photo")
        ).content
        removed = await alice.delete("/api/v1/me/photo", headers=await csrf(alice))
        assert removed.json()["photo_version"] is None
        assert (await alice.get("/api/v1/me/photo")).status_code == 404
        assert (await bob.get("/api/v1/me/photo")).status_code == 200
        assert (
            await alice.delete("/api/v1/me/photo", headers=await csrf(alice))
        ).status_code == 200
        await alice.post("/api/v1/auth/logout", headers=await csrf(alice))
        assert (await alice.get("/api/v1/me/photo")).status_code == 401
