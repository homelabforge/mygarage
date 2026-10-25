"""Torque Pro ingest — GET/POST with a path token. Returns text/plain 'OK!'.

Device auth is the path token (Torque cannot send headers or a stable query
param). No user session; token is scoped to exactly one vehicle. No `vin` path
param and no optional_auth, so the AST authz tripwire does not apply.

Also provides `redact_torque_path` + `TorqueTokenRedactionFilter` (R1-H3):
Torque forces the reusable device token into the request PATH (there is no
header or stable query param it can carry), so it would otherwise land
verbatim in the access log on every upload. The filter rewrites that path in
emitted log records before they're formatted. The token stays single-vehicle-
scoped and revocable (Task 13 DELETE) as defence in depth.
"""

import logging
import re
from collections.abc import Mapping

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.livelink_ingest import ingest
from app.services.livelink_sources.base import HttpEnvelope
from app.services.livelink_sources.torque import TorqueModule
from app.services.torque_service import TorqueService

router = APIRouter(prefix="/api/v1/torque", tags=["torque"])
_OK = Response(content="OK!", media_type="text/plain")

# Matches the ingest path with any token segment, for log redaction.
_TORQUE_PATH_RE = re.compile(r"/api/v1/torque/[^/]+/upload")


def redact_torque_path(text: str) -> str:
    """Rewrite any `/api/v1/torque/<token>/upload` occurrence to a redacted form.

    Pure function shared by `TorqueTokenRedactionFilter` and its unit test.
    """
    return _TORQUE_PATH_RE.sub("/api/v1/torque/<redacted>/upload", text)


class TorqueTokenRedactionFilter(logging.Filter):
    """Redact the Torque device path-token from access/request log records.

    Installed on the granian access logger (mirrors `HealthCheckLogFilter` in
    `main.py`). Rewrites the record's rendered message in place and clears
    `args` so the redacted text isn't re-interpolated; never drops a record.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact the token in `record`'s rendered message; always let it through."""
        message = record.getMessage()
        redacted = redact_torque_path(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


async def _ingest(token: str, params: Mapping[str, str], db: AsyncSession) -> Response:
    """Resolve the Torque path token and apply the upload through the pipeline.

    Owns the transaction: the pipeline does not commit. Answers 200 `OK!` on
    success, INCLUDING an unlinked device (the pipeline stores nothing for it,
    and Torque retries forever on anything but OK!), and 403 plain text on an
    invalid token.

    Parsing lives in `app.services.livelink_sources.torque`, orchestration in
    `app.services.livelink_ingest`. The device is resolved twice, here for the
    403 and again inside the pipeline: two indexed lookups in one transaction,
    and it keeps the 403-versus-OK decision where the HTTP contract lives.
    """
    if await TorqueService(db).resolve_by_token(token) is None:
        return Response(content="Invalid token", media_type="text/plain", status_code=403)

    await ingest(TorqueModule(), HttpEnvelope(token=token, params=params), db)
    await db.commit()
    return _OK


@router.get("/{token}/upload")
async def torque_ingest_get(
    token: str, request: Request, db: AsyncSession = Depends(get_db)
) -> Response:
    """Torque Pro's primary ingest path: GET with all data in the query string."""
    return await _ingest(token, request.query_params, db)


@router.post("/{token}/upload")
async def torque_ingest_post(
    token: str, request: Request, db: AsyncSession = Depends(get_db)
) -> Response:
    """Accept POST (query string and/or form body) for robustness; Torque itself uses GET."""
    params: dict[str, str] = dict(request.query_params)
    try:
        form = await request.form()
        for key, value in form.items():
            params.setdefault(key, str(value))
    except Exception:
        pass
    return await _ingest(token, params, db)
