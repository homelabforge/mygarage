"""Inject a runtime <base href> into the SPA shell for subpath hosting (#107).

The frontend is built with Vite ``base: './'`` (relative asset + dynamic-import
resolution). A <base href> anchors those relative URLs at every route — WITHOUT
it, a deep-link reload like /vehicles/ABC would fetch entry assets from
/vehicles/assets/... and the SPA would never start. We therefore ALWAYS inject
one: "/" at root (functionally identical to the old absolute output, one added
tag) and "/{prefix}/" when MYGARAGE_ROOT_PATH is set.
"""

from __future__ import annotations

import re

_HEAD_RE = re.compile(r"<head\b[^>]*>", re.IGNORECASE)


def inject_base_href(html: str, root_path: str) -> str:
    """Insert ``<base href="{root_path}/">`` after <head>. Idempotent."""
    if "<base " in html:
        return html
    href = f"{root_path}/" if root_path else "/"
    tag = f'<base href="{href}">'
    return _HEAD_RE.sub(lambda m: m.group(0) + "\n    " + tag, html, count=1)
