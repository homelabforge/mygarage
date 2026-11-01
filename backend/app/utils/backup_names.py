"""The stamp in every backup file name."""

import uuid
from datetime import datetime


def backup_stamp() -> str:
    """Local time to the second plus a short random suffix.

    By the second alone, two backups in one second shared a name and the later
    one overwrote the first. Local time, like every backup name before it.
    """
    return f"{datetime.now().strftime('%Y-%m-%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
