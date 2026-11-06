"""Title Case for vehicle makes and models (#219 takeover).

NHTSA hands back makes in capitals (``MITSUBISHI``, ``RAM``) and older rows
were saved that way, so the same car read « MITSUBISHI Mirage » in one place
and « Mitsubishi Mirage » in another. Makes take the canonical spelling from
``data/vehicle_makes.json`` (``BMW``, ``Ram``, ``Škoda``, ``McLaren``); a make
that isn't listed and a model only change when they arrive in ALL CAPS: a
model the picker catalog lists takes its spelling (``data/vehicle_models.json``,
read under the make when the writer knows it), anything else goes word by word. Anything typed in mixed case is the user's spelling and is
left alone, apart from the make aliases (``Chevy`` reads Chevrolet).
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import cast

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "vehicle_makes.json"
#: The picker catalog's models by make, copied from the frontend's
#: carCatalog.json by frontend/scripts/sync-vehicle-models.ts.
_MODELS_PATH = Path(__file__).resolve().parent.parent / "data" / "vehicle_models.json"

#: Three-letter words that are names in their own right and stay in capitals.
#: Any other three-letter word is capitalized (``FIT`` reads Fit, ``RIO`` Rio).
#: A word missing here reads « Gts »-style; the user can retype it, and mixed
#: case is never touched again.
KEEP_CAPS: frozenset[str] = frozenset(
    {
        # Trims and badges
        "AMG", "GTI", "GTO", "GTS", "GTV", "HSE", "LTZ", "RST", "SLT", "SRT", "SVR", "SXT",
        "TDI", "TSI", "XLT", "SUV", "MPV", "GNX", "SSR", "HHR",
        # Mercedes-Benz classes
        "CLA", "CLK", "CLS", "EQA", "EQB", "EQC", "EQE", "EQS", "GLA", "GLB", "GLC",
        "GLE", "GLK", "GLS", "SLC", "SLK", "SLR", "SLS",
        # Acura, Cadillac, Lincoln
        "ILX", "MDX", "NSX", "RDX", "RLX", "RSX", "TLX", "TSX", "ZDX",
        "ATS", "CTS", "DTS", "ELR", "SRX", "STS", "XTS",
        "MKC", "MKS", "MKT", "MKX", "MKZ",
        # Others
        "ASX", "BRZ", "LFA", "SVX", "TTS", "WRX",
    }
)  # fmt: skip

#: Two-letter words that are ordinary words, not codes, so they capitalize
#: (``SANTA FE`` reads Santa Fe, ``DE VILLE`` De Ville). Any other two-letter
#: word stays in capitals (``CR-V``, ``GT``, ``LE``, ``RS``).
TITLE_TWO_LETTER: frozenset[str] = frozenset(
    {"AN", "AU", "DA", "DE", "DI", "DU", "EL", "FE", "GO", "LA", "OF", "ON", "UP"}
)

_SEPARATORS = re.compile(r"(\s+|-|/)")


@lru_cache(maxsize=1)
def _data() -> dict[str, object]:
    with _DATA_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def fold_key(text: str) -> str:
    """Lowercase letters and digits only, with diacritics removed.

    ``Škoda``, ``SKODA`` and ``skoda`` share a key; so do ``Mercedes-Benz``
    and ``MERCEDES BENZ``.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]", "", plain)


def canonical_makes() -> list[str]:
    """Every canonical make spelling, in the file's order."""
    return [str(make) for make in cast(list[str], _data()["makes"])]


@lru_cache(maxsize=1)
def _by_key() -> dict[str, str]:
    table = {fold_key(make): make for make in canonical_makes()}
    for alias, target in cast(dict[str, str], _data()["aliases"]).items():
        table[str(alias)] = str(target)
    return table


def _model_key(text: str) -> str:
    """Case and diacritics folded, spaces collapsed, punctuation kept.

    Punctuation stays because it tells models apart: ``GO`` and ``GO+``,
    ``3.0`` and ``30``. A space after a dot doesn't: VW writes ``ID. Buzz``
    and people type ``ID.BUZZ``.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\.\s+", ".", " ".join(plain.casefold().split()))


def _unambiguous(names: list[str]) -> dict[str, str]:
    """Each name by its key; a key two spellings share is left out."""
    spellings: dict[str, set[str]] = {}
    for name in names:
        spellings.setdefault(_model_key(name), set()).add(name)
    return {key: next(iter(found)) for key, found in spellings.items() if len(found) == 1}


@lru_cache(maxsize=1)
def _catalog_by_make() -> dict[str, dict[str, str]]:
    """Each make's catalog models by key."""
    with _MODELS_PATH.open(encoding="utf-8") as handle:
        by_make = cast(dict[str, list[str]], json.load(handle))
    return {make: _unambiguous(names) for make, names in by_make.items()}


@lru_cache(maxsize=1)
def _catalog_models() -> dict[str, str]:
    """Every make's catalog models by key, for a writer that has no make.

    Saturn's ``Ion`` and Peugeot's ``iOn`` share a key, so ``ION`` falls back
    to the word rule instead of picking a make's spelling at random.
    """
    with _MODELS_PATH.open(encoding="utf-8") as handle:
        by_make = cast(dict[str, list[str]], json.load(handle))
    return _unambiguous([name for names in by_make.values() for name in names])


def _is_all_caps(text: str) -> bool:
    return any(ch.isalpha() for ch in text) and text == text.upper()


def _word(word: str) -> str:
    if not word or any(ch.isdigit() for ch in word):
        return word
    letters = sum(1 for ch in word if ch.isalpha())
    if letters <= 2 and word not in TITLE_TWO_LETTER:
        return word
    if letters == 3 and word in KEEP_CAPS:
        return word
    return word[0].upper() + word[1:].lower()


def _title_words(text: str) -> str:
    """Apply the word rule to each part between spaces, hyphens and slashes."""
    parts = _SEPARATORS.split(text)
    return "".join(part if _SEPARATORS.fullmatch(part) else _word(part) for part in parts)


def normalize_make(raw: str | None) -> str | None:
    """The canonical spelling of a make.

    Args:
        raw: The make as typed, decoded or stored.

    Returns:
        None when blank; the canonical spelling when the folded text is a
        known make or alias; otherwise ALL-CAPS text through the word rule,
        and anything else stripped but as written.
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    known = _by_key().get(fold_key(text))
    if known is not None:
        return known
    return _title_words(text) if _is_all_caps(text) else text


def normalize_model(raw: str | None, make: str | None = None) -> str | None:
    """A model name in Title Case when it arrives in ALL CAPS.

    Args:
        raw: The model as typed, decoded or stored.
        make: The vehicle's make, in any spelling, when the writer has it.

    Returns:
        None when blank. ALL-CAPS text takes the picker catalog's spelling
        when it names a catalog model (``DBS`` stays DBS, ``A2 E-TRON`` reads
        A2 e-tron), so a picked model saves as picked (Fable diff F-1). With
        a make, only that make's models count (a MINI ``ONE`` reads One, a
        Mercedes-AMG ``ONE`` stays ONE), and a make the catalog doesn't list
        gets the word rule; without one, any model only one make spells that
        way. Otherwise the word rule (digits and two-letter codes stay,
        three-letter words stay only in ``KEEP_CAPS``). Mixed case stripped
        but as written.
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    if not _is_all_caps(text):
        return text
    canonical = normalize_make(make)
    if canonical is None:
        catalog = _catalog_models()
    else:
        catalog = _catalog_by_make().get(canonical, {})
    known = catalog.get(_model_key(text))
    return known if known is not None else _title_words(text)
