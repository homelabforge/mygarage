"""Shared bits for tests that make their own users."""

# argon2id of "testpassword123" with auth.py's settings. Hashing for real needs
# threads, and PID-limited containers don't always have them.
TEST_PASSWORD_HASH = (
    "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$"
    "hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
)
