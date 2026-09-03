"""The analytics PDF has no tire section, on purpose, and this pins that.

Spec B ships tire analytics to the PAGE only. The reason is upgrade day: after
migration 097 most tires answer `nothing_bounded`, so an exported tire section
would be a page of blanks in a document people archive and re-read months
later, long after the on-screen prompts that explain the blanks are gone.

"Either the PDF has it or it does not" is not a decision: two implementations
would satisfy it and no test could tell them apart, which is how a page and its
own export come to disagree. This asserts the choice, so adding a tire section
later is a deliberate act that has to delete a test rather than a drift nobody
notices.

It reads the headings MECHANICALLY, from the one call the module uses to emit
them, rather than trusting a hand-written list of section names to have stayed
current.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_PDF_MODULES = (
    Path("app/utils/pdf_vehicle_report.py"),
    Path("app/utils/pdf_garage_report.py"),
)

#: Every quantity the tire surface names. Deliberately wider than "tire": a
#: section called "Tread depth" or "Wear projection" would be the same
#: omission, and a grep for the word "tire" alone would not see it.
_TIRE_WORDS = re.compile(r"\btire|\btread|\bwear\b|\brotation\b", re.IGNORECASE)


def _section_headers(source: str) -> list[str]:
    """Every literal passed to `make_section_header` in a module.

    Guard-the-guard: `test_the_enumerator_finds_a_known_section` asserts this
    returns a heading that is definitely there, so a refactor that renames the
    helper cannot quietly turn this file into a test of nothing.
    """
    headers: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name != "make_section_header":
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                headers.append(arg.value)
            elif isinstance(arg, ast.JoinedStr):
                headers.extend(
                    v.value
                    for v in arg.values
                    if isinstance(v, ast.Constant) and isinstance(v.value, str)
                )
    return headers


@pytest.mark.parametrize("module", _PDF_MODULES, ids=lambda p: p.name)
def test_no_pdf_section_is_about_tires(module: Path):
    offenders = [h for h in _section_headers(module.read_text()) if _TIRE_WORDS.search(h)]
    assert offenders == [], (
        f"{module.name} grew a tire section: {offenders}. Tire analytics are "
        "page-only for v3.3.0 (spec B). If that decision has changed, delete "
        "this test in the same commit that adds the section, and update the "
        "changelog line that tells users the PDF does not include them."
    )


def test_the_enumerator_finds_a_known_section():
    """The guard on the guard.

    Without this, renaming `make_section_header` would make `_section_headers`
    return nothing, every assertion above would pass vacuously, and a tire
    section could be added to the PDF with the test that forbids it still
    green.
    """
    headers = _section_headers(_PDF_MODULES[0].read_text())
    assert "Cost Projections" in headers, headers
