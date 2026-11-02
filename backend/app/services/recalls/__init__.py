"""Recall providers (#211): NHTSA for North America, RappelConso for France.

A provider says whether it applies to a vehicle (from its country profile's
``data_sources.recalls``) and fetches ``RecallHit`` rows for it; the recall
service stores what is new and the weekly job walks every vehicle through
the providers that apply. Adding a source is one module and one line in
``registry.PROVIDERS``.
"""

from app.services.recalls.base import RecallHit, RecallProvider
from app.services.recalls.registry import PROVIDERS, provider_by_name, providers_for

__all__ = ["PROVIDERS", "RecallHit", "RecallProvider", "provider_by_name", "providers_for"]
