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
