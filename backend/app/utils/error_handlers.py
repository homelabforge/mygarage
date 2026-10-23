"""Error handling utilities for secure error responses."""

import logging
import math
from typing import cast

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.utils.logging_utils import sanitize_for_log
from app.utils.settings_crypto import CIPHERTEXT_PREFIX, SettingsKeyUnavailable
from app.utils.settings_errors import PlaintextSecretsRemain, SettingCiphertextValue

logger = logging.getLogger(__name__)


class SecureErrorResponse:
    """Generate secure error responses that don't leak internal details."""

    @staticmethod
    def generic_error(
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        message: str = "An internal error occurred",
        request_id: str | None = None,
    ) -> JSONResponse:
        """Return a generic error response.

        Args:
            status_code: HTTP status code
            message: User-friendly error message
            request_id: Request ID for tracking

        Returns:
            JSONResponse with sanitized error
        """
        content = {
            "error": True,
            "message": message,
        }

        if request_id:
            content["request_id"] = request_id
            content["support_message"] = f"Please contact support with request ID: {request_id}"

        return JSONResponse(
            status_code=status_code,
            content=content,
        )

    @staticmethod
    def validation_error(
        errors: list,
        request_id: str | None = None,
    ) -> JSONResponse:
        """Return a validation error response.

        Args:
            errors: List of validation errors
            request_id: Request ID for tracking

        Returns:
            JSONResponse with validation errors
        """
        content = {
            "error": True,
            "message": "Validation error",
            "details": errors,
        }

        if request_id:
            content["request_id"] = request_id

        return JSONResponse(
            # Renamed upstream: starlette 1.6.0 deprecated
            # HTTP_422_UNPROCESSABLE_ENTITY in favour of the RFC 9110 spelling.
            # Same 422 on the wire.
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=content,
        )


async def handle_generic_exception(request: Request, exc: Exception) -> JSONResponse:
    """Handle generic exceptions securely.

    Logs the full error but returns a sanitized response to the client.

    Args:
        request: The request that caused the exception
        exc: The exception that was raised

    Returns:
        Secure error response
    """
    request_id = getattr(request.state, "request_id", None)

    # Log the full error with stack trace
    logger.error(
        f"Unhandled exception (request_id={request_id}): {type(exc).__name__}: {str(exc)}",
        exc_info=True,
    )

    # Return sanitized error to client
    return SecureErrorResponse.generic_error(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        message="An internal error occurred. Please try again later.",
        request_id=request_id,
    )


#: A field whose name (the last `loc` segment, any case) contains one of these may
#: hold a secret, so neither its rejected value nor its `ctx` is echoed back in the
#: 422 (L2, F-2).
_SECRET_FIELD_MARKERS = ("password", "secret", "token", "key")

#: All the log line keeps of each error. `input` is the rejected value (for a
#: missing field, the whole parent object) and `ctx` the constraint, which can
#: carry it too; neither is logged, for any field (L2).
_LOGGED_ERROR_FIELDS = ("type", "loc", "msg")


def _is_secret_field(loc: object) -> bool:
    """Whether a validation error's `loc` ends in a field named like a secret."""
    if not isinstance(loc, list | tuple):
        return False
    segments = cast("list[object] | tuple[object, ...]", loc)
    if not segments:
        return False
    name = str(segments[-1]).lower()
    return any(marker in name for marker in _SECRET_FIELD_MARKERS)


async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle validation errors.

    The 422 body keeps each error's `input` and `ctx`, except for a field named
    like a secret, which loses both, and except for an `input` that is a dict
    or a list (the whole parent object, on a missing field), which is dropped
    for any field. The log line keeps only `type`, `loc` and `msg`, so no
    rejected value reaches the log.

    Args:
        request: The request that caused the exception
        exc: The validation exception

    Returns:
        Validation error response
    """
    request_id = getattr(request.state, "request_id", None)

    # Convert validation errors to JSON-serializable format
    errors: list[dict[str, object]] = []
    for error in exc.errors():
        # Convert each error dict, ensuring all values are JSON-serializable
        json_error: dict[str, object] = {}
        for key, value in error.items():
            # Convert any non-serializable objects to strings. NaN and
            # infinity are floats JSON has no spelling for: echoed back as
            # the rejected input, they turned this 422 into a 500.
            if isinstance(value, float) and not math.isfinite(value):
                json_error[key] = str(value)
            elif isinstance(value, (str, int, float, bool, type(None))):
                json_error[key] = value
            elif isinstance(value, (list, tuple)):
                json_error[key] = [str(v) for v in value]
            else:
                json_error[key] = str(value)
        if _is_secret_field(error.get("loc")):
            # `ctx` too: a validator's exception lands in `ctx.error`, value and all (F-2).
            json_error.pop("input", None)
            json_error.pop("ctx", None)
        elif isinstance(error.get("input"), dict | list | tuple):
            # A whole object, not one value: on a missing field it is the parent
            # body, whatever secret fields that holds (T6 m3).
            json_error.pop("input", None)
        errors.append(json_error)

    logged = [{k: e[k] for k in _LOGGED_ERROR_FIELDS if k in e} for e in errors]
    logger.warning("Validation error (request_id=%s): %s", request_id, logged)

    # Return validation errors (the inputs that could hold a secret are already dropped)
    return SecureErrorResponse.validation_error(
        errors=errors,
        request_id=request_id,
    )


async def handle_database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """Handle database errors securely.

    Args:
        request: The request that caused the exception
        exc: The database exception

    Returns:
        Secure error response
    """
    request_id = getattr(request.state, "request_id", None)

    # Log the full database error
    logger.error(
        f"Database error (request_id={request_id}): {type(exc).__name__}: {str(exc)}",
        exc_info=True,
    )

    # Return sanitized error to client
    return SecureErrorResponse.generic_error(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        message="A database error occurred. Please try again later.",
        request_id=request_id,
    )


# PostgreSQL's "numeric value out of range": a number past its column. The
# same code covers "integer out of range", so the words say number, not amount.
_NUMERIC_OVERFLOW = "22003"
NUMERIC_OVERFLOW_DETAIL = "Number too large for storage"


def is_numeric_overflow(exc: DBAPIError) -> bool:
    """Whether the database refused a number too wide for its column.

    asyncpg's adapter sets `sqlstate` (and wraps the error as a plain
    DBAPIError, not a DataError); psycopg2 sets `pgcode`. SQLite never
    raises it: it ignores a column's declared precision.
    """
    orig = exc.orig
    code = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    return code == _NUMERIC_OVERFLOW


def _numeric_overflow_response(request: Request, exc: DBAPIError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    # The input fence missed this path, so it's worth a look, but it's the
    # client's number, not a server fault.
    logger.warning(
        "Numeric overflow (request_id=%s) on %s %s: %s",
        request_id,
        request.method,
        sanitize_for_log(request.url.path),
        type(exc.orig).__name__,
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": NUMERIC_OVERFLOW_DETAIL},
    )


async def handle_dbapi_error(request: Request, exc: DBAPIError) -> JSONResponse:
    """Production: a numeric overflow is a 422, any other DBAPI error a 500."""
    if is_numeric_overflow(exc):
        return _numeric_overflow_response(request, exc)
    return await handle_database_error(request, exc)


async def handle_dbapi_error_debug(request: Request, exc: DBAPIError) -> JSONResponse:
    """Debug: a numeric overflow is a 422 here too. Anything else propagates to
    the debug traceback, exactly as it did with no handler."""
    if is_numeric_overflow(exc):
        return _numeric_overflow_response(request, exc)
    raise exc


def ciphertext_value_detail(key: str) -> str:
    """The 422 detail for a secret setting given a value that is already ciphertext.

    Shared by the generic settings routes, which refuse it up front, and the
    handler below, which catches it from every other writer. Names the key,
    never the value.

    Args:
        key: The setting key that was being written.

    Returns:
        A message a client can show.
    """
    return (
        f"Setting '{key}' can't be set to a value starting with '{CIPHERTEXT_PREFIX}': "
        "that is an encrypted value, not the secret itself"
    )


async def handle_settings_key_unavailable(
    request: Request, exc: SettingsKeyUnavailable
) -> JSONResponse:
    """A secret setting write with no usable keyring: 503, saying what to fix (D3a, F-2).

    The setter raises it, so it can come from any writer. Its message names the
    key source (an env var by name, never its value), a fixed reason and the fix
    for that source, never key material or the value being written.
    """
    logger.warning(
        "Refused a secret settings write on %s %s: the settings encryption key is unavailable",
        request.method,
        sanitize_for_log(request.url.path),
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": str(exc)},
    )


async def handle_setting_ciphertext_value(
    request: Request, exc: SettingCiphertextValue
) -> JSONResponse:
    """A secret setting given a value that is already ciphertext: 422 (R2-9)."""
    logger.warning(
        "Refused a ciphertext value for %s on %s %s",
        sanitize_for_log(exc.key),
        request.method,
        sanitize_for_log(request.url.path),
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": ciphertext_value_detail(exc.key)},
    )


async def handle_plaintext_secrets_remain(
    request: Request, exc: PlaintextSecretsRemain
) -> JSONResponse:
    """A backup or restore refused because a secret is still plaintext: 503 (R1-H1).

    Raised by the backup preflight before anything is written. Its message names
    the setting keys and the fix, never a value.
    """
    logger.warning(
        "Refused %s %s: secret settings still stored unencrypted: %s",
        request.method,
        sanitize_for_log(request.url.path),
        sanitize_for_log(", ".join(exc.keys)),
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": str(exc)},
    )


def register_error_handlers(app: FastAPI, *, debug: bool) -> None:
    """Register the app's exception handlers.

    Production gets the sanitized handlers. The numeric-overflow mapping applies
    in debug too: an overflow is the client's number, so it's a 422 either way.
    Validation stays the fence; this is the backstop for a path it missed.

    The three secret-setting mappings are registered after the branch, in either
    mode. Starlette picks a handler by walking the exception's MRO, so their
    order against the production ``Exception`` catch-all doesn't matter; but
    debug registers no catch-all, and without them would answer with a
    traceback 500 (R2-3).
    """
    if debug:
        app.add_exception_handler(DBAPIError, handle_dbapi_error_debug)  # type: ignore[arg-type]
    else:
        app.add_exception_handler(Exception, handle_generic_exception)  # type: ignore[arg-type]
        app.add_exception_handler(SQLAlchemyError, handle_database_error)  # type: ignore[arg-type]
        # More specific than SQLAlchemyError, so a DBAPI error lands here first.
        app.add_exception_handler(DBAPIError, handle_dbapi_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, handle_validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(SettingsKeyUnavailable, handle_settings_key_unavailable)  # type: ignore[arg-type]
    app.add_exception_handler(SettingCiphertextValue, handle_setting_ciphertext_value)  # type: ignore[arg-type]
    app.add_exception_handler(PlaintextSecretsRemain, handle_plaintext_secrets_remain)  # type: ignore[arg-type]


def safe_error_detail(exc: Exception, development_mode: bool = False) -> str:
    """Get a safe error detail message.

    In production, returns a generic message.
    In development, returns the actual error.

    Args:
        exc: The exception
        development_mode: Whether in development mode

    Returns:
        Safe error message
    """
    if development_mode:
        return str(exc)
    return "An error occurred. Please contact support."
