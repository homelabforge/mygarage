"""API routes for report generation and export."""

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BeforeValidator
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.services import report_service
from app.services.auth import get_vehicle_or_403, require_auth
from app.utils.date_order import DATE_ORDER_PATTERN, resolve_date_order
from app.utils.pdf_generator import PDFReportGenerator
from app.utils.render_context import render_context_for_request
from app.utils.vehicle_key import download_tag, filename_fragment

router = APIRouter(prefix="/api/vehicles", tags=["Reports"])


def _blank_is_none(value: object) -> object:
    """An empty query value, what a form sends for a date left blank, is no filter."""
    return None if value == "" else value


# Typed as a date, so a malformed one is a 422 naming the param instead of a 500.
OptionalDate = Annotated[date | None, BeforeValidator(_blank_is_none)]


@router.get("/{vin}/reports/service-history-pdf")
async def download_service_history_pdf(
    vin: str,
    start_date: Annotated[OptionalDate, Query(description="Start date (YYYY-MM-DD)")] = None,
    end_date: Annotated[OptionalDate, Query(description="End date (YYYY-MM-DD)")] = None,
    currency_code: str = Query("USD", description="ISO 4217 code; defaults to USD."),
    locale: str = Query("en-US", description="BCP 47 locale; defaults to en-US."),
    date_format: str | None = Query(
        None, pattern=DATE_ORDER_PATTERN, description="'mdy' or 'dmy'; defaults to the account's."
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Generate and download service history PDF report."""
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    from app.utils.currency import normalize_pdf_currency_params

    safe_code, safe_locale = normalize_pdf_currency_params(currency_code, locale)
    pdf_gen = PDFReportGenerator(
        render_context=await render_context_for_request(current_user, db, vehicle=vehicle),
        currency_code=safe_code,
        locale=safe_locale,
        date_order=resolve_date_order(date_format, current_user),
    )
    pdf_buffer = await report_service.service_history_pdf(
        db, vehicle, pdf_gen, start_date, end_date
    )

    # Return as downloadable file
    filename = f"service_history_{download_tag(vehicle, vehicle.nickname)}_{datetime.now().strftime('%Y%m%d')}.pdf"
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{vin}/reports/sale-history-pdf")
async def download_sale_history_pdf(
    vin: str,
    date_format: str | None = Query(
        None, pattern=DATE_ORDER_PATTERN, description="'mdy' or 'dmy'; defaults to the account's."
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Sanitized service history PDF for prospective buyers (no costs/vendors/plate)."""
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    pdf_gen = PDFReportGenerator(
        render_context=await render_context_for_request(current_user, db, vehicle=vehicle),
        date_order=resolve_date_order(date_format, current_user),
    )
    pdf_buffer = await report_service.sale_history_pdf(db, vehicle, pdf_gen)
    filename = f"sale_history_{filename_fragment(vehicle)}_{datetime.now().strftime('%Y%m%d')}.pdf"
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{vin}/reports/cost-summary-pdf")
async def download_cost_summary_pdf(
    vin: str,
    year: int = Query(..., ge=1, description="Year for cost summary"),
    currency_code: str = Query("USD", description="ISO 4217 code; defaults to USD."),
    locale: str = Query("en-US", description="BCP 47 locale; defaults to en-US."),
    date_format: str | None = Query(
        None, pattern=DATE_ORDER_PATTERN, description="'mdy' or 'dmy'; defaults to the account's."
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Generate and download annual cost summary PDF."""
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    from app.utils.currency import normalize_pdf_currency_params

    safe_code, safe_locale = normalize_pdf_currency_params(currency_code, locale)
    pdf_gen = PDFReportGenerator(
        render_context=await render_context_for_request(current_user, db, vehicle=vehicle),
        currency_code=safe_code,
        locale=safe_locale,
        date_order=resolve_date_order(date_format, current_user),
    )
    pdf_buffer = await report_service.cost_summary_pdf(db, vehicle, pdf_gen, year)

    # Return as downloadable file
    filename = f"cost_summary_{download_tag(vehicle, vehicle.nickname)}_{year}.pdf"
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{vin}/reports/tax-deduction-pdf")
async def download_tax_deduction_pdf(
    vin: str,
    year: int = Query(..., ge=1, description="Tax year"),
    currency_code: str = Query("USD", description="ISO 4217 code; defaults to USD."),
    locale: str = Query("en-US", description="BCP 47 locale; defaults to en-US."),
    date_format: str | None = Query(
        None, pattern=DATE_ORDER_PATTERN, description="'mdy' or 'dmy'; defaults to the account's."
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Generate and download tax deduction report PDF."""
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    from app.utils.currency import normalize_pdf_currency_params

    safe_code, safe_locale = normalize_pdf_currency_params(currency_code, locale)
    pdf_gen = PDFReportGenerator(
        render_context=await render_context_for_request(current_user, db, vehicle=vehicle),
        currency_code=safe_code,
        locale=safe_locale,
        date_order=resolve_date_order(date_format, current_user),
    )
    pdf_buffer = await report_service.tax_deduction_pdf(db, vehicle, pdf_gen, year)

    # Return as downloadable file
    filename = f"tax_deduction_{download_tag(vehicle, vehicle.nickname)}_{year}.pdf"
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{vin}/reports/service-history-csv")
async def download_service_history_csv(
    vin: str,
    start_date: Annotated[OptionalDate, Query(description="Start date (YYYY-MM-DD)")] = None,
    end_date: Annotated[OptionalDate, Query(description="End date (YYYY-MM-DD)")] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Export service history to CSV, in the caller's own units."""
    # This docstring is the endpoint's public OpenAPI description, so the
    # reasoning lives here instead.
    #
    # A report is a render, so it follows the render policy: the CALLER's
    # units, never the vehicle owner's. There is deliberately no `?units=`
    # parameter. The backup export has one because a user chooses a backup's
    # format; a shared viewer reading a report should simply see their own
    # units, and `get_vehicle_or_403` admits admins and shared users whose
    # preferences differ from the owner's.
    #
    # `show_both` is ignored: a CSV cell is numeric, so it carries one number
    # in one unit, named by its header token. Rendering a counterpart into the
    # cell would make the column text a spreadsheet cannot sum.
    #
    # A vehicle set to its own odometer unit (#172) overrides distance for
    # every caller alike: it describes the vehicle's dash, not the owner's
    # taste, so it is not the owner's-units exception the paragraph above rules
    # out.
    vehicle = await get_vehicle_or_403(vin, current_user, db)
    context = await render_context_for_request(current_user, db, vehicle=vehicle)
    body = await report_service.service_history_csv(db, vehicle, context, start_date, end_date)

    # Return as downloadable file
    filename = f"service_history_{download_tag(vehicle, vehicle.nickname)}_{datetime.now().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([body]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{vin}/reports/all-records-csv")
async def download_all_records_csv(
    vin: str,
    year: int | None = Query(None, ge=1, description="Filter by year"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Export all maintenance records to CSV, in the caller's own units."""
    # Same render policy as `download_service_history_csv`, and for the same
    # reasons: the caller's units, no `?units=` parameter, `show_both` ignored.
    #
    # Distance and volume resolve independently, so a metric account that
    # prefers US gallons gets `Odometer (km)` alongside `Volume (gal_us)`.
    # The vehicle's own odometer unit applies as in the service-history CSV.
    vehicle = await get_vehicle_or_403(vin, current_user, db)
    context = await render_context_for_request(current_user, db, vehicle=vehicle)
    body = await report_service.all_records_csv(db, vehicle, context, year)

    # Return as downloadable file
    filename = f"all_records_{download_tag(vehicle, vehicle.nickname)}_{datetime.now().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([body]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
