import keyring
import pytest
from keyring.errors import PasswordDeleteError


@pytest.fixture
def fake_keyring(monkeypatch):
    """In-memory keyring so tests never touch the real OS secret store."""
    data: dict[tuple[str, str], str] = {}

    def get(service, name):
        return data.get((service, name))

    def set_(service, name, value):
        data[(service, name)] = value

    def delete(service, name):
        if (service, name) not in data:
            raise PasswordDeleteError(name)
        del data[(service, name)]

    monkeypatch.setattr(keyring, "get_password", get)
    monkeypatch.setattr(keyring, "set_password", set_)
    monkeypatch.setattr(keyring, "delete_password", delete)
    return data
