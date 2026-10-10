"""checked_redirect_uri: the one rule every writer of the SSO callback pin uses.

Blank or an absolute http(s) URL, with no whitespace or control character
inside. urlsplit quietly drops tabs and newlines before it parses, so its view
of the URL alone said "https://x\\n.evil" was fine while the raw value got stored.
"""

import pytest

from app.services.oidc.config import checked_redirect_uri

PINNED = "https://garage.example.com/mygarage/api/auth/oidc/callback"


@pytest.mark.unit
class TestCheckedRedirectUri:
    @pytest.mark.parametrize("blank", ["", "   ", "\t\n"], ids=["empty", "spaces", "tab-newline"])
    def test_blank_is_blank(self, blank: str) -> None:
        assert checked_redirect_uri(blank) == ""

    @pytest.mark.parametrize(
        "good",
        [PINNED, "http://garage.lan:8686/api/auth/oidc/callback", "HTTPS://Garage.example.com/cb"],
        ids=["https", "http-with-port", "upper-case-scheme"],
    )
    def test_an_absolute_http_url_is_kept(self, good: str) -> None:
        assert checked_redirect_uri(good) == good

    def test_the_ends_are_stripped(self) -> None:
        assert checked_redirect_uri(f" \t{PINNED}\n ") == PINNED

    @pytest.mark.parametrize(
        "bad",
        [
            "ftp://garage.example.com/cb",
            "garage.example.com/cb",
            "https://",
            "https:///cb",
            "https://[garage.example.com",
            "https://garage.example.com\n.evil/cb",
            "https://garage.example.com\r.evil/cb",
            "https://garage.example.com\t.evil/cb",
            "https://garage .example.com/cb",
            "https://garage.example.com/c b",
            "https://garage.example.com/\x00cb",
            "https://garage.example.com/\x1bcb",
            "https://garage.example.com/\x7fcb",
            "https://garage.example.com/\x9bcb",
            "https://garage.example.com/ cb",
        ],
        ids=[
            "ftp",
            "no-scheme",
            "no-host",
            "empty-host",
            "unparseable",
            "newline",
            "carriage-return",
            "tab",
            "space-in-host",
            "space-in-path",
            "nul",
            "escape",
            "delete",
            "c1-csi",
            "no-break-space",
        ],
    )
    def test_anything_else_is_refused(self, bad: str) -> None:
        with pytest.raises(ValueError, match="must be blank or an absolute http\\(s\\) URL"):
            checked_redirect_uri(bad)
