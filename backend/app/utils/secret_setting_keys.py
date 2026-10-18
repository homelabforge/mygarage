"""The settings whose values are secrets: encrypted at rest and masked in responses.

A leaf module with no imports, on purpose. The ``Setting`` model imports this
set, and ``app.services.settings_init`` imports the model, so deriving the set
from the seed metadata there would make an import cycle.

The list is explicit, and ``tests/unit/utils/test_secret_setting_keys.py`` pins
it to the seed: every ``DEFAULT_SETTINGS`` key flagged ``encrypted: True``, plus
the three POI provider keys, which migration 027 seeds without the flag. A seed
key newly flagged fails that test until it is listed here. The ``encrypted``
column on the row is informational only; this set is what the code obeys.
"""

SECRET_SETTING_KEYS: frozenset[str] = frozenset(
    {
        # SSO
        "oidc_client_secret",
        # Notifications
        "ntfy_token",
        "gotify_token",
        "pushover_user_key",
        "pushover_api_token",
        "slack_webhook_url",
        "discord_webhook_url",
        "matrix_access_token",
        "telegram_bot_token",
        "email_smtp_password",
        # Integrations
        "webhook_ingest_token",
        "llm_api_key",
        "livelink_mqtt_password",
        # POI providers
        "tomtom_api_key",
        "google_places_api_key",
        "yelp_api_key",
        "foursquare_api_key",
    }
)
