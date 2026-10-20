import pytest
from pydantic import ValidationError

from investiq.core.errors import AppError
from investiq.schemas.identity import ProfileUpdate, RegisterInput, ResetInput, TokenInput
from investiq.services.identity import IdentityService


@pytest.mark.parametrize("value", ["Name\x00", "Name\nOther", "\ud800"])
def test_profile_rejects_database_incompatible_text(value: str) -> None:
    with pytest.raises(ValidationError):
        ProfileUpdate(name=value)


def test_malformed_secret_input_is_rejected_without_normalizing_passwords() -> None:
    with pytest.raises(ValidationError):
        ResetInput(token="a" * 43, password="bad\ud800password123")
    with pytest.raises(ValidationError):
        TokenInput(token="é" * 43)
    payload = RegisterInput(
        email="learner@example.com", name="Learner", password="  spaced password  "
    )
    assert payload.password.get_secret_value() == "  spaced password  "


def test_malformed_csrf_returns_forbidden() -> None:
    # No resources are used by this pure check.
    instance = object.__new__(IdentityService)
    for value in ("é" * 64, "a" * 65, "a"):
        with pytest.raises(AppError) as error:
            instance.validate_csrf("cookie", value)
        assert error.value.status == 403
