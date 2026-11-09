"""The `sync_engine` fixture's type."""

from collections.abc import Callable

from sqlalchemy import Engine

#: What `sync_engine` yields: `create_engine` with the same arguments, and every
#: engine it made is disposed when the test ends.
SyncEngine = Callable[..., Engine]
