"""How long a sent nag holds back the next one.

The daily reminder and expiry checks cron on the container's local time, so on
a DST day there are only 23 h between ticks. The slack covers that, plus the
odd second of start-up jitter.
"""

from __future__ import annotations

from datetime import datetime, timedelta

#: One nag a day per thing.
NOTIFICATION_COOLDOWN = timedelta(hours=24)
#: Yesterday's stamp can read as little as 23 h on a spring-forward day.
NOTIFICATION_COOLDOWN_SLACK = timedelta(hours=2)


def in_cooldown(last_notified_at: datetime | None, now: datetime) -> bool:
    """Whether a stamp is recent enough to skip this run's nag."""
    if last_notified_at is None:
        return False
    return now - last_notified_at < NOTIFICATION_COOLDOWN - NOTIFICATION_COOLDOWN_SLACK
