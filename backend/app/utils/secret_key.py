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
                logger.debug(f"Loaded existing secret key from {key_file}")
                return secret_key
            else:
                logger.warning(f"Secret key file at {key_file} is empty, generating new key")

        # Generate cryptographically secure key (32 bytes = 256 bits)
        secret_key = secrets.token_urlsafe(32)

        # Ensure parent directory exists
        key_file.parent.mkdir(parents=True, exist_ok=True)

        # Write key to file
        key_file.write_text(secret_key)

        # Set restrictive permissions (owner read/write only)
        key_file.chmod(0o600)

        # Use print() instead of logger since logging isn't configured yet during import
        print(f"✓ Generated new secret key and saved to {key_file}")
        print(f"✓ Secret key will persist across container restarts")

        return secret_key

    except PermissionError as e:
        logger.error(f"Permission denied when accessing secret key file: {e}")
        logger.warning("Using temporary in-memory secret key (will change on restart)")
        return secrets.token_urlsafe(32)

    except Exception as e:
        logger.error(f"Failed to handle secret key file: {e}", exc_info=True)
        logger.warning("Using temporary in-memory secret key (will change on restart)")
        return secrets.token_urlsafe(32)
