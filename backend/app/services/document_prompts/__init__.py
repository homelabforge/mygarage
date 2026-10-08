"""The prompts the document reader (#211) hands a vision model, one per kind.

A prompt names the harmonised keys the JSON answer may carry; the reader
keeps those keys and drops the rest, and the kind's own parser validates
every value before anything is applied. Adding a document kind is one
module here and one entry in ``PROMPTS``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DocumentKind = Literal["registration_certificate", "insurance_policy"]


@dataclass(frozen=True)
class DocumentPrompt:
    kind: DocumentKind
    #: The system message: what the document is, the exact JSON contract.
    system: str
    #: The user text sent with the images.
    user_text: str
    #: The keys the answer may carry; anything else is dropped.
    keys: tuple[str, ...]


def _load() -> dict[str, DocumentPrompt]:
    from app.services.document_prompts.insurance_policy import PROMPT as INSURANCE
    from app.services.document_prompts.registration_certificate import PROMPT as REGISTRATION

    return {REGISTRATION.kind: REGISTRATION, INSURANCE.kind: INSURANCE}


PROMPTS: dict[str, DocumentPrompt] = _load()


def prompt_for(kind: str) -> DocumentPrompt:
    try:
        return PROMPTS[kind]
    except KeyError as exc:
        raise ValueError(f"No document prompt for kind {kind!r}") from exc
