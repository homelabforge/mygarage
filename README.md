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

**📚 [View Full Documentation](https://github.com/homelabforge/mygarage/wiki)** | **🌐 [Website](https://homelabforge.io/builds/mygarage/)** | **⭐ [Star on GitHub](https://github.com/homelabforge/mygarage)**

> **Love MyGarage?** Give us a ⭐ on GitHub to show your support and help others discover this project!

---

## Quick Start

### Docker Compose (Recommended)

1. Create `docker-compose.yml`:

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
    # ⚠️ PRODUCTION USERS: Change authentication mode after startup!
    # Default runs with NO authentication (auth_mode='none') for easy testing.
    # Go to Settings → System → Authentication Mode and switch to 'local' or 'oidc'
    # See Authentication Modes section below for details.
```

2. Start the container:
```bash
docker-compose up -d
```

3. Open http://localhost:8686

**That's it.** MyGarage handles everything automatically:
- ✅ Generates secret keys on first startup
- ✅ Creates SQLite database
- ✅ Runs migrations
- ✅ Initializes default settings
- ✅ Prompts for admin account on first visit

⚠️ **Default Mode**: Runs with no authentication for easy setup. You'll see a security warning in the logs:

```
⚠️  SECURITY WARNING: Authentication is disabled (auth_mode='none')
⚠️  All endpoints are accessible without authentication!
⚠️  This should NEVER be used in production environments!
```

**Before exposing to the internet**: Go to Settings → System → Authentication Mode and switch to `local` or `oidc`.

### Docker Run

```bash
docker run -d \
  --name mygarage \
  -p 8686:8686 \
  -v $(pwd)/data:/data \
  ghcr.io/homelabforge/mygarage:latest
```

---

## Key Features

- **VIN Decoding** - Automatic vehicle details via NHTSA API
- **Service Records** - Track maintenance with attachments and service reminders
- **Fuel Tracking** - Log fill-ups with automatic MPG calculations and fuel economy analytics
- **Unit Conversion** - Imperial/Metric units with per-user preferences (MPG ↔ L/100km, miles ↔ km, gallons ↔ liters)
- **Vehicle Archive** - Safely archive sold/traded vehicles while preserving complete history
- **Document Management** - Store registration, insurance, manuals with OCR text extraction
- **Photo Gallery** - Vehicle photos with thumbnails and full-size viewing
- **Multi-User Support** - Separate accounts with per-vehicle ownership and admin controls
- **Authentication Options** - No auth (dev), local JWT, or OIDC (Authentik, Keycloak, Google, Azure AD)
- **RESTful API** - Full OpenAPI documentation at `/docs`
- **Self-Hosted** - Your data stays on your infrastructure

---

## Configuration

MyGarage is **zero-config by default**. Everything is auto-generated and can be configured through the web UI after startup.

### Web UI Configuration (Recommended)

After first startup, configure MyGarage in **Settings**:

- **System Settings**: Authentication mode, multi-user support, date/time format, debug logging
- **Unit Preferences**: Choose Imperial (miles, gallons, MPG) or Metric (km, liters, L/100km)
  - Per-user preferences - each user can choose their preferred units
  - Optional "Show Both" mode displays both units simultaneously
- **Vehicle Archive**: View and manage archived vehicles, restore or permanently delete
- **Theme**: Light/dark mode and color customization

All settings persist to the database and survive container restarts.

### Environment Variables (Optional)

Only set these if you need to pre-configure before first startup:

| Variable | Default | When to Set |
|----------|---------|-------------|
| `MYGARAGE_DATABASE_URL` | `sqlite+aiosqlite:////data/mygarage.db` | Only if using PostgreSQL or custom SQLite path |

**Note**: Secret keys and API tokens are auto-generated on first startup and stored in `/data/secret.key` and the database.

---

## Authentication Modes

### No Authentication (Default)
Suitable for local development, testing, or single-user setups behind a firewall.

**Startup behavior:**
- No login required
- All endpoints accessible
- **Prominent security warning in logs**

⚠️ **Warning**: Do not expose to the public internet without changing auth mode.

### Local JWT Authentication
Username/password authentication with JWT tokens. Users managed in Settings → System → Multi-User Management.

**Setup:**
1. Go to **Settings → System** and change Authentication Mode to `local`
2. Navigate to the registration page (`/register`)
3. Create the first admin account (registration is disabled after first user)
4. Additional users must be created by admins via Settings → Multi-User Management

**Authentication behavior:**
- Issues JWT tokens for authenticated sessions
- Session persistence across browser restarts
- All endpoints require authentication

### OIDC/SSO Authentication
Authenticate using any OIDC-compatible provider (Authentik, Keycloak, Google, Azure AD, Okta, etc.).

**Setup:**
1. Go to **Settings → System** and change Authentication Mode to `oidc`
2. Configure your OIDC provider details:
   - Client ID
   - Client Secret
   - Discovery URL (e.g., `https://auth.example.com/.well-known/openid-configuration`)
3. Save settings and restart if needed

**Authentication behavior:**
- Redirects to identity provider for login
- Creates user accounts automatically from OIDC claims (if enabled)
- Supports account linking for existing local users
- First OIDC user becomes admin automatically

---

## Database

MyGarage supports **SQLite** (default) and **PostgreSQL**.

### SQLite (Default)
Zero-config database suitable for single-user or small deployments (1-5 users).

**Default configuration:**
```yaml
volumes:
  - ./data:/data
```

Database is automatically created at `/data/mygarage.db`.

**Backup:**
```bash
# Full backup (database + uploads)
tar -czf mygarage-backup-$(date +%Y%m%d).tar.gz ./data

# Database only
cp ./data/mygarage.db ./backups/mygarage-$(date +%Y%m%d).db

# Restore
tar -xzf mygarage-backup-20241201.tar.gz
```

### PostgreSQL (Optional)
Recommended for multi-user deployments or high-concurrency scenarios.

**Features:**
- Connection pooling (5 base + 10 overflow connections)
- Automatic connection recycling
- Pre-ping health checks

**Example stack:**
```yaml
version: '3.8'

services:
  postgres:
    image: postgres:16-alpine
    container_name: mygarage-postgres
    environment:
      POSTGRES_DB: mygarage
      POSTGRES_USER: mygarage
      POSTGRES_PASSWORD: CHANGEME_YOUR_SECURE_PASSWORD_HERE
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

  mygarage:
    image: ghcr.io/homelabforge/mygarage:latest
    container_name: mygarage
    depends_on:
      - postgres
    ports:
      - "8686:8686"
    volumes:
      - ./data:/data  # For uploads, photos, attachments
    environment:
      - MYGARAGE_DATABASE_URL=postgresql+asyncpg://mygarage:CHANGEME_YOUR_SECURE_PASSWORD_HERE@postgres:5432/mygarage
      - MYGARAGE_AUTH_MODE=local
    restart: unless-stopped

volumes:
  postgres_data:
```

**PostgreSQL backup:**
```bash
# Backup database
docker exec mygarage-postgres pg_dump -U mygarage mygarage > mygarage-backup-$(date +%Y%m%d).sql

# Restore
docker exec -i mygarage-postgres psql -U mygarage mygarage < mygarage-backup-20241201.sql
```

### Storage Structure

Regardless of database choice, file uploads are stored in `/data`:

```
/data/
├── mygarage.db          # SQLite database (if using SQLite)
├── secret.key           # Auto-generated JWT secret
├── attachments/         # Service record attachments
├── photos/              # Vehicle photos
└── documents/           # Registration, insurance, manuals
```

---

## Reverse Proxy Setup

### Traefik Example

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.mygarage.rule=Host(`garage.example.com`)"
  - "traefik.http.routers.mygarage.entrypoints=https"
  - "traefik.http.routers.mygarage.tls.certresolver=letsencrypt"
  - "traefik.http.services.mygarage.loadbalancer.server.port=8686"
```

### Nginx Example

```nginx
server {
    listen 443 ssl http2;
    server_name mygarage.example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://localhost:8686;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## Health Checks

MyGarage includes built-in health checks for container orchestration.

**Endpoint**: `GET /health`

**Docker Compose example:**
```yaml
services:
  mygarage:
    image: ghcr.io/homelabforge/mygarage:latest
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8686/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

**Response (healthy):**
```json
{
  "status": "healthy",
  "database": "connected",
  "version": "2.13.0"
}
```

---

## Development

### Requirements
- Python 3.14+
- Bun 1.3.4+ ([Install guide](https://bun.sh/docs/installation))
- Docker & Docker Compose (optional)

### Local Setup

```bash
# Clone repository
git clone https://github.com/homelabforge/mygarage.git
cd mygarage

# Backend
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
python app/main.py

# Frontend (in a new terminal)
cd frontend
bun install
bun dev
```

Backend runs on http://localhost:8686
Frontend dev server runs on http://localhost:3000

### API Documentation

Interactive API docs available at:
- Swagger UI: http://localhost:8686/docs
- ReDoc: http://localhost:8686/redoc
- OpenAPI JSON: http://localhost:8686/openapi.json

---

## Technology Stack

**Backend:**
- FastAPI (Python 3.14+)
- SQLAlchemy 2.0+ with Alembic migrations
- SQLite / PostgreSQL
- JWT Authentication with Argon2 password hashing
- OIDC/OAuth2 Support (Authlib)
- Granian ASGI server

**Frontend:**
- React 19
- TypeScript
- Tailwind CSS 4
- Recharts (analytics)
- Lucide React (icons)
- Bun 1.3.4 runtime
- Vite 7.2.4 bundler
- Vitest test runner

---

## License

MIT License - see [LICENSE](LICENSE) file for details.

---

## Common Issues

Having trouble? Here are the most common issues and quick fixes:

| Problem | Quick Fix |
|---------|-----------|
| **Port 8686 already in use** | Change port: `- "8687:8686"` in docker-compose.yml |
| **Can't login / No authentication** | Check auth mode in Settings → System. Default is `none` (no login required) |
| **Database permission errors** | Run: `sudo chown -R 1000:1000 ./data` |
| **VIN decode not working** | NHTSA API rate limit (10/min). Wait or add API key in settings |
| **Container won't start** | Check logs: `docker logs mygarage` |
| **OIDC redirect errors** | Verify redirect URI matches: `http://your-domain/api/oidc/callback` |

📖 **For detailed troubleshooting**, see the [Troubleshooting Guide](https://github.com/homelabforge/mygarage/wiki/Troubleshooting).

---

## Need Help?

### Quick Links
- **🚀 [Quick Start Guide](https://github.com/homelabforge/mygarage/wiki/Quick-Start)** - Get up and running in 5 minutes
- **❓ [FAQ](https://github.com/homelabforge/mygarage/wiki/FAQ)** - Common questions answered
- **🔧 [Troubleshooting](https://github.com/homelabforge/mygarage/wiki/Troubleshooting)** - Fix common issues
- **🔐 [Authentication Guide](https://github.com/homelabforge/mygarage/wiki/Authentication)** - Setup local, OIDC, or SSO
- **📏 [Unit Conversion System](docs/UNIT_CONVERSION.md)** - Imperial/Metric units and preferences
- **🗃️ [Vehicle Archive System](docs/ARCHIVE_SYSTEM.md)** - Archive vehicles while preserving history
- **🗄️ [Database Configuration](https://github.com/homelabforge/mygarage/wiki/Database-Configuration)** - SQLite vs PostgreSQL
- **🌐 [Reverse Proxy Setup](https://github.com/homelabforge/mygarage/wiki/Reverse-Proxy)** - Traefik, Nginx, Caddy

### Support Channels
- **📚 Full Documentation**: [GitHub Wiki](https://github.com/homelabforge/mygarage/wiki)
- **🌐 Website**: [homelabforge.io/builds/mygarage](https://homelabforge.io/builds/mygarage/)
- **🐛 Bug Reports**: [GitHub Issues](https://github.com/homelabforge/mygarage/issues)
- **💬 Questions & Discussions**: [GitHub Discussions](https://github.com/homelabforge/mygarage/discussions)
- **🔒 Security Vulnerabilities**: [Security Advisories](https://github.com/homelabforge/mygarage/security/advisories)

---

## Acknowledgments

Built for homelabbers who want to track vehicle maintenance without sending their data to third-party services.

VIN decoding powered by the [NHTSA vPIC API](https://vpic.nhtsa.dot.gov/).

### Development Assistance

MyGarage was developed through AI-assisted pair programming:

- **Claude (Anthropic)** - Co-developed architecture, implemented security patterns, conducted code reviews, designed testing strategies, and helped debug complex issues
- **GitHub Copilot** - Assisted with code completion, boilerplate generation, and inline suggestions

This project represents a true collaboration between human vision and AI capabilities. The human developer provided direction, domain knowledge, and decision-making, while AI tools contributed technical implementation, best practices, and caught potential issues. Both share credit for what works well, and the maintainer takes responsibility for addressing anything that doesn't.
