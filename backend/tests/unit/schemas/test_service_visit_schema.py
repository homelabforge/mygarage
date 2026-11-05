"""The line item create schema keeps the rules its response can't share.

A rule on the shared base runs on every stored row a response reads, so one a
legacy row breaks lives on the create instead.
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.recall import RecallResponse
from app.schemas.service_visit import (
    ServiceLineItemCreate,
    ServiceLineItemResponse,
    ServiceLineItemUpdate,
)


def test_create_refuses_a_maintenance_type_that_is_not_a_code():
    """A guard: true today.

    Mutant: delete the base's validator without adding it to the create.
    """
    with pytest.raises(ValidationError, match="maintenance_type"):
        ServiceLineItemCreate(description="Oil change", maintenance_type="Oil Change")


# Recall and warranty links (D8): a link needs its flag on the way in, but a
# stored row that breaks that still reads.


@pytest.mark.parametrize(
    ("flag", "link"), [("is_recall", "recall_id"), ("is_warranty", "warranty_id")]
)
def test_create_refuses_a_link_without_its_flag(flag: str, link: str) -> None:
    with pytest.raises(ValidationError, match=flag):
        ServiceLineItemCreate.model_validate({"description": "x", link: 3})
    with pytest.raises(ValidationError, match=flag):
        ServiceLineItemCreate.model_validate({"description": "x", flag: False, link: 3})


@pytest.mark.parametrize(
    ("flag", "link"), [("is_recall", "recall_id"), ("is_warranty", "warranty_id")]
)
def test_create_takes_a_flag_with_or_without_a_link(flag: str, link: str) -> None:
    linked = ServiceLineItemCreate.model_validate({"description": "x", flag: True, link: 3})
    assert (getattr(linked, flag), getattr(linked, link)) == (True, 3)
    bare = ServiceLineItemCreate.model_validate({"description": "x", flag: True})
    assert (getattr(bare, flag), getattr(bare, link)) == (True, None)


@pytest.mark.parametrize(
    ("flag", "link"), [("is_recall", "recall_id"), ("is_warranty", "warranty_id")]
)
def test_update_refuses_a_link_with_its_flag_sent_false(flag: str, link: str) -> None:
    with pytest.raises(ValidationError, match=flag):
        ServiceLineItemUpdate.model_validate({"id": 1, "description": "x", flag: False, link: 3})


@pytest.mark.parametrize(
    ("flag", "link"), [("is_recall", "recall_id"), ("is_warranty", "warranty_id")]
)
def test_update_takes_a_link_with_its_flag_omitted(flag: str, link: str) -> None:
    """Omitted keeps the stored flag, so {id, recall_id} is fine."""
    item = ServiceLineItemUpdate.model_validate({"id": 1, "description": "x", link: 3})
    assert getattr(item, link) == 3
    assert flag not in item.model_fields_set


@pytest.mark.parametrize(
    ("flag", "link"), [("is_recall", "recall_id"), ("is_warranty", "warranty_id")]
)
def test_update_refuses_a_new_item_link_without_its_flag(flag: str, link: str) -> None:
    """A new item has no stored flag to keep, so omitted means false."""
    with pytest.raises(ValidationError, match=flag):
        ServiceLineItemUpdate.model_validate({"description": "x", link: 3})


@pytest.mark.parametrize("flag", ["is_recall", "is_warranty"])
def test_update_refuses_a_null_flag(flag: str) -> None:
    with pytest.raises(ValidationError, match=flag):
        ServiceLineItemUpdate.model_validate({"id": 1, "description": "x", flag: None})


def test_a_stored_link_without_its_flag_still_reads() -> None:
    """The rule is on the write schemas only, so a bad row can't 500 the visit."""
    item = ServiceLineItemResponse.model_validate(
        {
            "id": 1,
            "visit_id": 1,
            "description": "x",
            "created_at": datetime(2026, 3, 1),
            "is_recall": False,
            "recall_id": 3,
            "is_warranty": False,
            "warranty_id": 4,
        }
    )
    assert (item.recall_id, item.warranty_id) == (3, 4)
    assert item.recall_summary is None
    assert item.warranty_summary is None


def test_recall_resolved_via_reads_unknown_as_null() -> None:
    base = {
        "id": 1,
        "vin": "1HGCM82633A004352",
        "component": "AIR BAGS",
        "summary": "s",
        "is_resolved": True,
        "created_at": datetime(2026, 3, 1),
    }
    assert RecallResponse.model_validate(
        {**base, "resolved_via": "service_visit"}
    ).resolved_via == ("service_visit")
    assert RecallResponse.model_validate({**base, "resolved_via": "telepathy"}).resolved_via is None
    read = RecallResponse.model_validate(base)
    assert read.resolved_via is None
    assert read.linked_visit is None


# The description is trimmed on the way in, so "Recall " saves as "Recall".


@pytest.mark.parametrize("schema", [ServiceLineItemCreate, ServiceLineItemUpdate])
def test_write_schemas_trim_the_description(
    schema: type[ServiceLineItemCreate] | type[ServiceLineItemUpdate],
) -> None:
    assert schema.model_validate({"description": "  Recall \n"}).description == "Recall"
    # Padding doesn't count toward the 200 cap.
    padded = schema.model_validate({"description": " " + "x" * 200 + " "})
    assert padded.description == "x" * 200


@pytest.mark.parametrize("schema", [ServiceLineItemCreate, ServiceLineItemUpdate])
def test_write_schemas_refuse_a_blank_description(
    schema: type[ServiceLineItemCreate] | type[ServiceLineItemUpdate],
) -> None:
    with pytest.raises(ValidationError, match="description"):
        schema.model_validate({"description": "   "})


def test_a_stored_padded_description_reads_as_saved() -> None:
    """The trim is on the write schemas only."""
    item = ServiceLineItemResponse.model_validate(
        {"id": 1, "visit_id": 1, "description": "Recall ", "created_at": datetime(2026, 3, 1)}
    )
    assert item.description == "Recall "
