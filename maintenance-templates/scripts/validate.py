#!/usr/bin/env python3
"""
Validate MyGarage maintenance template YAML files.

Usage:
    python scripts/validate.py templates/ram/1500/2019-2024-normal.yml
    python scripts/validate.py templates/  # Validate all templates
"""

import sys
from pathlib import Path
import yaml


VALID_CATEGORIES = {
    "Engine",
    "Transmission",
    "Drivetrain",
    "Brakes",
    "Tires",
    "Suspension",
    "Steering",
    "Electrical",
    "HVAC",
    "Fuel System",
    "Exhaust",
    "Emissions",
    "Cooling System",
    "Hybrid System",
    "Towing",
    "General",
}

VALID_SEVERITIES = {"critical", "normal", "optional"}
VALID_DUTY_TYPES = {"normal", "severe"}


def validate_metadata(metadata: dict, filepath: Path) -> list[str]:
    """Validate template metadata section."""
    errors = []

    # Required fields
    required = ["make", "model", "year_start", "year_end", "duty_type", "source", "contributor", "version"]
    for field in required:
        if field not in metadata:
            errors.append(f"Missing required metadata field: {field}")

    # Make should be uppercase
    if "make" in metadata and not metadata["make"].isupper():
        errors.append(f"'make' should be UPPERCASE, got: {metadata['make']}")

    # Year validation
    if "year_start" in metadata and "year_end" in metadata:
        if not isinstance(metadata["year_start"], int) or not isinstance(metadata["year_end"], int):
            errors.append("year_start and year_end must be integers")
        elif metadata["year_start"] > metadata["year_end"]:
            errors.append(f"year_start ({metadata['year_start']}) must be <= year_end ({metadata['year_end']})")
        elif metadata["year_start"] < 2000 or metadata["year_end"] > 2030:
            errors.append(f"Years must be between 2000 and 2030")

    # Duty type validation
    if "duty_type" in metadata and metadata["duty_type"] not in VALID_DUTY_TYPES:
        errors.append(f"Invalid duty_type: {metadata['duty_type']}. Must be one of: {VALID_DUTY_TYPES}")

    # Version format (basic semver check)
    if "version" in metadata:
        version = metadata["version"]
        if not isinstance(version, str) or not all(part.isdigit() for part in version.split(".")):
            errors.append(f"Invalid version format: {version}. Use semver (e.g., '1.0.0')")

    return errors


def validate_maintenance_item(item: dict, index: int) -> list[str]:
    """Validate a single maintenance item."""
    errors = []

    # Required fields
    required = ["description", "category", "severity"]
    for field in required:
        if field not in item:
            errors.append(f"Item {index}: Missing required field: {field}")

    # At least one interval
    if "interval_months" not in item and "interval_miles" not in item:
        errors.append(f"Item {index}: Must have at least one of interval_months or interval_miles")

    # Category validation
    if "category" in item and item["category"] not in VALID_CATEGORIES:
        errors.append(f"Item {index}: Invalid category: {item['category']}. Must be one of: {VALID_CATEGORIES}")

    # Severity validation
    if "severity" in item and item["severity"] not in VALID_SEVERITIES:
        errors.append(f"Item {index}: Invalid severity: {item['severity']}. Must be one of: {VALID_SEVERITIES}")

    # Interval validation
    if "interval_months" in item and item["interval_months"] is not None:
        if not isinstance(item["interval_months"], int) or item["interval_months"] < 1:
            errors.append(f"Item {index}: interval_months must be positive integer or null")

    if "interval_miles" in item and item["interval_miles"] is not None:
        if not isinstance(item["interval_miles"], int) or item["interval_miles"] < 100:
            errors.append(f"Item {index}: interval_miles must be >= 100 or null")

    # Description length
    if "description" in item:
        desc_len = len(item["description"])
        if desc_len < 5:
            errors.append(f"Item {index}: description too short ({desc_len} chars, minimum 5)")
        elif desc_len > 200:
            errors.append(f"Item {index}: description too long ({desc_len} chars, maximum 200)")

    return errors


def validate_template(filepath: Path) -> tuple[bool, list[str]]:
    """Validate a template file."""
    errors = []

    # Check file exists
    if not filepath.exists():
        return False, [f"File not found: {filepath}"]

    # Load YAML
    try:
        with open(filepath, "r") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return False, [f"YAML syntax error: {e}"]
    except Exception as e:
        return False, [f"Error reading file: {e}"]

    # Check top-level structure
    if not isinstance(data, dict):
        return False, ["Template must be a YAML object/dict"]

    if "metadata" not in data:
        errors.append("Missing 'metadata' section")
    else:
        errors.extend(validate_metadata(data["metadata"], filepath))

    if "maintenance_items" not in data:
        errors.append("Missing 'maintenance_items' section")
    elif not isinstance(data["maintenance_items"], list):
        errors.append("'maintenance_items' must be a list")
    elif len(data["maintenance_items"]) == 0:
        errors.append("'maintenance_items' must contain at least one item")
    else:
        for i, item in enumerate(data["maintenance_items"], start=1):
            if not isinstance(item, dict):
                errors.append(f"Item {i}: must be a dict/object")
            else:
                errors.extend(validate_maintenance_item(item, i))

    return len(errors) == 0, errors


def validate_all_templates(templates_dir: Path) -> tuple[int, int, list[str]]:
    """Validate all templates in a directory."""
    total = 0
    passed = 0
    all_errors = []

    for yml_file in templates_dir.rglob("*.yml"):
        # Skip non-template files
        if yml_file.parent.name in ["schemas", "scripts"]:
            continue

        total += 1
        valid, errors = validate_template(yml_file)

        if valid:
            passed += 1
            print(f"✓ {yml_file.relative_to(templates_dir)}")
        else:
            print(f"✗ {yml_file.relative_to(templates_dir)}")
            for error in errors:
                print(f"  - {error}")
            all_errors.extend([f"{yml_file.name}: {e}" for e in errors])

    return total, passed, all_errors


def main():
    if len(sys.argv) < 2:
        print("Usage: python validate.py <template-file-or-directory>")
        sys.exit(1)

    target = Path(sys.argv[1])

    if target.is_file():
        # Validate single file
        valid, errors = validate_template(target)
        if valid:
            print(f"✓ {target.name} is valid")
            sys.exit(0)
        else:
            print(f"✗ {target.name} has errors:")
            for error in errors:
                print(f"  - {error}")
            sys.exit(1)

    elif target.is_dir():
        # Validate all templates in directory
        print(f"Validating templates in {target}...\n")
        total, passed, errors = validate_all_templates(target)

        print(f"\n{'='*60}")
        print(f"Results: {passed}/{total} templates passed")
        print(f"{'='*60}")

        if passed == total:
            print("✓ All templates are valid!")
            sys.exit(0)
        else:
            print(f"✗ {total - passed} template(s) have errors")
            sys.exit(1)

    else:
        print(f"Error: {target} is not a file or directory")
        sys.exit(1)


if __name__ == "__main__":
    main()
