#!/usr/bin/env python3
"""Onboard local HA and configure the MyGarage integration for screenshots."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HA_URL = "http://localhost:8123"
CLIENT_ID = f"{HA_URL}/"
HOST = "http://mygarage-mock:8686"
API_KEY = "mg_widget_screenshot_key"
TOKEN_OUT = Path(__file__).resolve().parents[1] / "docker_data" / "ha_refresh_token.txt"
USERNAME = "admin"
PASSWORD = "screenshots-only"


def http_json(
    method: str,
    path: str,
    body: dict | None = None,
    token: str | None = None,
    form: dict | None = None,
) -> dict | list | str | None:
    data = None
    headers: dict[str, str] = {}
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{HA_URL.rstrip('/')}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=60) as resp:
        raw = resp.read()
        if not raw:
            return None
        ctype = resp.headers.get("Content-Type", "")
        if "application/json" in ctype or raw[:1] in (b"{", b"["):
            return json.loads(raw)
        return raw.decode()


def wait_ha(timeout: int = 180) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{HA_URL}/api/onboarding", timeout=3)
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError("Home Assistant did not become ready in time")


def onboarding_steps() -> list[dict]:
    steps = http_json("GET", "/api/onboarding")
    assert isinstance(steps, list)
    return steps


def step_done(name: str) -> bool:
    return any(s.get("step") == name and s.get("done") for s in onboarding_steps())


def create_user() -> tuple[str, str]:
    user = http_json(
        "POST",
        "/api/onboarding/users",
        {
            "client_id": CLIENT_ID,
            "name": "Screenshot Admin",
            "username": USERNAME,
            "password": PASSWORD,
            "language": "en",
        },
    )
    assert isinstance(user, dict)
    token_resp = http_json(
        "POST",
        "/auth/token",
        form={
            "grant_type": "authorization_code",
            "code": user["auth_code"],
            "client_id": CLIENT_ID,
        },
    )
    assert isinstance(token_resp, dict)
    return token_resp["access_token"], token_resp["refresh_token"]


def login_password() -> tuple[str, str]:
    """Obtain tokens via auth login flow (HA ≥2024)."""
    # Start login flow
    flow = http_json(
        "POST",
        "/auth/login_flow",
        {
            "client_id": CLIENT_ID,
            "handler": ["homeassistant", None],
            "redirect_uri": CLIENT_ID,
        },
    )
    assert isinstance(flow, dict)
    result = http_json(
        "POST",
        f"/auth/login_flow/{flow['flow_id']}",
        {
            "client_id": CLIENT_ID,
            "username": USERNAME,
            "password": PASSWORD,
        },
    )
    assert isinstance(result, dict)
    if "result" not in result:
        raise RuntimeError(f"Login failed: {result}")
    token_resp = http_json(
        "POST",
        "/auth/token",
        form={
            "grant_type": "authorization_code",
            "code": result["result"],
            "client_id": CLIENT_ID,
        },
    )
    assert isinstance(token_resp, dict)
    return token_resp["access_token"], token_resp["refresh_token"]


def finish_onboarding(access_token: str) -> None:
    if not step_done("core_config"):
        http_json(
            "POST",
            "/api/onboarding/core_config",
            {
                "location_name": "Screenshot Home",
                "language": "en",
                "country": "US",
                "timezone": "America/New_York",
                "unit_system": "metric",
                "currency": "USD",
            },
            token=access_token,
        )
    if not step_done("analytics"):
        try:
            http_json("POST", "/api/onboarding/analytics", {}, token=access_token)
        except urllib.error.HTTPError:
            pass
    if not step_done("integration"):
        try:
            http_json(
                "POST",
                "/api/onboarding/integration",
                {"client_id": CLIENT_ID, "redirect_uri": CLIENT_ID},
                token=access_token,
            )
        except urllib.error.HTTPError:
            pass


def save_refresh(refresh: str) -> None:
    TOKEN_OUT.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_OUT.write_text(refresh.strip() + "\n", encoding="utf-8")
    print(f"Wrote refresh token to {TOKEN_OUT}")


def configure_integration(access_token: str) -> None:
    entries = http_json("GET", "/api/config/config_entries/entry", token=access_token)
    assert isinstance(entries, list)
    if any(e.get("domain") == "mygarage" for e in entries):
        print("MyGarage config entry already present")
        return

    flow = http_json(
        "POST",
        "/api/config/config_entries/flow",
        {"handler": "mygarage", "show_advanced_options": False},
        token=access_token,
    )
    assert isinstance(flow, dict)
    result = http_json(
        "POST",
        f"/api/config/config_entries/flow/{flow['flow_id']}",
        {
            "host": HOST,
            "api_key": API_KEY,
            "webhook_token": "",
        },
        token=access_token,
    )
    assert isinstance(result, dict)
    if result.get("type") != "create_entry":
        raise RuntimeError(f"Config flow failed: {json.dumps(result, indent=2)}")
    print(f"Configured MyGarage entry: {result.get('title')}")
    time.sleep(5)


def main() -> int:
    wait_ha()
    steps = onboarding_steps()
    user_done = any(s.get("step") == "user" and s.get("done") for s in steps)

    if not user_done:
        access, refresh = create_user()
    elif TOKEN_OUT.is_file():
        refresh = TOKEN_OUT.read_text(encoding="utf-8").strip()
        token_resp = http_json(
            "POST",
            "/auth/token",
            form={
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": CLIENT_ID,
            },
        )
        assert isinstance(token_resp, dict)
        access = token_resp["access_token"]
        print("Reused existing refresh token")
    else:
        access, refresh = login_password()

    save_refresh(refresh)
    finish_onboarding(access)
    configure_integration(access)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
