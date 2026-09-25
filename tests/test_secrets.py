"""Tests for Fernet secret wrapper."""

from __future__ import annotations

import pytest

from routeforge.secrets import Secrets, SecretsError


def test_round_trip() -> None:
    s = Secrets(Secrets.generate_key())
    assert s.decrypt(s.encrypt("hello")) == "hello"


def test_missing_key_raises() -> None:
    with pytest.raises(SecretsError):
        Secrets(None)


def test_malformed_key_raises() -> None:
    with pytest.raises(SecretsError):
        Secrets("not-a-valid-fernet-key")


def test_decrypt_invalid_token_raises_generic() -> None:
    s = Secrets(Secrets.generate_key())
    with pytest.raises(SecretsError, match="decryption failed"):
        s.decrypt(b"this-is-not-a-fernet-token")


def test_generate_key_is_urlsafe_44_chars() -> None:
    key = Secrets.generate_key()
    assert len(key) == 44
