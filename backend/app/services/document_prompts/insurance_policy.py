"""The prompt for a motor insurance policy document (certificate, schedule,
renewal notice, avis d'échéance…).

The keys mirror what the insurance parsers extract from a text PDF, so a
photo of the document lands in the same fields: the insurer, the policy
number, the period, the premium and how often it is paid, the deductible,
the policy type as printed, the coverages with their limits, the plates and
VINs the policy names, and the no-claims class (CRM, SF-Klasse, classe di
merito).
"""

from __future__ import annotations

from app.services.document_prompts import DocumentPrompt

KEYS: tuple[str, ...] = (
    "insurer",
    "policy_number",
    "start_date",
    "end_date",
    "premium",
    "payment_frequency",
    "deductible",
    "policy_type",
    "coverages",
    "plates",
    "vins",
    "no_claims_class",
    "currency",
)

SYSTEM = (
    "You read a motor insurance document: a policy schedule, an insurance certificate, a "
    "renewal notice (avis d'échéance), a Versicherungsschein, a polizza, a póliza.\n"
    "Reply with ONLY a JSON object, no prose, using exactly these keys: " + ", ".join(KEYS) + ".\n"
    "Key meanings: insurer = the insurance company's name; policy_number = the contract "
    "or policy number as printed; start_date and end_date = the cover period as "
    "YYYY-MM-DD; premium = the total premium as a number without currency symbol; "
    "payment_frequency = one of monthly, quarterly, semi-annual, annual, or null; "
    "deductible = the deductible or franchise as a number; policy_type = the formula as "
    "printed (tous risques, au tiers, Vollkasko, Teilkasko…); coverages = a list of "
    "objects {name, limit} for each coverage printed, limit as a number or null; "
    "plates = a list of registration plates printed; vins = a list of 17-character VINs "
    "printed; no_claims_class = the bonus-malus coefficient or class as printed (0.50, "
    "SF 12, classe 1…); currency = the ISO 4217 code of the amounts.\n"
    "Use null for a field that is absent or illegible, and an empty list for a list with "
    "nothing printed. Never guess, never invent a value; copy values as printed, dates "
    "converted to YYYY-MM-DD and numbers without units or thousands separators."
)

USER_TEXT = "Read this insurance document and return the JSON object."

PROMPT = DocumentPrompt(kind="insurance_policy", system=SYSTEM, user_text=USER_TEXT, keys=KEYS)
