"""Error handling utilities for secure error responses."""

import logging
from typing import Optional
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


class SecureErrorResponse:
    """Generate secure error responses that don't leak internal details."""

    @staticmethod
    def generic_error(
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        message: str = "An internal error occurred",
        request_id: Optional[str] = None,
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
            content["support_message"] = (
                f"Please contact support with request ID: {request_id}"
            )

        return JSONResponse(
            status_code=status_code,
            content=content,
        )

    @staticmethod
    def validation_error(
        errors: list,
        request_id: Optional[str] = None,
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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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


async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle validation errors.

    Args:
        request: The request that caused the exception
        exc: The validation exception

    Returns:
        Validation error response
    """
    request_id = getattr(request.state, "request_id", None)

    # Convert validation errors to JSON-serializable format
    errors = []
    for error in exc.errors():
        # Convert each error dict, ensuring all values are JSON-serializable
        json_error = {}
        for key, value in error.items():
            # Convert any non-serializable objects to strings
            if isinstance(value, (str, int, float, bool, type(None))):
                json_error[key] = value
            elif isinstance(value, (list, tuple)):
                json_error[key] = [str(v) for v in value]
            else:
                json_error[key] = str(value)
        errors.append(json_error)

    # Log validation errors
    logger.warning(
        f"Validation error (request_id={request_id}): {errors}",
    )

    # Return validation errors (these are safe to expose)
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
