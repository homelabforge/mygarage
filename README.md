# MyGarage

Self-hosted vehicle maintenance tracking with VIN decoding, service records, fuel logging, and document management.

[![CI](https://github.com/homelabforge/mygarage/actions/workflows/ci.yml/badge.svg)](https://github.com/homelabforge/mygarage/actions/workflows/ci.yml)
[![Docker Build](https://github.com/homelabforge/mygarage/actions/workflows/docker-build.yml/badge.svg)](https://github.com/homelabforge/mygarage/actions/workflows/docker-build.yml)
[![CodeQL](https://github.com/homelabforge/mygarage/actions/workflows/codeql.yml/badge.svg)](https://github.com/homelabforge/mygarage/actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-2.14.4-green.svg)](https://github.com/homelabforge/mygarage/releases)
[![Docker](https://img.shields.io/badge/Docker-Available-2496ED?logo=docker&logoColor=white)](https://github.com/homelabforge/mygarage/pkgs/container/mygarage)
[![Python 3.14+](https://img.shields.io/badge/Python-3.14+-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev)
[![Bun 1.3.4+](https://img.shields.io/badge/Bun-1.3.4+-000000?logo=bun&logoColor=white)](https://bun.sh)

![MyGarage Dashboard](docs/screenshots/dashboard.png)

**📚 [Full Documentation (Wiki)](https://github.com/homelabforge/mygarage/wiki)** | **🌐 [Website](https://homelabforge.io/builds/mygarage/)** | **⭐ [Star on GitHub](https://github.com/homelabforge/mygarage)**

---

## Quick Start

```yaml
version: '3.8'

services:
  mygarage:
    image: ghcr.io/homelabforge/mygarage:latest
    container_name: mygarage
    ports:
      - "8686:8686"
    volumes:
      - ./data:/data
    restart: unless-stopped
```

```bash
docker-compose up -d
```

Open http://localhost:8686 and start tracking your vehicles.

**Default Mode**: Runs with no authentication for easy setup. Configure authentication in Settings before exposing to the internet.

📖 **[Complete Installation Guide](https://github.com/homelabforge/mygarage/wiki/Installation)**

---

## Key Features

- **VIN Decoding** - Automatic vehicle details via NHTSA API
- **Service Records** - Track maintenance with attachments and reminders
- **Fuel Tracking** - Log fill-ups with automatic MPG calculations
- **Fifth Wheel & Trailer Support** - Propane tracking, spot rental billing, and RV park management
- **Unit Conversion** - Imperial/Metric units with per-user preferences
- **Document Management** - Store registration, insurance, manuals with OCR
- **Multi-User Support** - Separate accounts with admin controls
- **Authentication Options** - No auth, local JWT, or OIDC (Authentik, Keycloak, Google, Azure AD)
- **Self-Hosted** - Your data stays on your infrastructure

---

## Documentation

### Getting Started
- **[Installation](https://github.com/homelabforge/mygarage/wiki/Installation)** - Docker setup and configuration
- **[Quick Start Guide](https://github.com/homelabforge/mygarage/wiki/Quick-Start)** - Get running in 5 minutes
- **[First Time Setup](https://github.com/homelabforge/mygarage/wiki/First-Time-Setup)** - Initial configuration

### Features
- **[Managing Vehicles](https://github.com/homelabforge/mygarage/wiki/Managing-Vehicles)** - Adding and organizing vehicles
- **[Service Records](https://github.com/homelabforge/mygarage/wiki/Service-Records)** - Maintenance tracking
- **[Fuel Tracking](https://github.com/homelabforge/mygarage/wiki/Fuel-Tracking)** - MPG and economy analytics
- **[Fifth Wheels & RVs](https://github.com/homelabforge/mygarage/wiki/Fifth-Wheels-And-RVs)** - RV-specific features
- **[Documents](https://github.com/homelabforge/mygarage/wiki/Documents)** - File management and OCR
- **[Dashboard](https://github.com/homelabforge/mygarage/wiki/Dashboard)** - Overview and analytics

### Configuration
- **[Authentication](https://github.com/homelabforge/mygarage/wiki/Authentication)** - Local, OIDC, and SSO setup
- **[Database Configuration](https://github.com/homelabforge/mygarage/wiki/Database-Configuration)** - SQLite vs PostgreSQL
- **[Reverse Proxy](https://github.com/homelabforge/mygarage/wiki/Reverse-Proxy)** - Traefik, Nginx, Caddy examples

### Help
- **[FAQ](https://github.com/homelabforge/mygarage/wiki/FAQ)** - Common questions
- **[Troubleshooting](https://github.com/homelabforge/mygarage/wiki/Troubleshooting)** - Fix common issues

---

## Technology Stack

**Backend:** FastAPI (Python), SQLAlchemy, SQLite/PostgreSQL, JWT Auth, OIDC Support
**Frontend:** React, TypeScript, Tailwind CSS, Bun, Vite

---


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
