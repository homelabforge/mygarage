"""Settings-secret errors that the error handlers map, kept in a leaf module.

``app.utils.error_handlers`` maps these to HTTP responses, and a utils module
must not import a service to do it. ``app.services.settings_secrets`` raises
``PlaintextSecretsRemain`` and re-exports it, so existing imports keep working.
"""

from app.utils.settings_crypto import ENV_KEY


class PlaintextSecretsRemain(Exception):  # noqa: N818 - the name the plan and later tasks use
    """A backup was refused: some secret settings are still stored as plaintext (R1-H1).

    Deliberately not a ``RuntimeError``: the full-backup route maps those to a
    500, and this must stay a 503 (R2-2). ``register_error_handlers`` maps it.
    Names setting keys only, never a value.

    Attributes:
        keys: The secret setting keys still stored as plaintext, sorted.
    """

    def __init__(self, keys: tuple[str, ...], *, keyring_unavailable: bool = True) -> None:
        """Build the refusal for these keys.

        Args:
            keys: The plaintext secret setting keys, sorted.
            keyring_unavailable: Why they stayed plaintext. True says how to fix
                the key; False means encrypting them failed with a key at hand.
        """
        self.keys = keys
        fix = (
            f"Set {ENV_KEY} to a valid key, or make the data directory writable so a key "
            "can be generated, then try again."
            if keyring_unavailable
            else "Encrypting them failed; check the server log, then try again."
        )
        super().__init__(
            "Backups are refused while these secret settings are stored unencrypted: "
            f"{', '.join(keys)}. A backup, and the safety backup a restore writes first, "
            f"would copy them in the clear. {fix}"
        )
