"""Secret key generation and management."""

import secrets
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def get_or_create_secret_key(key_file: Path = Path("/data/secret.key")) -> str:
    """Get existing or create new secret key.

    If the secret key file exists, reads and returns it.
    If not, generates a new cryptographically secure key and saves it.

    Args:
        key_file: Path to the secret key file (default: /data/secret.key)

    Returns:
        The secret key as a string

    Note:
        Falls back to in-memory key generation if file operations fail.
        This means the key will change on restart, logging out all users.
    """
    try:
        # Check if key file already exists
        if key_file.exists():
            secret_key = key_file.read_text().strip()
            if secret_key:
                logger.debug("Loaded existing secret key from %s", key_file)
                return secret_key
            else:
                logger.warning(
                    "Secret key file at %s is empty, generating new key", key_file
                )

        # Generate cryptographically secure key (32 bytes = 256 bits)
        secret_key = secrets.token_urlsafe(32)

        # Ensure parent directory exists
        key_file.parent.mkdir(parents=True, exist_ok=True)

        # Write key to file
        # codeql[py/clear-text-storage-sensitive-data] - Secret key must persist across restarts
        # Security: File permissions set to 0o600 (owner-only access) and stored in protected /data volume
        # This is standard practice for JWT signing keys - encryption would require external key management
        key_file.write_text(secret_key)

        # Set restrictive permissions (owner read/write only)
        key_file.chmod(0o600)

        # Use print() instead of logger since logging isn't configured yet during import
        print(f"✓ Generated new secret key and saved to {key_file}")
        print("✓ Secret key will persist across container restarts")

        return secret_key

    except PermissionError as e:
        logger.error("Permission denied when accessing secret key file: %s", str(e))
        logger.warning("Using temporary in-memory secret key (will change on restart)")
        return secrets.token_urlsafe(32)

    except Exception as e:
        logger.error("Failed to handle secret key file: %s", str(e), exc_info=True)
        logger.warning("Using temporary in-memory secret key (will change on restart)")
        return secrets.token_urlsafe(32)
