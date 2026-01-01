# Contributing to MyGarage Maintenance Templates

Thank you for contributing to the MyGarage Maintenance Templates repository! This guide will help you create high-quality templates for the community.

## How to Contribute

### 1. Fork and Clone

```bash
git clone https://github.com/homelabforge/mygarage.git
cd mygarage/maintenance-templates
```

### 2. Create a New Template

Templates are organized by manufacturer, model, and year range:

```
templates/
└── manufacturer/
    └── model/
        └── YYYY-YYYY-duty.yml
```

**Example:** `templates/ram/1500/2019-2024-normal.yml`

### 3. Follow the Template Format

Use this structure for your template:

```yaml
metadata:
  make: MANUFACTURER        # UPPERCASE (e.g., RAM, FORD, CHEVROLET)
  model: "Model Name"       # Exact model name (e.g., "1500", "F-150")
  year_start: 2019          # First year this template applies to
  year_end: 2024            # Last year this template applies to
  duty_type: normal         # "normal" or "severe"
  source: "Source Document" # Where you got this info
  contributor: "github-username"
  version: "1.0.0"          # Semantic versioning
  notes: |
    Optional notes about when to use severe duty vs normal duty

maintenance_items:
  - description: "Engine Oil & Filter Change"
    interval_months: 12     # Integer or null
    interval_miles: 10000   # Integer or null
    category: "Engine"      # See categories list below
    severity: "critical"    # critical, normal, or optional
    notes: "Additional details about this maintenance item"
```

### 4. Required Fields

**Metadata:**
- `make`, `model`, `year_start`, `year_end`
- `duty_type`, `source`, `contributor`, `version`

**Maintenance Items:**
- `description`, `category`, `severity`
- At least one of: `interval_months` or `interval_miles`

### 5. Valid Categories

Use one of these categories for each maintenance item:

- Engine
- Transmission
- Drivetrain
- Brakes
- Tires
- Suspension
- Steering
- Electrical
- HVAC
- Fuel System
- Exhaust
- Emissions
- Cooling System
- Hybrid System
- Towing
- General

### 6. Severity Levels

- **critical**: Safety-critical or prevents major damage (oil changes, brakes, coolant)
- **normal**: Standard maintenance (tire rotation, filters, inspections)
- **optional**: Nice-to-have or convenience items

### 7. Validate Your Template

Before submitting, validate your template:

```bash
python scripts/validate.py templates/your-manufacturer/your-model/your-template.yml
```

This checks:
- YAML syntax
- Required fields
- Valid categories and severity levels
- Proper formatting

### 8. Submit a Pull Request

1. Commit your template:
   ```bash
   git add templates/your-manufacturer/your-model/your-template.yml
   git commit -m "Add maintenance template for [Year Range] [Make] [Model]"
   ```

2. Push to your fork:
   ```bash
   git push origin main
   ```

3. Open a pull request on GitHub

## Guidelines

### Data Sources

Use **official manufacturer documentation** as your source:
- Owner's manuals
- Maintenance guides
- Service bulletins
- Dealership maintenance schedules

**Avoid:**
- Third-party websites (unless they cite official sources)
- Forum posts or anecdotal information
- Aftermarket recommendations

### Accuracy is Critical

People rely on these templates for vehicle maintenance. Ensure:
- All intervals match manufacturer recommendations
- Service descriptions are clear and specific
- Notes include important details (fluid types, special tools, etc.)

### Normal vs. Severe Duty

**Normal Duty:**
- Most daily driving
- Highway commuting
- Occasional towing (within limits)

**Severe Duty (create separate template):**
- Frequent trailer towing
- Dusty/off-road driving
- Extreme temperatures
- Short trips in freezing weather
- Commercial use, police/taxi service

### Maintenance Item Best Practices

**Good Description:**
```yaml
- description: "Engine Oil & Filter Change - 6.7L Cummins Diesel"
  interval_miles: 15000
  notes: "Use CK-4 or FA-4 15W-40 diesel engine oil. Severe duty: 7,500 miles"
```

**Bad Description:**
```yaml
- description: "Change oil"
  interval_miles: 15000
  notes: "Use good oil"
```

**Include specifics:**
- Engine type if multiple options (V6, V8, diesel)
- Fluid specifications (SAE 5W-30, Dexos1, ATF+4)
- Severe duty intervals in notes
- Part numbers if helpful

### Version Updates

If updating an existing template:
1. Increment version number (semver: MAJOR.MINOR.PATCH)
2. Document changes in git commit message
3. Consider if old version should remain for older years

## Template Naming Convention

Use this format:

```
YYYY-YYYY-duty.yml
```

Examples:
- `2019-2024-normal.yml`
- `2019-2024-severe.yml`
- `2015-2018-normal.yml`

## Questions?

- Open an issue: [GitHub Issues](https://github.com/homelabforge/mygarage/issues)
- Ask in discussions: [GitHub Discussions](https://github.com/homelabforge/mygarage/discussions)

## Code of Conduct

Be respectful, constructive, and focused on accuracy. We're building a resource the community can trust.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
