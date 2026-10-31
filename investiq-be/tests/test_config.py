import pytest
from pydantic import ValidationError

from investiq.core.config import Settings


@pytest.mark.parametrize("origin", ["*", "https://example.com/path", "ftp://example.com"])
def test_unsafe_cors_origins_rejected(origin: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cors_origins=[origin])


def test_database_driver_and_secret_handling() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="sqlite:///test.db")
    config = Settings(
        _env_file=None, database_url="postgresql+asyncpg://user:private_password@localhost/db"
    )
    assert "private_password" not in repr(config)
    assert "private_password" not in config.model_dump_json()


@pytest.mark.parametrize(
    "sender",
    [
        "InvestIQ sender@example.com",
        "InvestIQ <sender@example.com",
        "sender@example.com\r\nBcc: someone@example.com",
        "first@example.com, second@example.com",
        "InvestIQ",
        "",
    ],
)
def test_malformed_email_sender_rejected_before_smtp(sender: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, mail_from=sender)


@pytest.mark.parametrize(
    "sender",
    ["sender@example.com", "InvestIQ <sender@example.com>", "InvestIQ <no-reply@investiq.local>"],
)
def test_valid_email_sender_and_local_development_address_accepted(sender: str) -> None:
    assert Settings(_env_file=None, mail_from=sender).mail_from == sender
