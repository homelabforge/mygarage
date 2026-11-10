"""The shared lenient read for a vocabulary field on a response.

A stored value outside the vocabulary reads as null, or as the vocabulary's own
"unknown" for a field that stays required, and logs once. The schema stays the
vocabulary's union, so the generated TypeScript doesn't widen to `string`.
"""

import logging
from typing import Annotated, Literal

import pytest
from pydantic import BaseModel, BeforeValidator

from app.utils import lenient_vocab
from app.utils.lenient_vocab import LenientVocab, lenient_reader

_Craft = Literal["Car", "Boat"]
_Status = Literal["online", "offline", "unknown"]
type _CraftAlias = Literal["Car", "Boat"]

_LOGGER = "app.utils.lenient_vocab"


@pytest.fixture(autouse=True)
def _nothing_warned_yet(monkeypatch: pytest.MonkeyPatch) -> None:
    # The warn-once set lives for the process, so each test starts it empty.
    # Raises if `_warned` is renamed, rather than leaking state between tests.
    monkeypatch.setattr(lenient_vocab, "_warned", set())


def _vessel():  # inferred, so the test sees the fields
    """A response with a nullable lenient field, declared after the row's id.

    Built per test rather than at import, so a reader that isn't there yet
    fails the test instead of the collection.
    """

    class Vessel(BaseModel):
        id: int
        notes: str | None = None
        craft: Annotated[
            _Craft | None, BeforeValidator(lenient_reader(_Craft)), LenientVocab(None)
        ] = None

    return Vessel


def _device():  # inferred, so the test sees the fields
    """A response whose status stays required: a bad value reads as "unknown"."""

    class Device(BaseModel):
        vin: str | None = None
        status: Annotated[
            _Status,
            BeforeValidator(lenient_reader(_Status, fallback="unknown")),
            LenientVocab("unknown"),
        ] = "unknown"

    return Device


def test_a_value_in_the_vocabulary_reads_as_itself() -> None:
    assert _vessel().model_validate({"id": 1, "craft": "Boat"}).craft == "Boat"
    assert _device().model_validate({"status": "offline"}).status == "offline"


def test_none_reads_as_none_or_as_the_fallback() -> None:
    assert _vessel().model_validate({"id": 1, "craft": None}).craft is None
    assert _device().model_validate({"status": None}).status == "unknown"


def test_a_bad_value_reads_as_null_and_warns_naming_the_model_field_and_row(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        vessel = _vessel().model_validate(
            {"id": 7, "notes": "the secret route", "craft": "Hovercraft"}
        )
    assert vessel.craft is None
    [record] = caplog.records
    message = record.getMessage()
    assert record.levelno == logging.WARNING
    assert "Vessel.craft" in message
    assert "Hovercraft" in message
    assert "id=7" in message
    # Names the row, never the rest of it.
    assert "secret route" not in message


def test_a_second_read_of_the_same_bad_value_logs_nothing_new(
    caplog: pytest.LogCaptureFixture,
) -> None:
    vessel = _vessel()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert vessel.model_validate({"id": 1, "craft": "Hovercraft"}).craft is None
        assert vessel.model_validate({"id": 2, "craft": "Hovercraft"}).craft is None
        assert vessel.model_validate({"id": 1, "craft": "Hovercraft"}).craft is None
        # A different value is news.
        assert vessel.model_validate({"id": 3, "craft": "Zeppelin"}).craft is None
    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 2
    assert "Hovercraft" in messages[0]
    assert "Zeppelin" in messages[1]


def test_a_long_bad_value_is_remembered_by_what_the_log_shows(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The warn-once set keys on the first 80 characters of the repr, the same
    # cut the log line shows, so a run of huge bad values can't grow it without
    # bound. Two values that only differ past that cut log once.
    vessel = _vessel()
    stem = "Hovercraft" * 20
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert vessel.model_validate({"id": 1, "craft": stem + "A"}).craft is None
        assert vessel.model_validate({"id": 2, "craft": stem + "B"}).craft is None
    assert len(caplog.records) == 1
    assert [len(value) for _model, _field, value in lenient_vocab._warned] == [80]


def test_with_a_fallback_a_bad_value_reads_as_unknown(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        device = _device().model_validate({"vin": "VBAD1", "status": "rebooting"})
    assert device.status == "unknown"
    [record] = caplog.records
    assert "Device.status" in record.getMessage()
    assert "VBAD1" in record.getMessage()


def test_a_value_that_cannot_be_looked_up_reads_as_the_fallback() -> None:
    # A list out of a JSON column can't be hashed, so it can't be in the set.
    assert _vessel().model_validate({"id": 1, "craft": ["Car"]}).craft is None


def test_the_vocabulary_can_be_a_type_alias() -> None:
    class Ferry(BaseModel):
        craft: Annotated[
            _CraftAlias | None, BeforeValidator(lenient_reader(_CraftAlias)), LenientVocab(None)
        ] = None

    assert Ferry.model_validate({"craft": "Car"}).craft == "Car"
    assert Ferry.model_validate({"craft": "Hovercraft"}).craft is None


def test_the_schema_is_the_vocabulary_or_null() -> None:
    # openapi-typescript turns this into `"Car" | "Boat" | null`, not `string`.
    for mode in ("validation", "serialization"):
        craft = _vessel().model_json_schema(mode=mode)["properties"]["craft"]
        assert craft["anyOf"] == [
            {"enum": ["Car", "Boat"], "type": "string"},
            {"type": "null"},
        ]
        # The fallback keeps a required status required: no null in its schema.
        status = _device().model_json_schema(mode=mode)["properties"]["status"]
        assert status["enum"] == ["online", "offline", "unknown"]
        assert "anyOf" not in status


def test_a_fallback_must_be_in_the_vocabulary() -> None:
    with pytest.raises(ValueError, match="rebooting"):
        lenient_reader(_Status, fallback="rebooting")


def test_the_vocabulary_must_be_a_literal() -> None:
    with pytest.raises(TypeError, match="Literal"):
        lenient_reader(str)
    with pytest.raises(TypeError, match="Literal"):
        lenient_reader(_Craft | None)
