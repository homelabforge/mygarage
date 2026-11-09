"""The six settings batch 5 stopped seeding, shared by the seed and write tests.

Nothing read them: uploads follow the server's configuration (sizes from the
environment, each kind's file types from defaults in code the environment can
override), and the three display settings were never read at all. They're off
the write allowlist too.
"""

RETIRED_SEED_KEYS = (
    "max_upload_size_mb",
    "allowed_photo_types",
    "allowed_attachment_types",
    "date_format",
    "distance_unit",
    "fuel_unit",
)
