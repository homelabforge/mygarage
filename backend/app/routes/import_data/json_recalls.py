"""Recalls in a JSON backup: every column, keyed on the NHTSA campaign (K10).

A flat section, matched one to one like warranties (R5). A recall the nightly
check already put back keeps everything it has, and only gains a resolution
and notes from the file when it has neither.
"""

# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recall import Recall
from app.routes.import_data._common import (
    _is_blank,
    _json_bool,
    _json_optional_date,
    _json_row_datetime,
    _json_text,
    _RowError,
    _unexpected_reason,
)
from app.routes.import_data._families import as_object
from app.routes.import_data._matching import _DuplicateMatcher, _matches, _text_matches
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


def _recall_from_json(vin: str, row: Mapping[str, Any]) -> Recall:
    """One recall as an unsaved row, every column the export writes.

    Text is read as given (NB-1): the sync stores a campaign number uncut, so a
    cap would refuse what the app wrote. Component and summary may be missing,
    since the columns allow NULL and a restore takes what was stored.
    """
    return Recall(
        vin=vin,
        nhtsa_campaign_number=_json_text(row, "nhtsa_campaign_number"),
        component=_json_text(row, "component"),
        summary=_json_text(row, "summary"),
        consequence=_json_text(row, "consequence"),
        remedy=_json_text(row, "remedy"),
        date_announced=_json_optional_date(row, "date_announced"),
        is_resolved=_json_bool(row, "is_resolved", default=False),
        resolved_at=_json_row_datetime(row, "resolved_at"),
        notes=_json_text(row, "notes"),
    )


def _json_recall_key(row: Mapping[str, Any], recall: Recall) -> list[ColumnElement[bool]]:
    """S6's recall key: the campaign number alone when there is one.

    NHTSA rewords components and summaries, so those only key a hand-entered
    recall, each when the row has it (T-16). A hand-entered one never matches a
    campaign row. The route adds the vehicle.
    """
    if recall.nhtsa_campaign_number is not None:
        return [Recall.nhtsa_campaign_number == recall.nhtsa_campaign_number]
    key = [_text_matches(Recall.nhtsa_campaign_number, None)]
    if "component" in row:
        key.append(_text_matches(Recall.component, recall.component))
    if "summary" in row:
        key.append(_text_matches(Recall.summary, recall.summary))
    if "date_announced" in row:
        key.append(_matches(Recall.date_announced, recall.date_announced))
    return key


async def import_recalls(
    db: AsyncSession,
    vin: str,
    rows: Sequence[Any],
    *,
    matcher: _DuplicateMatcher,
    skip_duplicates: bool,
    bucket: dict[str, int],
    errors: list[str],
) -> None:
    """Import the file's recalls one row at a time, a bad one a row error (3a's flat loop)."""
    for idx, row in enumerate(rows):
        try:
            data = as_object(row)
            recall = _recall_from_json(vin, data)
            if skip_duplicates:
                stored: Recall | None = await matcher.take(
                    db, Recall, Recall.vin == vin, *_json_recall_key(data, recall)
                )
                if stored is not None:
                    # The nightly check may have put this recall back already, unresolved.
                    # Fill in what the backup knew, never over what's here.
                    if not stored.is_resolved and _is_blank(stored.notes):
                        async with db.begin_nested():
                            stored.is_resolved = recall.is_resolved
                            stored.resolved_at = recall.resolved_at
                            stored.notes = recall.notes
                    bucket["skipped"] += 1
                    continue

            async with db.begin_nested():
                db.add(recall)
            bucket["success"] += 1
        except _RowError as e:
            bucket["errors"] += 1
            errors.append(f"Recall {idx}: {e.reason}")
        except Exception as e:
            bucket["errors"] += 1
            logger.warning("Import: recall %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Recall {idx}: {_unexpected_reason(e)}")
