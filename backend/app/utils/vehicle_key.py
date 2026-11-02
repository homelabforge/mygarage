"""The vehicle key and the identifier people actually see (#226).

`vehicles.vin` is the primary key every table and route hangs off. A vehicle
with a real VIN uses the VIN as its key. A tractor, a mower or a boat with a HIN
gets a generated key instead: "Q" plus 16 VIN characters. ISO 3779 bans Q from a
VIN, so a generated key can never collide with a real one, and it is still 17
uppercase alphanumerics, so every length-17 schema, URL and upload folder keeps
working.

The key is plumbing. What a person sees is `display_identifier`: the VIN, or the
serial / HIN / chassis number / asset tag in `vehicles.identifier`. Whether a
vehicle has a real VIN is `identifier_type == "vin"`, never the key's shape.
"""

from __future__ import annotations

import re
import secrets
from typing import Any, Literal, Protocol

IdentifierType = Literal["vin", "serial", "hin", "chassis", "asset_tag", "none"]
IDENTIFIER_TYPES: tuple[str, ...] = ("vin", "serial", "hin", "chassis", "asset_tag", "none")

# The VIN alphabet: A-Z and 0-9 without I, O and Q.
_VIN_ALPHABET = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
_VIN_SHAPE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
_SYNTHETIC_SHAPE = re.compile(r"^Q[A-HJ-NPR-Z0-9]{16}$")


class _HasIdentity(Protocol):
    vin: str
    identifier_type: str
    identifier: str | None


def generate_vehicle_key() -> str:
    """Return a fresh key for a vehicle without a VIN ("Q" + 16 VIN characters)."""
    return "Q" + "".join(secrets.choice(_VIN_ALPHABET) for _ in range(16))


def is_synthetic_key(key: str) -> bool:
    """Whether a key was generated for a vehicle without a VIN."""
    return bool(_SYNTHETIC_SHAPE.match(key))


def is_vehicle_key(key: str) -> bool:
    """Whether a string is shaped like a vehicle key: a VIN or a generated key.

    This is the path-parameter guard (it keeps `../` out of upload paths). It
    says nothing about whether the vehicle exists or has a real VIN.
    """
    return bool(_VIN_SHAPE.match(key) or _SYNTHETIC_SHAPE.match(key))


def has_real_vin(vehicle: _HasIdentity) -> bool:
    """Whether the vehicle's key is a VIN that may be decoded or sent to NHTSA."""
    return (vehicle.identifier_type or "vin") == "vin"


def display_identifier(vehicle: _HasIdentity) -> tuple[str, str | None]:
    """The identifier to show for a vehicle, as (type, value). Never a generated key."""
    kind = vehicle.identifier_type or "vin"
    if kind == "vin":
        return "vin", vehicle.vin
    return kind, vehicle.identifier or None


#: English labels for backend output (PDFs, notifications); the frontend has its own i18n keys.
IDENTIFIER_LABELS: dict[str, str] = {
    "vin": "VIN",
    "serial": "Serial",
    "hin": "HIN",
    "chassis": "Chassis",
    "asset_tag": "Asset tag",
    "none": "ID",
}


def identifier_text(vehicle: _HasIdentity) -> str | None:
    """A one-line English label for backend output (PDFs, notifications): "Serial KBT-1"."""
    kind, value = display_identifier(vehicle)
    if not value:
        return None
    return f"{IDENTIFIER_LABELS.get(kind, kind)} {value}"


def _filename_safe(value: str | None) -> str:
    return re.sub(r"-{2,}", "-", re.sub(r"[^A-Za-z0-9-]", "-", value or "")).strip("-")


def download_tag(vehicle: _HasIdentity, nickname: str | None = None) -> str:
    """The vehicle's part of a download filename: the VIN, else a safe identifier.

    Only [A-Za-z0-9-] survive, so it can go straight into Content-Disposition.
    A vehicle without a VIN never puts its generated key in a filename (#226).
    """
    kind, value = display_identifier(vehicle)
    if kind == "vin" and value:
        return value
    return (_filename_safe(value) or _filename_safe(nickname) or "vehicle")[:40]


def export_basename(vehicle: Any) -> str:
    """Year_Make_Model for export filenames, skipping what's unknown.

    A mower entered with only a nickname used to download as
    `None_None_None_...`; it falls back to the nickname, then "vehicle". Only
    [A-Za-z0-9-] survive, so make/model text can't break Content-Disposition.
    """
    parts = [_filename_safe(str(p)) for p in (vehicle.year, vehicle.make, vehicle.model) if p]
    parts = [p for p in parts if p]
    if parts:
        return "_".join(parts)
    return _filename_safe(getattr(vehicle, "nickname", None)) or "vehicle"


def filename_fragment(vehicle: _HasIdentity, length: int = 6) -> str:
    """A short, filename-safe tail of the identifier for download names."""
    _kind, value = display_identifier(vehicle)
    safe = re.sub(r"[^A-Za-z0-9]", "", value or "")
    return safe[-length:] if safe else "vehicle"
