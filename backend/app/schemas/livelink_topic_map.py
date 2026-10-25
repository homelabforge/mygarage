"""Schemas for the topic-map admin API."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from app.schemas._nullability import reject_null
from app.schemas.livelink import DEVICE_ID_PATTERN
from app.utils.lenient_vocab import LenientVocab, lenient_reader

TopicMapRole = Literal["telemetry", "status"]
# For TopicMapResponse: `role` has no CHECK, so a role we don't know reads as
# null instead of 500ing the whole topic-map list.
LenientTopicMapRole = Annotated[
    TopicMapRole | None, BeforeValidator(lenient_reader(TopicMapRole)), LenientVocab(None)
]


def _exact_topic(v: str) -> str:
    """Mapped topics are exact. See LiveLinkTopicMap's docstring."""
    if "+" in v or "#" in v:
        raise ValueError("Mapped topics must be exact; + and # are not allowed")
    return v


class TopicMapBase(BaseModel):
    """Fields shared by create and update."""

    device_id: str = Field(..., max_length=20)
    topic: str = Field(..., max_length=255)
    role: TopicMapRole = "telemetry"
    param_key: str | None = Field(None, max_length=100)
    value_path: str | None = Field(None, max_length=100)
    unit: str | None = Field(None, max_length=20)
    param_class: str | None = Field(None, max_length=50)
    scale: Decimal = Decimal(1)
    value_offset: Decimal = Decimal(0)
    enabled: bool = True

    @field_validator("param_key")
    @classmethod
    def canonicalize(cls, v: str | None) -> str | None:
        """Match the uppercase canonicalization every ingest path applies.

        Stripped first and blank is None, so a telemetry row still has to name
        a key: " " used to become "_" and register a parameter called that.
        """
        if v is None:
            return None
        v = v.strip()
        return v.upper().replace(" ", "_") if v else None


class TopicMapCreate(TopicMapBase):
    """Request body for POST."""

    #: Here and not on the base: `TopicMapResponse` shares the base, and a
    #: pattern there would run on every stored row during response validation,
    #: so one row written before this rule existed would 500 the whole list.
    device_id: str = Field(..., max_length=20, pattern=DEVICE_ID_PATTERN)

    # Here for the same reason as device_id: no CHECK holds either rule, so a
    # stored row can break them. The PATCH revalidates the merged row through
    # this class, so it keeps both.
    @field_validator("topic")
    @classmethod
    def reject_wildcards(cls, v: str) -> str:
        """Mapped topics are exact. See LiveLinkTopicMap's docstring."""
        return _exact_topic(v)

    @model_validator(mode="after")
    def param_key_required_for_telemetry(self) -> TopicMapCreate:
        """Only a status row may omit param_key."""
        if self.role == "telemetry" and not self.param_key:
            raise ValueError("param_key is required when role is 'telemetry'")
        return self


class TopicMapUpdate(BaseModel):
    """Request body for PATCH. Every field optional."""

    model_config = ConfigDict(extra="forbid")

    param_key: str | None = None
    value_path: str | None = None
    unit: str | None = None
    param_class: str | None = None
    scale: Decimal | None = None
    value_offset: Decimal | None = None
    enabled: bool | None = None

    # NOT NULL columns: omitted keeps the stored value, null is a 422.
    _no_null = reject_null("enabled", "scale", "value_offset")


class TopicMapResponse(TopicMapBase):
    """One stored row."""

    model_config = ConfigDict(from_attributes=True)

    # Text without the input rules, so a stored string past today's limits
    # still reads instead of 500ing (test_response_contract).
    device_id: str
    topic: str
    param_key: str | None = None
    value_path: str | None = None
    unit: str | None = None
    param_class: str | None = None
    # A role we don't know reads as null, so one odd row can't 500 the list.
    role: LenientTopicMapRole = "telemetry"
    id: int


class TopicDiscoveryRequest(BaseModel):
    """Body for a discovery run."""

    prefix: str = Field(..., max_length=255)
    seconds: int = Field(15, ge=1, le=60)


class PresetReadingInfo(BaseModel):
    """One reading a preset's sensor publishes."""

    suffix: str = Field(..., description="Key into PresetApplyRequest.topics")
    name: str
    unit: str | None
    default_topic: str = Field(
        ..., description="Last topic segment in the reference layout; suggested when none is heard"
    )
    keywords: list[str] = Field(
        ..., description="Lowercase substrings that identify this reading's topic in any layout"
    )
    required: bool


class PresetInfo(BaseModel):
    """A sensor template, as the add-sensor form needs it."""

    name: str
    title: str
    description: str
    kind: str
    readings: list[PresetReadingInfo]


class PresetApplyRequest(BaseModel):
    """Body for adding one sensor from a preset.

    Which readings exist, and which are required, is the preset's, so the
    route checks `topics` against it. What does not depend on the preset is
    checked here.
    """

    label: str = Field(..., min_length=1, max_length=60)
    vin: str | None = Field(None, min_length=17, max_length=17)
    topics: dict[str, str] = Field(
        ...,
        description=(
            "The exact topic carrying each reading, keyed by reading suffix "
            "(LEVEL_PCT). A reading left out or blank is not mapped."
        ),
    )

    @field_validator("label")
    @classmethod
    def label_not_blank(cls, v: str) -> str:
        """Every reading is named after the sensor ("Front tank level")."""
        v = v.strip()
        if not v:
            raise ValueError("A sensor needs a name")
        return v

    @field_validator("topics")
    @classmethod
    def exact_distinct_topics(cls, v: dict[str, str]) -> dict[str, str]:
        """Blank entries are dropped. The rest are exact, and each is used
        once: one topic carries one reading."""
        topics = {suffix: topic.strip() for suffix, topic in v.items() if topic.strip()}
        for topic in topics.values():
            if len(topic) > 255:
                raise ValueError("A topic is at most 255 characters")
            _exact_topic(topic)
        if len(set(topics.values())) != len(topics):
            raise ValueError("Each reading needs its own topic")
        return topics
