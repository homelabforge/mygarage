"""
Maintenance Template Service

Handles fetching, parsing, and applying maintenance schedule templates
from the GitHub repository.
"""

import logging
import re
from urllib.parse import urlparse

import httpx
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.maintenance_schedule_item import MaintenanceScheduleItem
from app.models.maintenance_template import MaintenanceTemplate
from app.models.vehicle import Vehicle
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

# Allowed GitHub hosts for template fetching (SSRF protection)
ALLOWED_GITHUB_HOSTS = frozenset(["raw.githubusercontent.com", "github.com", "raw.github.com"])

# Regex for valid path components (alphanumeric, hyphens, underscores)
SAFE_PATH_COMPONENT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class MaintenanceTemplateService:
    """Service for managing maintenance schedule templates."""

    def __init__(self):
        self.timeout = 10.0  # 10-second timeout for GitHub requests
        # GitHub raw content base URL
        self.github_base_url = "https://raw.githubusercontent.com/homelabforge/mygarage/main/maintenance-templates/templates"

    def _validate_template_url(self, url: str) -> bool:
        """Validate that a URL is safe to fetch (SSRF protection).

        Args:
            url: The URL to validate

        Returns:
            True if URL is safe, False otherwise
        """
        try:
            parsed = urlparse(url)

            # Must be HTTPS
            if parsed.scheme != "https":
                logger.warning("Blocked non-HTTPS URL: %s", sanitize_for_log(url))
                return False

            # Must be an allowed GitHub host
            if parsed.hostname not in ALLOWED_GITHUB_HOSTS:
                logger.warning("Blocked URL with disallowed host: %s", sanitize_for_log(url))
                return False

            # Path must not contain traversal sequences
            if ".." in parsed.path or "//" in parsed.path:
                logger.warning("Blocked URL with path traversal: %s", sanitize_for_log(url))
                return False

            return True
        except Exception as e:
            logger.error("URL validation error: %s", sanitize_for_log(e))
            return False

    def _sanitize_path_component(self, component: str) -> str | None:
        """Sanitize a path component for safe URL construction.

        Args:
            component: A path component (make, model, etc.)

        Returns:
            Sanitized component or None if invalid
        """
        if not component:
            return None

        # Normalize: lowercase, strip whitespace
        clean = component.lower().strip()

        # Replace spaces with hyphens
        clean = clean.replace(" ", "-")

        # Remove any characters that aren't alphanumeric, hyphen, or underscore
        clean = re.sub(r"[^a-z0-9_-]", "", clean)

        # Validate against safe pattern
        if not SAFE_PATH_COMPONENT_RE.match(clean):
            logger.warning(
                "Invalid path component after sanitization: %s -> %s",
                sanitize_for_log(component),
                sanitize_for_log(clean),
            )
            return None

        return clean

    def _normalize_make(self, make: str) -> str:
        """
        Normalize manufacturer name to match GitHub folder structure.

        Examples:
            - "Dodge Ram" -> "ram"
            - "RAM" -> "ram"
            - "FORD" -> "ford"
            - "CHEVROLET" -> "chevrolet"
            - "MITSUBISHI" -> "mitsubishi"
        """
        make_lower = make.lower().strip()

        # Handle special cases
        if "ram" in make_lower or "dodge" in make_lower:
            return "ram"
        elif "chevy" in make_lower or "chevrolet" in make_lower:
            return "chevrolet"
        elif "gmc" in make_lower:
            return "gmc"
        elif "mitsubishi" in make_lower:
            return "mitsubishi"

        return make_lower

    def _normalize_model(self, model: str) -> str:
        """
        Normalize model name to match GitHub folder structure.

        Examples:
            - "F150" -> "f-150"
            - "F-150" -> "f-150"
            - "Silverado 1500" -> "silverado-1500"
            - "1500" -> "1500"
        """
        model_lower = model.lower().strip()

        # Add hyphen to F-series if missing
        if model_lower.startswith("f") and model_lower[1:].isdigit():
            return f"f-{model_lower[1:]}"

        # Replace spaces with hyphens
        return model_lower.replace(" ", "-")

    def _normalize_fuel_type(self, fuel_type: str | None) -> str | None:
        """
        Normalize fuel type to match template naming convention.

        Args:
            fuel_type: Raw fuel type from vehicle data

        Returns:
            Normalized fuel type ("diesel" or "gas") or None
        """
        if not fuel_type:
            return None

        fuel_lower = fuel_type.lower().strip()

        # Diesel variants
        if "diesel" in fuel_lower:
            return "diesel"

        # Gasoline variants
        if any(keyword in fuel_lower for keyword in ["gas", "gasoline", "petrol", "flex", "e85"]):
            return "gas"

        # Electric/Hybrid - no fuel-specific templates yet
        if "electric" in fuel_lower or "hybrid" in fuel_lower:
            return None

        return None

    def _build_template_path(
        self,
        make: str,
        model: str,
        year: int,
        duty_type: str = "normal",
        fuel_type: str | None = None,
    ) -> str:
        """
        Build the GitHub path for a template.

        Args:
            make: Vehicle manufacturer
            model: Vehicle model
            year: Vehicle year
            duty_type: "normal" or "severe"
            fuel_type: Optional fuel type ("Diesel", "Gasoline", etc.)

        Returns:
            GitHub path like "ram/3500/2019-2025-diesel-normal.yml"
        """
        norm_make = self._normalize_make(make)
        norm_model = self._normalize_model(model)
        norm_fuel = self._normalize_fuel_type(fuel_type)

        # Determine year range (we use 2019-2025 for modern vehicles)
        # This is a simple approach - could be enhanced to search multiple year ranges
        if year >= 2019:
            year_range = "2019-2025"
        elif year >= 2015:
            year_range = "2015-2018"
        else:
            year_range = f"{year}-{year + 4}"  # Guess a 5-year range

        # Build filename with optional fuel type
        if norm_fuel:
            filename = f"{year_range}-{norm_fuel}-{duty_type}.yml"
        else:
            filename = f"{year_range}-{duty_type}.yml"

        return f"{norm_make}/{norm_model}/{filename}"

    async def find_template_for_vehicle(
        self,
        year: int,
        make: str,
        model: str,
        duty_type: str = "normal",
        fuel_type: str | None = None,
    ) -> tuple[str, dict] | None:
        """
        Search for a maintenance template for a specific vehicle.

        Implements fallback logic:
        1. Try with fuel_type specified (e.g., "2019-2025-diesel-normal.yml")
        2. Try without fuel_type (e.g., "2019-2025-normal.yml")
        3. Try alternate year ranges if 2019-2025 doesn't exist

        Args:
            year: Vehicle year
            make: Vehicle manufacturer
            model: Vehicle model
            duty_type: "normal" or "severe"
            fuel_type: Optional fuel type ("Diesel", "Gasoline", etc.)

        Returns:
            Tuple of (template_path, template_data) if found, None otherwise
        """
        # Build list of paths to try (in order of specificity)
        paths_to_try = []

        # 1. Try with fuel type if provided
        if fuel_type:
            paths_to_try.append(self._build_template_path(make, model, year, duty_type, fuel_type))

        # 2. Try without fuel type (fallback for older templates)
        paths_to_try.append(self._build_template_path(make, model, year, duty_type))

        # 3. Try alternate year ranges (2019-2024 as fallback for 2019-2025)
        norm_make = self._normalize_make(make)
        norm_model = self._normalize_model(model)
        norm_fuel = self._normalize_fuel_type(fuel_type)

        if year >= 2019:
            # Try 2019-2024 as fallback
            if norm_fuel:
                paths_to_try.append(
                    f"{norm_make}/{norm_model}/2019-2024-{norm_fuel}-{duty_type}.yml"
                )
            paths_to_try.append(f"{norm_make}/{norm_model}/2019-2024-{duty_type}.yml")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for template_path in paths_to_try:
                template_url = f"{self.github_base_url}/{template_path}"

                # SSRF protection: validate URL before making request
                if not self._validate_template_url(template_url):
                    logger.warning(
                        "Skipping invalid template URL: %s",
                        sanitize_for_log(template_url),
                    )
                    continue

                logger.info("Trying template: %s", sanitize_for_log(template_url))

                try:
                    response = await client.get(template_url)
                    response.raise_for_status()

                    # Parse YAML
                    template_data = yaml.safe_load(response.text)

                    logger.info(
                        "Successfully fetched template: %s",
                        sanitize_for_log(template_path),
                    )
                    return (template_path, template_data)

                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        logger.info("Template not found: %s", sanitize_for_log(template_path))
                        continue  # Try next path
                    logger.error("HTTP error fetching template: %s", sanitize_for_log(e))
                    continue
                except yaml.YAMLError as e:
                    logger.error(
                        "YAML parse error for %s: %s",
                        sanitize_for_log(template_path),
                        sanitize_for_log(e),
                    )
                    continue
                except Exception as e:
                    logger.error(
                        "Error fetching template %s: %s",
                        sanitize_for_log(template_path),
                        sanitize_for_log(e),
                    )
                    continue

        # No templates found after trying all paths
        logger.warning(
            "No template found for %s %s %s (%s duty, fuel: %s)",
            year,
            sanitize_for_log(make),
            sanitize_for_log(model),
            sanitize_for_log(duty_type),
            sanitize_for_log(fuel_type),
        )
        return None

    @staticmethod
    def _slugify_description(description: str) -> str:
        """Generate a stable template_item_id from a description.

        Args:
            description: Maintenance item description

        Returns:
            Slugified string like "engine-oil-filter-change"
        """
        slug = description.lower().strip()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        return slug.strip("-")

    @staticmethod
    def _infer_item_type(description: str) -> str:
        """Infer whether a template item is a service or inspection.

        Args:
            description: Maintenance item description

        Returns:
            "inspection" or "service"
        """
        desc_lower = description.lower()
        if "inspection" in desc_lower or "check" in desc_lower:
            return "inspection"
        return "service"

    async def apply_template_to_vehicle(
        self,
        db: AsyncSession,
        vin: str,
        template_path: str,
        template_data: dict,
        current_mileage: int | None = None,
        created_by: str = "auto",
    ) -> int:
        """
        Apply a maintenance template to a vehicle by creating schedule items.

        Args:
            db: Database session
            vin: Vehicle VIN
            template_path: Path to template (e.g., "ram/1500/2019-2024-normal.yml")
            template_data: Parsed template YAML data
            current_mileage: Current vehicle mileage (unused, kept for API compat)
            created_by: "auto" or "manual"

        Returns:
            Number of schedule items created
        """
        # Verify vehicle exists
        result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
        vehicle = result.scalar_one_or_none()
        if not vehicle:
            raise ValueError(f"Vehicle with VIN {vin} not found")

        # Extract maintenance items
        maintenance_items = template_data.get("maintenance_items", [])
        if not maintenance_items:
            logger.warning("No maintenance items in template %s", sanitize_for_log(template_path))
            return 0

        # Get existing template_item_ids for this VIN to avoid duplicates
        existing_result = await db.execute(
            select(MaintenanceScheduleItem.template_item_id).where(
                MaintenanceScheduleItem.vin == vin,
                MaintenanceScheduleItem.template_item_id.isnot(None),
            )
        )
        existing_ids = {row[0] for row in existing_result}

        items_created = 0

        for item in maintenance_items:
            try:
                description = item.get("description")
                if not description:
                    continue

                template_item_id = self._slugify_description(description)

                # Skip duplicates
                if template_item_id in existing_ids:
                    logger.info(
                        "Skipping duplicate template item %s for %s",
                        sanitize_for_log(template_item_id),
                        sanitize_for_log(vin),
                    )
                    continue

                schedule_item = MaintenanceScheduleItem(
                    vin=vin,
                    name=description,
                    component_category=item.get("category", "Other"),
                    item_type=self._infer_item_type(description),
                    interval_months=item.get("interval_months"),
                    interval_miles=item.get("interval_miles"),
                    source="template",
                    template_item_id=template_item_id,
                )

                db.add(schedule_item)
                existing_ids.add(template_item_id)
                items_created += 1

            except Exception as e:
                logger.error(
                    "Error creating schedule item for %s: %s",
                    sanitize_for_log(item),
                    sanitize_for_log(e),
                )
                continue

        # Save template application record
        template_record = MaintenanceTemplate(
            vin=vin,
            template_source=f"github:{template_path}",
            template_version=template_data.get("metadata", {}).get("version"),
            template_data=template_data,
            created_by=created_by,
            reminders_created=items_created,
        )
        db.add(template_record)

        await db.commit()

        logger.info(
            "Applied template %s to %s, created %d schedule items",
            sanitize_for_log(template_path),
            sanitize_for_log(vin),
            items_created,
        )

        return items_created

    async def get_applied_templates(self, db: AsyncSession, vin: str) -> list[MaintenanceTemplate]:
        """
        Get all templates that have been applied to a vehicle.

        Args:
            db: Database session
            vin: Vehicle VIN

        Returns:
            List of MaintenanceTemplate records
        """
        result = await db.execute(
            select(MaintenanceTemplate)
            .where(MaintenanceTemplate.vin == vin)
            .order_by(MaintenanceTemplate.applied_at.desc())
        )
        return list(result.scalars().all())
