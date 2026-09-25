"""Fernet-backed encryption for API keys at rest."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class SecretsError(RuntimeError):
    """Raised when encryption setup or operation fails."""


class Secrets:
    """Wrapper around a Fernet instance.

    The master key is a 32-byte url-safe base64 string. It MUST come from
    environment variable `ROUTE_FORGE_MASTER_KEY`. The instance never logs
    or echoes any plaintext or ciphertext.
    """

    def __init__(self, master_key: str | None) -> None:
        if not master_key:
            raise SecretsError("ROUTE_FORGE_MASTER_KEY is required")
        try:
            self._fernet = Fernet(master_key.encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise SecretsError("ROUTE_FORGE_MASTER_KEY is not a valid Fernet key") from exc

    def encrypt(self, plaintext: str) -> bytes:
        if not isinstance(plaintext, str):
            raise SecretsError("plaintext must be str")
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        try:
            return self._fernet.decrypt(ciphertext).decode("utf-8")
        except InvalidToken as exc:
            raise SecretsError("decryption failed") from exc

    @staticmethod
    def generate_key() -> str:
        """Generate a fresh Fernet key (44 url-safe base64 chars)."""
        return Fernet.generate_key().decode("ascii")
