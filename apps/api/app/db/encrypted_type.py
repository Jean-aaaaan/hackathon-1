"""
EncryptedText — SQLAlchemy TypeDecorator for at-rest encryption of sensitive columns.

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the cryptography library.
Key is read from FIELD_ENCRYPTION_KEY env var (must be a valid Fernet key).

Generate a key:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Graceful migration path: if decryption fails (pre-encryption plaintext), the raw
value is returned so existing rows can be re-encrypted on next write without data loss.
"""
from sqlalchemy import types


class EncryptedText(types.TypeDecorator):
    impl = types.Text
    cache_ok = True

    def _fernet(self):
        from app.config import get_settings
        import structlog as _sl
        key = get_settings().field_encryption_key
        if not key:
            _sl.get_logger().warning("field_encryption_key_absent_tokens_plaintext")
            return None
        from cryptography.fernet import Fernet
        return Fernet(key.encode() if isinstance(key, str) else key)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        f = self._fernet()
        if f is None:
            return value
        return f.encrypt(value.encode()).decode()

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        f = self._fernet()
        if f is None:
            return value
        try:
            return f.decrypt(value.encode()).decode()
        except Exception:
            return value  # Pre-encryption plaintext fallback — will re-encrypt on next write
