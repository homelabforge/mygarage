"""The toll tag create schema keeps the rules its response can't share.

A rule on the shared base runs on every stored row a response reads, so one a
legacy row breaks lives on the create instead.
"""

import datetime as dt

import pytest
from pydantic import ValidationError

from app.schemas.toll import TollTagCreate, TollTagResponse, TollTagUpdate

VIN = "1HGBH41JXMN109186"


def test_create_refuses_a_status_outside_the_vocabulary():
    """A guard: true today.

    Mutant: delete the base's validator without adding it to the create.
    """
    with pytest.raises(ValidationError, match="Status must be one of"):
        TollTagCreate(vin=VIN, toll_system="EZ TAG", tag_number="0012345678", status="lost")


def test_create_refuses_a_toll_system_of_only_spaces():
    """Spaces used to pass min_length and save as the system name."""
    with pytest.raises(ValidationError, match="at least 1 character"):
        TollTagCreate(vin=VIN, toll_system="   ", tag_number="0012345678")


def test_create_trims_and_collapses_the_toll_system():
    tag = TollTagCreate(vin=VIN, toll_system="  Via   Verde ", tag_number="0012345678")
    assert tag.toll_system == "Via Verde"


def test_create_normalizes_a_padded_known_spelling():
    tag = TollTagCreate(vin=VIN, toll_system=" ez   tag ", tag_number="0012345678")
    assert tag.toll_system == "EZ TAG"


def test_create_counts_length_after_trimming():
    name = "A" * 50
    tag = TollTagCreate(vin=VIN, toll_system=f"  {name}  ", tag_number="0012345678")
    assert tag.toll_system == name
    with pytest.raises(ValidationError, match="at most 50 characters"):
        TollTagCreate(vin=VIN, toll_system="A" * 51, tag_number="0012345678")


def test_update_refuses_a_toll_system_of_only_spaces():
    with pytest.raises(ValidationError, match="at least 1 character"):
        TollTagUpdate(toll_system="   ")


def test_update_normalizes_known_spellings_like_create():
    """An edit used to store "eztag" as typed."""
    assert TollTagUpdate(toll_system=" eztag ").toll_system == "EZ TAG"


def test_update_tidies_an_off_list_name_and_counts_length_after():
    assert TollTagUpdate(toll_system="  Via   Verde ").toll_system == "Via Verde"
    name = "A" * 50
    assert TollTagUpdate(toll_system=f"  {name}  ").toll_system == name
    with pytest.raises(ValidationError, match="at most 50 characters"):
        TollTagUpdate(toll_system="A" * 51)


def test_update_still_refuses_null_and_keeps_omission():
    with pytest.raises(ValidationError, match="cannot be null"):
        TollTagUpdate(toll_system=None)
    assert "toll_system" not in TollTagUpdate(status="active").model_dump(exclude_unset=True)


def test_a_stored_blank_toll_system_still_reads():
    """A guard: true today.

    Mutant: move the blank check onto TollTagBase, which the response shares.
    """
    row = TollTagResponse.model_validate(
        {
            "id": 1,
            "vin": VIN,
            "toll_system": "   ",
            "tag_number": "0012345678",
            "status": "active",
            "notes": None,
            "created_at": dt.datetime(2026, 10, 4, tzinfo=dt.UTC),
        }
    )
    assert row.toll_system == "   "
