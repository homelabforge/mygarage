#!/usr/bin/env python3
"""Capture MyGarage app screenshots for the HA packaging PR."""

from __future__ import annotations

import os
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots" / "pr" / "ha-packaging"
APP = os.environ.get("MYGARAGE_URL", "http://127.0.0.1:3000")


def wait(url: str, timeout: int = 90) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=3)
            if r.status_code < 500:
                return
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError(f"Not ready: {url}")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    wait(f"{APP.rstrip('/')}/")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})

        page.goto(f"{APP.rstrip('/')}/", wait_until="networkidle")
        page.wait_for_timeout(2000)
        page.screenshot(path=str(OUT / "app-dashboard.png"), full_page=False)
        print("wrote app-dashboard.png")

        page.goto(
            f"{APP.rstrip('/')}/vehicles/1HGBH41JXMN109186",
            wait_until="networkidle",
        )
        page.wait_for_timeout(2000)
        page.screenshot(path=str(OUT / "app-vehicle.png"), full_page=False)
        print("wrote app-vehicle.png")

        page.goto(f"{APP.rstrip('/')}/settings", wait_until="networkidle")
        page.wait_for_timeout(1000)
        page.locator("button, a, [role=tab]").filter(has_text="Integrations").first.click()
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT / "app-integrations.png"), full_page=False)
        print("wrote app-integrations.png")

        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
