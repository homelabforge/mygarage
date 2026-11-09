"""The type of the `keep_rows` fixture, for tests and helpers that take it."""

from collections.abc import Awaitable, Callable

#: What `keep_rows` yields: call it with the settings keys a test is about to
#: write, and teardown puts those rows back the way they were.
Keep = Callable[[*tuple[str, ...]], Awaitable[None]]
