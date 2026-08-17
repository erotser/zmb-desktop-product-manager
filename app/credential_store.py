"""
Secure storage for the site sync Application Password, using the OS's
native credential store via `keyring` (Windows Credential Manager on
Windows) rather than plaintext JSON -- this is a real, live credential,
unlike the rest of settings.json which only holds non-sensitive
preferences (site URL, username -- the username alone isn't sensitive
without the password).
"""

from __future__ import annotations

import keyring
import keyring.errors

SERVICE_NAME = "ZombeeProductManager"
ACCOUNT_KEY = "site_application_password"


class CredentialStoreError(Exception):
    pass


def save_application_password(password: str) -> None:
    try:
        keyring.set_password(SERVICE_NAME, ACCOUNT_KEY, password)
    except keyring.errors.KeyringError as e:
        raise CredentialStoreError(f"Could not save the password securely: {e}") from e


def load_application_password() -> str | None:
    try:
        return keyring.get_password(SERVICE_NAME, ACCOUNT_KEY)
    except keyring.errors.KeyringError:
        return None


def clear_application_password() -> None:
    try:
        keyring.delete_password(SERVICE_NAME, ACCOUNT_KEY)
    except keyring.errors.KeyringError:
        pass  # nothing stored, or backend unavailable -- either way, nothing more to do
