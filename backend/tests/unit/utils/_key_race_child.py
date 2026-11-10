"""Child process targets for the key-file race tests.

Kept apart from the test modules, which import the app at the top: a child must
set up its own environment before anything imports `app.config`. Under
forkserver or spawn a child inherits neither the parent's monkeypatches nor its
`settings.data_dir`, so each target clears the key env vars, points the data
dir at the test's directory, and only then imports the module under test.
"""

import logging
import multiprocessing
import os
import sys
import traceback
from collections.abc import Callable
from multiprocessing.queues import Queue
from multiprocessing.synchronize import Barrier
from pathlib import Path

#: (pid, key or kid or "error", source or traceback, warnings) from one child.
type RaceResult = tuple[int, object, object, list[str]]


class _Collect(logging.Handler):
    """Keeps every WARNING message the key modules log in this process."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _listen() -> _Collect:
    handler = _Collect()
    for name in ("app.utils.secret_key", "app.utils.settings_crypto"):
        logging.getLogger(name).addHandler(handler)
    return handler


def settings_key_child(data_dir: str, start: Barrier, results: Queue[RaceResult]) -> None:
    """Load the settings keyring from a data dir that has no key file yet.

    Puts ``(pid, current kid, keyring source, warnings)`` on ``results``, or
    ``(pid, "error", traceback, [])`` if anything raised.
    """
    try:
        os.environ.pop("MYGARAGE_SETTINGS_KEY", None)
        os.environ.pop("MYGARAGE_SETTINGS_KEY_FILE", None)
        os.environ["MYGARAGE_DATA_DIR"] = data_dir
        handler = _listen()

        from app.config import settings

        settings.data_dir = Path(data_dir)
        from app.utils import settings_crypto

        start.wait(timeout=60)
        kid = settings_crypto.current_kid()
        keyring = settings_crypto._keyring
        source = keyring.source if keyring is not None else None
        results.put((os.getpid(), kid, source, handler.messages))
    except BaseException:
        results.put((os.getpid(), "error", traceback.format_exc(), []))
        sys.exit(1)


def jwt_key_child(key_file: str, start: Barrier, results: Queue[RaceResult]) -> None:
    """Get the JWT key from a path that has no file yet.

    Puts ``(pid, key, KEY_SOURCE, warnings)`` on ``results``, or
    ``(pid, "error", traceback, [])`` if anything raised.
    """
    try:
        handler = _listen()
        from app.utils import secret_key

        # Never carry over a real /data/secret.key from the machine running this.
        secret_key.DEFAULT_KEY_FILE = Path("/nonexistent-mygarage/secret.key")
        start.wait(timeout=60)
        key = secret_key.get_or_create_secret_key(Path(key_file))
        results.put((os.getpid(), key, secret_key.KEY_SOURCE, handler.messages))
    except BaseException:
        results.put((os.getpid(), "error", traceback.format_exc(), []))
        sys.exit(1)


def run_race(target: Callable[..., None], arg: str, processes: int) -> list[RaceResult]:
    """Start ``processes`` children on ``target`` at once and collect what each one put.

    Spawned explicitly, so a child never inherits this process's state, whatever
    the platform's default start method. Every wait has a timeout, so a stuck
    child fails the test instead of hanging the run.
    """
    ctx = multiprocessing.get_context("spawn")
    start = ctx.Barrier(processes)
    results: Queue[RaceResult] = ctx.Queue()
    children = [ctx.Process(target=target, args=(arg, start, results)) for _ in range(processes)]
    for child in children:
        child.start()
    try:
        return [results.get(timeout=120) for _ in children]
    finally:
        for child in children:
            child.join(timeout=30)
            if child.is_alive():
                child.terminate()
                child.join(timeout=5)


def race_warnings(results: list[RaceResult]) -> list[str]:
    """Every WARNING message the racers logged, in one list."""
    return [m for r in results for m in r[3]]
