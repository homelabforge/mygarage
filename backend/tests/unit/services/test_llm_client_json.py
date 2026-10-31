"""extract_json_object turns any reply it can't read into the 502, never a 500."""

import pytest
from fastapi import HTTPException

from app.services.llm_client import extract_json_object

# Past Python's 4300-digit int limit, so json.loads raises a plain ValueError,
# not a JSONDecodeError.
_HUGE_INT = "9" * 4301


@pytest.mark.parametrize(
    "reply",
    [
        f'{{"odometer": {_HUGE_INT}}}',
        f'Here you go: {{"odometer": {_HUGE_INT}}} hope that helps',
    ],
    ids=["bare-json", "json-in-prose"],
)
def test_an_int_too_long_to_parse_is_a_502(reply: str) -> None:
    # Bare, the first parse has to fall through; in prose only the second parse sees it.
    with pytest.raises(HTTPException) as caught:
        extract_json_object(reply)
    assert caught.value.status_code == 502
    assert caught.value.detail == "LLM response JSON was invalid"
