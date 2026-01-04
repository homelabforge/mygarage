"""API routes for MyGarage."""

from app.routes.vin import router as vin_router
from app.routes.vehicles import router as vehicles_router
from app.routes.photos import router as photos_router
from app.routes.service import router as service_router
from app.routes.fuel import router as fuel_router
from app.routes.odometer import router as odometer_router
from app.routes.documents import router as documents_router
from app.routes.reminders import router as reminders_router
from app.routes.notes import router as notes_router
from app.routes.dashboard import router as dashboard_router
from app.routes.export import router as export_router
from app.routes.import_data import router as import_router
from app.routes.analytics import router as analytics_router
from app.routes.warranty import router as warranty_router
from app.routes.insurance import router as insurance_router
from app.routes.reports import router as reports_router
from app.routes.toll import toll_tags_router, toll_transactions_router
from app.routes.recall import recalls_router
from app.routes.settings import router as settings_router
from app.routes.backup import router as backup_router
from app.routes.attachments import router as attachments_router
from app.routes.tax import router as tax_router
from app.routes.spot_rental import router as spot_rental_router
from app.routes.spot_rental_billing import router as spot_rental_billing_router
from app.routes.address_book import router as address_book_router
from app.routes.calendar import router as calendar_router
from app.routes.window_sticker import router as window_sticker_router
from app.routes.notifications import router as notifications_router
from app.routes.maintenance_templates import maintenance_templates_router
from app.routes.shop_discovery import router as shop_discovery_router

__all__ = [
    "vin_router",
    "vehicles_router",
    "photos_router",
    "service_router",
    "fuel_router",
    "odometer_router",
    "documents_router",
    "reminders_router",
    "notes_router",
    "dashboard_router",
    "export_router",
    "import_router",
    "analytics_router",
    "warranty_router",
    "insurance_router",
    "reports_router",
    "toll_tags_router",
    "toll_transactions_router",
    "recalls_router",
    "settings_router",
    "backup_router",
    "attachments_router",
    "tax_router",
    "spot_rental_router",
    "spot_rental_billing_router",
    "address_book_router",
    "calendar_router",
    "window_sticker_router",
    "notifications_router",
    "maintenance_templates_router",
    "shop_discovery_router",
]
