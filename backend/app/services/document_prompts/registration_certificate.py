"""The prompt for an EU registration certificate (Directive 1999/37/EC).

The keys are the harmonised field codes printed on every member state's
certificate (carte grise, Zulassungsbescheinigung Teil I, kentekenbewijs,
carta di circolazione, permiso de circulación…), with the dot dropped so
they are plain JSON keys: A plate, B first registration, C1 holder, D1
make, D2 type/variant/version, D3 commercial name, E VIN, F1 maximum mass,
G mass in service, J EU category, J1 national category, K type approval,
P1 displacement, P2 power kW, P3 energy code, P6 fiscal power, S1 seats,
V7 CO₂, V9 Euro class, X1 last inspection, Y1 to Y6 taxes.
"""

from __future__ import annotations

from app.services.document_prompts import DocumentPrompt

KEYS: tuple[str, ...] = (
    "country",
    "A",
    "B",
    "C1",
    "D1",
    "D2",
    "D3",
    "E",
    "F1",
    "G",
    "J",
    "J1",
    "K",
    "P1",
    "P2",
    "P3",
    "P6",
    "S1",
    "V7",
    "V9",
    "X1",
    "Y1",
    "Y2",
    "Y3",
    "Y4",
    "Y5",
    "Y6",
)

SYSTEM = (
    "You read a European vehicle registration certificate (EU Directive 1999/37/EC: "
    "a French carte grise, a German Zulassungsbescheinigung Teil I, a Dutch "
    "kentekenbewijs, an Italian carta di circolazione, a Spanish permiso de "
    "circulación, a Luxembourg carte grise, and the like). The fields are labelled "
    "with harmonised codes printed on the document.\n"
    "Reply with ONLY a JSON object, no prose, using exactly these keys: " + ", ".join(KEYS) + ".\n"
    "Key meanings: country = ISO 3166-1 alpha-2 of the issuing country; A = registration "
    "plate; B = date of first registration as YYYY-MM-DD; C1 = holder name; D1 = make; "
    "D2 = type, variant, version; D3 = commercial name (model); E = 17-character VIN; "
    "F1 = technically permissible maximum laden mass in kg; G = mass in service in kg; "
    "J = EU vehicle category (M1, N1, L3e…); J1 = national category (VP, CTTE, MTL…); "
    "K = type-approval number; P1 = engine capacity in cm3; P2 = maximum net power in kW; "
    "P3 = fuel code as printed (ES, GO, EL, EE, EH, GL, GH, GP, GN, FE, H2, EG, EN); "
    "P6 = national fiscal power; S1 = number of seats; V7 = CO2 in g/km; V9 = Euro "
    "emission class or environmental category as printed; X1 = date of the last "
    "technical inspection as YYYY-MM-DD; Y1 to Y6 = the tax amounts printed, as numbers.\n"
    "Use null for a field that is absent, illegible or not printed. Never guess, never "
    "invent a plausible value, never translate a code; copy values as printed, dates "
    "converted to YYYY-MM-DD and numbers without units."
)

USER_TEXT = "Read this registration certificate and return the JSON object."

PROMPT = DocumentPrompt(
    kind="registration_certificate", system=SYSTEM, user_text=USER_TEXT, keys=KEYS
)
