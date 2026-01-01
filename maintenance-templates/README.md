# MyGarage Maintenance Templates

Community-maintained maintenance schedule templates for [MyGarage](https://github.com/homelabforge/mygarage).

## What is this?

This repository contains pre-built maintenance schedule templates for various vehicles. When you add a vehicle to MyGarage, it can automatically download and apply the appropriate maintenance schedule based on your vehicle's year, make, and model.

## Supported Vehicles

Currently focused on **American trucks (2019-2024)**:

### RAM
- RAM 1500 (2019-2024)
- RAM 2500 (2019-2024)
- RAM 3500 (2019-2024)

### Ford
- F-150 (2019-2024)
- F-250 Super Duty (2019-2024)
- F-350 Super Duty (2019-2024)

### Chevrolet
- Silverado 1500 (2019-2024)
- Silverado 2500HD (2019-2024)
- Silverado 3500HD (2019-2024)

### GMC
- Sierra 1500 (2019-2024)

## How it Works

1. You create a vehicle in MyGarage
2. MyGarage checks this repository for a matching template
3. If found, the template is downloaded and converted into maintenance reminders
4. Reminders appear on your dashboard with due dates and mileage intervals

## Template Format

Templates are written in YAML format. Example:

```yaml
metadata:
  make: RAM
  model: "1500"
  year_start: 2019
  year_end: 2024
  duty_type: normal
  source: "RAM Owner's Manual 2024"
  contributor: "jamey"
  version: "1.0.0"

maintenance_items:
  - description: "Engine Oil & Filter Change"
    interval_months: 12
    interval_miles: 10000
    category: "Engine"
    severity: "critical"
    notes: "Use Mopar 5W-20 or equivalent"

  - description: "Tire Rotation"
    interval_months: 12
    interval_miles: 10000
    category: "Tires"
    severity: "normal"
    notes: "Rotate tires and check pressure"
```

## Contributing

We welcome community contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

### Quick Start for Contributors

1. Fork this repository
2. Create a new template in the appropriate directory
3. Follow the template schema (see `schemas/template-schema.json`)
4. Validate your template: `python scripts/validate.py templates/your-template.yml`
5. Submit a pull request

## Directory Structure

```
templates/
├── ram/
│   ├── 1500/
│   │   ├── 2019-2024-normal.yml
│   │   └── 2019-2024-severe.yml
│   ├── 2500/
│   └── 3500/
├── ford/
│   ├── f-150/
│   ├── f-250/
│   └── f-350/
└── chevrolet/
    ├── silverado-1500/
    ├── silverado-2500hd/
    └── silverado-3500hd/
```

## Duty Types

- **normal**: Standard driving conditions
- **severe**: Frequent towing, dusty environments, extreme temperatures, short trips in freezing weather

## License

MIT License - See [LICENSE](LICENSE) for details.

## Disclaimer

These templates are community-maintained and based on publicly available owner's manuals and maintenance guides. Always consult your vehicle's official documentation and follow manufacturer recommendations. MyGarage and contributors are not responsible for maintenance decisions based on these templates.

## Support

- Report issues: [GitHub Issues](https://github.com/homelabforge/mygarage-maintenance-templates/issues)
- Request a vehicle template: [Request Template](https://github.com/homelabforge/mygarage-maintenance-templates/issues/new?template=template_request.md)
- MyGarage documentation: [homelabforge.io](https://homelabforge.io)
