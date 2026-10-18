"""`Setting.value` encrypts and decrypts the secret keys at the model (D6).

The column is mapped to `stored_value`; `value` is a hybrid property. These pin
the getter and setter on in-memory rows, with no database:

- a secret is stored as current ciphertext and read back as plaintext;
- "" and None are stored as is, so "configured or not" stays visible;
- a re-save of the same value under the current key leaves the row alone, while
  a legacy plaintext row or one under an older key is always rewritten (R1-H3);
- a value that already looks like ciphertext is refused (R2-9);
- `stored_value=` passes raw bytes through, whatever the kwargs order;
- a ciphertext moved onto another key's row reads as unreadable (plan test 7).

Each test gets its own random key in MYGARAGE_SETTINGS_KEY, and the cached
keyring is reset before and after.
"""

import base64
import hashlib
import os
from collections.abc import Iterator

import pytest
from sqlalchemy import select

from app.models.settings import Setting, SettingCiphertextValue
from app.utils.secret_setting_keys import SECRET_SETTING_KEYS
from app.utils.settings_crypto import (
    CIPHERTEXT_PREFIX,
    ENV_KEY,
    ENV_KEY_FILE,
    DecryptStatus,
    SettingsKeyUnavailable,
    _reset_keyring_for_tests,  # pyright: ignore[reportPrivateUsage] - the suite's reset hook
    current_kid,
    decrypt,
    encrypt,
)

pytestmark = pytest.mark.unit

KeyEntry = tuple[str, str]
"""A keyring entry and its kid."""

SECRET = "gotify_token"
PLAIN = "gotify-token-0123456789"


def _new_key() -> tuple[str, str]:
    """A random keyring entry and its kid."""
    raw = os.urandom(32)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode(), hashlib.sha256(raw).hexdigest()[:8]


def _use_keys(monkeypatch: pytest.MonkeyPatch, *entries: str) -> None:
    monkeypatch.setenv(ENV_KEY, ",".join(entries))
    _reset_keyring_for_tests()


@pytest.fixture
def key_a(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, str]]:
    """An isolated one-key keyring; yields (entry, kid)."""
    monkeypatch.delenv(ENV_KEY_FILE, raising=False)
    entry = _new_key()
    _use_keys(monkeypatch, entry[0])
    yield entry
    _reset_keyring_for_tests()


class TestGetterAndSetter:
    def test_a_secret_is_stored_as_ciphertext_and_reads_back(self, key_a: KeyEntry) -> None:
        row = Setting(key=SECRET, value=PLAIN)
        assert row.stored_value is not None
        assert row.stored_value.startswith(f"{CIPHERTEXT_PREFIX}{key_a[1]}:")
        assert PLAIN not in row.stored_value
        assert row.value == PLAIN
        assert row.unreadable is False

    def test_the_row_key_is_the_associated_data(self, key_a: KeyEntry) -> None:
        row = Setting(key=SECRET, value=PLAIN)
        assert row.stored_value is not None
        assert decrypt(SECRET, row.stored_value).plaintext == PLAIN
        assert decrypt("ntfy_token", row.stored_value).status is DecryptStatus.UNREADABLE

    def test_value_before_key_in_the_kwargs_still_binds_the_key(self, key_a: KeyEntry) -> None:
        """A custom __init__ sets key first, so the setter knows the row's name."""
        row = Setting(value=PLAIN, key=SECRET)
        assert row.stored_value is not None
        assert row.stored_value.startswith(CIPHERTEXT_PREFIX)
        assert row.value == PLAIN

    def test_a_non_secret_key_is_stored_as_is(self, key_a: KeyEntry) -> None:
        row = Setting(key="app_name", value="MyGarage")
        assert row.stored_value == "MyGarage"
        assert row.value == "MyGarage"
        assert row.unreadable is False

    @pytest.mark.parametrize("blank", ["", None])
    def test_empty_and_none_are_stored_as_is(self, key_a: KeyEntry, blank: str | None) -> None:
        row = Setting(key=SECRET, value=blank)
        assert row.stored_value == blank
        assert row.value == blank
        row.value = PLAIN
        row.value = blank
        assert row.stored_value == blank
        assert row.unreadable is False

    def test_re_saving_the_same_value_under_the_current_key_leaves_the_row_alone(
        self, key_a: KeyEntry
    ) -> None:
        row = Setting(key=SECRET, value=PLAIN)
        before = row.stored_value
        row.value = PLAIN
        assert row.stored_value == before

    def test_a_new_value_is_re_encrypted(self, key_a: KeyEntry) -> None:
        row = Setting(key=SECRET, value=PLAIN)
        before = row.stored_value
        row.value = "another-token"
        assert row.stored_value != before
        assert row.value == "another-token"

    def test_an_unchanged_legacy_plaintext_is_rewritten_as_ciphertext(
        self, key_a: KeyEntry
    ) -> None:
        row = Setting(key=SECRET, stored_value=PLAIN)
        assert row.value == PLAIN  # legacy passes through
        row.value = PLAIN
        assert row.stored_value is not None
        assert row.stored_value.startswith(f"{CIPHERTEXT_PREFIX}{key_a[1]}:")
        assert row.value == PLAIN

    def test_an_unchanged_value_under_an_older_key_is_always_rewritten(
        self, key_a: KeyEntry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        row = Setting(key=SECRET, value=PLAIN)
        under_a = row.stored_value
        key_b = _new_key()
        _use_keys(monkeypatch, key_b[0], key_a[0])
        assert current_kid() == key_b[1]
        assert row.value == PLAIN  # the old key still decrypts
        row.value = PLAIN
        assert row.stored_value != under_a
        assert row.stored_value is not None
        assert row.stored_value.startswith(f"{CIPHERTEXT_PREFIX}{key_b[1]}:")
        assert row.value == PLAIN

    def test_a_value_that_is_already_ciphertext_is_refused(self, key_a: KeyEntry) -> None:
        stored = encrypt(SECRET, PLAIN)
        row = Setting(key=SECRET, value="")
        with pytest.raises(SettingCiphertextValue) as caught:
            row.value = stored
        assert isinstance(caught.value, ValueError)
        assert stored not in str(caught.value)
        assert row.stored_value == ""
        with pytest.raises(SettingCiphertextValue):
            Setting(key=SECRET, value=f"{CIPHERTEXT_PREFIX}typed-by-hand")

    def test_the_prefix_refusal_is_for_secret_keys_only(self, key_a: KeyEntry) -> None:
        row = Setting(key="app_name", value=f"{CIPHERTEXT_PREFIX}whatever")
        assert row.stored_value == f"{CIPHERTEXT_PREFIX}whatever"

    def test_stored_value_passes_raw_bytes_through(self, key_a: KeyEntry) -> None:
        stored = encrypt(SECRET, PLAIN)
        for row in (
            Setting(key=SECRET, stored_value=stored),
            Setting(stored_value=stored, key=SECRET, category="notifications"),
        ):
            assert row.stored_value == stored
            assert row.value == PLAIN
        assert Setting(key=SECRET, stored_value="legacy").stored_value == "legacy"

    def test_value_and_stored_value_together_are_refused(self, key_a: KeyEntry) -> None:
        with pytest.raises(TypeError):
            Setting(key=SECRET, value=PLAIN, stored_value=PLAIN)

    def test_a_secret_write_without_a_keyring_raises_and_changes_nothing(
        self, key_a: KeyEntry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        row = Setting(key=SECRET, stored_value="legacy-token")
        _use_keys(monkeypatch, "not-a-key")
        with pytest.raises(SettingsKeyUnavailable):
            row.value = "new-token"
        assert row.stored_value == "legacy-token"
        assert row.value == "legacy-token"  # plaintext keeps working
        assert Setting(key="app_name", value="still writes").stored_value == "still writes"

    def test_the_class_level_expression_is_the_raw_column(self) -> None:
        """select(Setting.value) and where(Setting.value == ...) see the stored form."""
        assert str(Setting.value == "x") == str(Setting.stored_value == "x")
        assert "settings.value" in str(select(Setting.value).where(Setting.value == "x"))


class TestUnreadable:
    def test_a_ciphertext_moved_onto_another_keys_row_reads_as_unreadable(
        self, key_a: KeyEntry
    ) -> None:
        """Plan test 7 at model level: the row key is bound in as associated data."""
        llm = Setting(key="llm_api_key", value="sk-live-123")
        moved = Setting(key="slack_webhook_url", stored_value=llm.stored_value)
        assert moved.value is None
        assert moved.unreadable is True

    def test_a_ciphertext_under_an_unknown_key_reads_as_unreadable(
        self, key_a: KeyEntry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        row = Setting(key=SECRET, value=PLAIN)
        _use_keys(monkeypatch, _new_key()[0])
        assert row.value is None
        assert row.unreadable is True

    def test_a_legacy_value_and_an_empty_one_are_not_unreadable(self, key_a: KeyEntry) -> None:
        assert Setting(key=SECRET, stored_value="plain").unreadable is False
        assert Setting(key=SECRET, stored_value="").unreadable is False
        assert Setting(key=SECRET, stored_value=None).unreadable is False

    def test_a_non_secret_key_is_never_unreadable(self, key_a: KeyEntry) -> None:
        row = Setting(key="app_name", stored_value=f"{CIPHERTEXT_PREFIX}00000000:AAAA")
        assert row.unreadable is False
        assert row.value == f"{CIPHERTEXT_PREFIX}00000000:AAAA"


def test_every_secret_key_round_trips(key_a: KeyEntry) -> None:
    for key in sorted(SECRET_SETTING_KEYS):
        row = Setting(key=key, value=f"value-of-{key}")
        assert row.stored_value is not None and row.stored_value.startswith(CIPHERTEXT_PREFIX)
        assert row.value == f"value-of-{key}"
