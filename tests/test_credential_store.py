import keyring.errors
import pytest

from app import credential_store


class FakeKeyringBackend:
    """In-memory stand-in for a real OS credential store, so these tests
    verify our wrapper's logic without depending on an actual keychain
    being available (this sandbox has none; Windows/macOS/Linux desktop
    sessions do)."""

    def __init__(self):
        self._store = {}

    def set_password(self, service, username, password):
        self._store[(service, username)] = password

    def get_password(self, service, username):
        return self._store.get((service, username))

    def delete_password(self, service, username):
        if (service, username) not in self._store:
            raise keyring.errors.PasswordDeleteError("not found")
        del self._store[(service, username)]


@pytest.fixture
def fake_backend(monkeypatch):
    backend = FakeKeyringBackend()
    monkeypatch.setattr(credential_store.keyring, "set_password", backend.set_password)
    monkeypatch.setattr(credential_store.keyring, "get_password", backend.get_password)
    monkeypatch.setattr(credential_store.keyring, "delete_password", backend.delete_password)
    return backend


def test_save_and_load_round_trips(fake_backend):
    credential_store.save_application_password("xxxx xxxx xxxx xxxx")
    assert credential_store.load_application_password() == "xxxx xxxx xxxx xxxx"


def test_load_returns_none_when_nothing_stored(fake_backend):
    assert credential_store.load_application_password() is None


def test_clear_removes_stored_password(fake_backend):
    credential_store.save_application_password("secret")
    credential_store.clear_application_password()
    assert credential_store.load_application_password() is None


def test_clear_is_safe_when_nothing_was_stored(fake_backend):
    credential_store.clear_application_password()  # must not raise


def test_load_returns_none_when_backend_unavailable(monkeypatch):
    def raise_error(*a, **kw):
        raise keyring.errors.KeyringError("no backend available")

    monkeypatch.setattr(credential_store.keyring, "get_password", raise_error)
    assert credential_store.load_application_password() is None


def test_save_raises_clear_error_when_backend_unavailable(monkeypatch):
    def raise_error(*a, **kw):
        raise keyring.errors.KeyringError("no backend available")

    monkeypatch.setattr(credential_store.keyring, "set_password", raise_error)
    with pytest.raises(credential_store.CredentialStoreError):
        credential_store.save_application_password("secret")
