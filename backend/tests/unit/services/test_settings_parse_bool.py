"""parse_bool reads a switch setting's text with one vocabulary (R5).

On is true/1/yes/on and off is false/0/no/off, in any case and with the
surrounding whitespace ignored. Blank text, or none at all, reads as the
caller's default. Any other text is off: an unknown word never turns a
feature on.
"""

import pytest

from app.services.settings_service import SWITCH_OFF_VALUES, SWITCH_ON_VALUES, parse_bool

pytestmark = pytest.mark.unit


def test_the_vocabulary_is_r5s() -> None:
    assert frozenset({"true", "1", "yes", "on"}) == SWITCH_ON_VALUES
    assert frozenset({"false", "0", "no", "off"}) == SWITCH_OFF_VALUES


@pytest.mark.parametrize("default", [False, True])
@pytest.mark.parametrize(
    "text", ["true", "1", "yes", "on", "TRUE", "Yes", "oN", " on ", "\ttrue\n"]
)
def test_on_text_is_on_whatever_the_default(text: str, default: bool) -> None:
    assert parse_bool(text, default) is True


@pytest.mark.parametrize("default", [False, True])
@pytest.mark.parametrize(
    "text", ["false", "0", "no", "off", "FALSE", "No", "OfF", " off ", "\n0\t"]
)
def test_off_text_is_off_whatever_the_default(text: str, default: bool) -> None:
    assert parse_bool(text, default) is False


@pytest.mark.parametrize("default", [False, True])
@pytest.mark.parametrize("text", [None, "", " ", "\t\n "])
def test_blank_or_none_is_the_default(text: str | None, default: bool) -> None:
    assert parse_bool(text, default) is default


@pytest.mark.parametrize("default", [False, True])
@pytest.mark.parametrize("text", ["enabled", "y", "t", "2", "true!", "o n", "None"])
def test_any_other_text_is_off(text: str, default: bool) -> None:
    assert parse_bool(text, default) is False


def test_default_can_be_passed_by_name() -> None:
    assert parse_bool(None, default=True) is True
