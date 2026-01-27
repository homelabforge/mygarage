<div align="center">
  
Self-hosted vehicle maintenance tracking with VIN decoding, service records, fuel logging, and document management.

[![Docker Build](https://github.com/homelabforge/mygarage/actions/workflows/docker-build.yml/badge.svg)](https://github.com/homelabforge/mygarage/actions/workflows/docker-build.yml)
[![CodeQL](https://github.com/homelabforge/mygarage/actions/workflows/codeql.yml/badge.svg)](https://github.com/homelabforge/mygarage/actions/workflows/codeql.yml)
[![CI](https://github.com/homelabforge/mygarage/actions/workflows/ci.yml/badge.svg)](https://github.com/homelabforge/mygarage/actions/workflows/ci.yml)

[![Docker](https://img.shields.io/badge/Docker-Available-2496ED?logo=docker&logoColor=white)](https://github.com/homelabforge/mygarage/pkgs/container/mygarage)
[![Python 3.14](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev)
[![Bun 1.3.7](https://img.shields.io/badge/Bun-1.3.7-000000?logo=bun&logoColor=white)](https://bun.sh)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

![MyGarage Dashboard](docs/screenshots/dashboard.png)

</div>

---

## Key Features

- **VIN Decoding** - Automatic vehicle details via NHTSA API
- **Service Visits** - Track maintenance with line items, tax/fees, and attachments
- **Maintenance Scheduling** - Proactive maintenance tracking with due date/mileage alerts
- **POI Finder** - Discover nearby auto shops, EV charging, and fuel stations with interactive map
- **Fuel Tracking** - Log fill-ups with automatic MPG calculations
- **Fifth Wheel & Trailer Support** - Propane tracking, spot rental billing, and RV park management
- **Unit Conversion** - Imperial/Metric units with per-user preferences
- **Document Management** - Store registration, insurance, manuals with OCR
- **Multi-User Support** - Separate accounts with admin controls
- **Authentication Options** - No auth, local JWT, or OIDC (Authentik, Keycloak, Google, Azure AD)
- **Self-Hosted** - Your data stays on your infrastructure

---

**Default Mode**: Runs with no authentication for easy setup. Configure authentication in Settings before exposing to the internet.

📖 **[Complete Installation Guide](https://github.com/homelabforge/mygarage/wiki/Installation)**

## Support

- **📚 Documentation**: [GitHub Wiki](https://github.com/homelabforge/mygarage/wiki)
- **🌐 Website**: [homelabforge.io/builds/mygarage](https://homelabforge.io/builds/mygarage/)
- **🐛 Bug Reports**: [GitHub Issues](https://github.com/homelabforge/mygarage/issues)
- **💬 Discussions**: [GitHub Discussions](https://github.com/homelabforge/mygarage/discussions)

---

## License

MIT License - see [LICENSE](LICENSE) file for details.

---

## Acknowledgments

Built for homelabbers who want to track vehicle maintenance without sending data to third-party services.

VIN decoding powered by the [NHTSA vPIC API](https://vpic.nhtsa.dot.gov/).

### Development Assistance

MyGarage was developed through AI-assisted pair programming with **Claude** and **Codex**, combining human vision with AI capabilities for architecture, security patterns, and implementation.
