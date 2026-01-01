"""
Maintenance Template Service

Handles fetching, parsing, and applying maintenance schedule templates
from the GitHub repository.
"""

import logging
import httpx
import yaml
from typing import Optional
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.maintenance_template import MaintenanceTemplate
from app.models.reminder import Reminder
from app.models.vehicle import Vehicle

logger = logging.getLogger(__name__)


class MaintenanceTemplateService:
    """Service for managing maintenance schedule templates."""

    def __init__(self):
        self.timeout = 10.0  # 10-second timeout for GitHub requests
        # GitHub raw content base URL
        self.github_base_url = "https://raw.githubusercontent.com/homelabforge/mygarage/main/maintenance-templates/templates"

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

    def _normalize_fuel_type(self, fuel_type: Optional[str]) -> Optional[str]:
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
        if any(
            keyword in fuel_lower
            for keyword in ["gas", "gasoline", "petrol", "flex", "e85"]
        ):
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
        fuel_type: Optional[str] = None,
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
        fuel_type: Optional[str] = None,
    ) -> Optional[tuple[str, dict]]:
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
            paths_to_try.append(
                self._build_template_path(make, model, year, duty_type, fuel_type)
            )

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
                logger.info(f"Trying template: {template_url}")

                try:
                    response = await client.get(template_url)
                    response.raise_for_status()

                    # Parse YAML
                    template_data = yaml.safe_load(response.text)

                    logger.info(f"Successfully fetched template: {template_path}")
                    return (template_path, template_data)

                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        logger.info(f"Template not found: {template_path}")
                        continue  # Try next path
                    logger.error(f"HTTP error fetching template: {e}")
                    continue
                except yaml.YAMLError as e:
                    logger.error(f"YAML parse error for {template_path}: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error fetching template {template_path}: {e}")
                    continue

        # No templates found after trying all paths
        logger.warning(
            f"No template found for {year} {make} {model} ({duty_type} duty, fuel: {fuel_type})"
        )
        return None

    async def apply_template_to_vehicle(
        self,
        db: AsyncSession,
        vin: str,
        template_path: str,
        template_data: dict,
        current_mileage: Optional[int] = None,
        created_by: str = "auto",
    ) -> int:
        """
        Apply a maintenance template to a vehicle by creating reminders.

        Args:
            db: Database session
            vin: Vehicle VIN
            template_path: Path to template (e.g., "ram/1500/2019-2024-normal.yml")
            template_data: Parsed template YAML data
            current_mileage: Current vehicle mileage (for mileage-based reminders)
            created_by: "auto" or "manual"

        Returns:
            Number of reminders created
        """
        # Verify vehicle exists
        result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
        vehicle = result.scalar_one_or_none()
        if not vehicle:
            raise ValueError(f"Vehicle with VIN {vin} not found")

        # Extract maintenance items
        maintenance_items = template_data.get("maintenance_items", [])
        if not maintenance_items:
            logger.warning(f"No maintenance items in template {template_path}")
            return 0

        reminders_created = 0

        for item in maintenance_items:
            try:
                description = item.get("description")
                interval_months = item.get("interval_months")
                interval_miles = item.get("interval_miles")
                notes = item.get("notes", "")

                if not description:
                    continue

                # Create reminder
                reminder = Reminder(
                    vin=vin,
                    description=description,
                    notes=notes,
                    is_completed=False,
                )

                # Set due date if interval_months is specified
                if interval_months:
                    reminder.due_date = datetime.now().date() + timedelta(
                        days=interval_months * 30
                    )
                    reminder.is_recurring = True
                    reminder.recurrence_days = interval_months * 30

                # Set due mileage if interval_miles and current_mileage are specified
                if interval_miles and current_mileage:
                    reminder.due_mileage = current_mileage + interval_miles
                    reminder.is_recurring = True
                    reminder.recurrence_miles = interval_miles

                db.add(reminder)
                reminders_created += 1

            except Exception as e:
                logger.error(f"Error creating reminder for item {item}: {e}")
                continue

        # Save template application record
        template_record = MaintenanceTemplate(
            vin=vin,
            template_source=f"github:{template_path}",
            template_version=template_data.get("metadata", {}).get("version"),
            template_data=template_data,
            created_by=created_by,
            reminders_created=reminders_created,
        )
        db.add(template_record)

        await db.commit()

        logger.info(
            f"Applied template {template_path} to {vin}, created {reminders_created} reminders"
        )

        return reminders_created

    async def get_applied_templates(
        self, db: AsyncSession, vin: str
    ) -> list[MaintenanceTemplate]:
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
        return result.scalars().all()
