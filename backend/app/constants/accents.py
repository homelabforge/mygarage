"""UI accent constants — the six selectable theme accents.

The single source of truth for backend-side accent validation. Mirrors the
frontend's ``src/constants/accents.ts`` (``ACCENT_KEYS`` / ``DEFAULT_ACCENT``);
keep the two in sync when adding or removing an accent.
"""

SUPPORTED_ACCENTS: set[str] = {"blue", "amber", "teal", "red", "violet", "green"}

DEFAULT_ACCENT: str = "blue"
