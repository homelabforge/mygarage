"""The topic map create schema keeps the rules its response can't share.

A rule on the shared base runs on every stored row a response reads, so one a
legacy row breaks lives on the create instead. The PATCH revalidates the merged
row through the create, so it keeps them too.
"""

import pytest
from pydantic import ValidationError

from app.schemas.livelink_topic_map import TopicMapCreate


def test_create_refuses_a_wildcard_topic():
    """A guard: true today.

    Mutant: delete the base's validator without adding it to the create.
    """
    with pytest.raises(ValidationError, match="must be exact"):
        TopicMapCreate(device_id="gw01", topic="wican/+/level", param_key="LEVEL")


def test_create_refuses_telemetry_without_a_param_key():
    """A guard: true today.

    Mutant: delete the base's validator without adding it to the create.
    """
    with pytest.raises(ValidationError, match="param_key is required"):
        TopicMapCreate(device_id="gw01", topic="wican/gw01/level", role="telemetry")


def test_a_blank_param_key_on_telemetry_is_refused():
    """P2E3: " " used to canonicalise to "_" and register a parameter called `_`."""
    with pytest.raises(ValidationError, match="param_key is required"):
        TopicMapCreate(device_id="gw01", topic="wican/gw01/level", role="telemetry", param_key=" ")


def test_a_blank_param_key_on_a_status_row_is_none():
    row = TopicMapCreate(device_id="gw01", topic="wican/gw01/status", role="status", param_key="  ")

    assert row.param_key is None


def test_a_padded_param_key_is_stripped_before_it_is_canonicalised():
    """Padding used to become underscores: " level pct " was `_LEVEL_PCT_`."""
    row = TopicMapCreate(device_id="gw01", topic="wican/gw01/level", param_key=" level pct ")

    assert row.param_key == "LEVEL_PCT"
