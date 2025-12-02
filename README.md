# MyGarage

Self-hosted vehicle maintenance tracking with VIN decoding, service records, fuel logging, and document management.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-Available-2496ED?logo=docker&logoColor=white)](https://github.com/homelabforge/mygarage/pkgs/container/mygarage)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![React 18](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)](https://react.dev)

![MyGarage Dashboard](docs/screenshots/dashboard.png)

**See more**: [homelabforge.io/builds/mygarage](https://homelabforge.io/builds/mygarage/)

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

After first startup, configure MyGarage in **Settings → System**:

- **Authentication Mode**: Switch from `none` to `local` or `oidc`
- **Multi-User Support**: Enable/disable additional user accounts
- **Date/Time Format**: Customize display formats
- **Units**: Miles vs kilometers, gallons vs liters
- **Debug Mode**: Enable detailed logging

All settings persist to the database and survive container restarts.

### Environment Variables (Optional)

Only set these if you need to pre-configure before first startup:

| Variable | Default | When to Set |
|----------|---------|-------------|
| `MYGARAGE_DATABASE_URL` | `sqlite+aiosqlite:////data/mygarage.db` | Only if using PostgreSQL or custom SQLite path |
| `MYGARAGE_AUTH_MODE` | `none` | Pre-configure auth mode (can change in UI later) |
| `MYGARAGE_DEBUG` | `false` | Enable debug logging |
| `MYGARAGE_OIDC_CLIENT_ID` | - | Required if using OIDC authentication |
| `MYGARAGE_OIDC_CLIENT_SECRET` | - | Required if using OIDC authentication |
| `MYGARAGE_OIDC_DISCOVERY_URL` | - | Required if using OIDC authentication |

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

**Startup behavior:**
- Prompts to create admin account on first visit
- Issues JWT tokens for authenticated sessions
- Session persistence across browser restarts

Enable via Settings UI or environment variable:
```yaml
environment:
  - MYGARAGE_AUTH_MODE=local
```

### OIDC/SSO Authentication
Authenticate using any OIDC-compatible provider (Authentik, Keycloak, Google, Azure AD, Okta, etc.).

**Startup behavior:**
- Redirects to identity provider for login
- Creates user accounts automatically from OIDC claims
- Supports account linking for existing local users

Enable via Settings UI or environment variables:
```yaml
environment:
  - MYGARAGE_AUTH_MODE=oidc
  - MYGARAGE_OIDC_CLIENT_ID=mygarage
  - MYGARAGE_OIDC_CLIENT_SECRET=your-client-secret
  - MYGARAGE_OIDC_DISCOVERY_URL=https://auth.example.com/.well-known/openid-configuration
```

**Recommended**: Configure via Settings UI after startup for easier setup and testing.

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
    server_name garage.example.com;

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
- Python 3.11+
- Node.js 18+
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
npm install
npm run dev
```

Backend runs on http://localhost:8686  
Frontend dev server runs on http://localhost:5173

### API Documentation

Interactive API docs available at:
- Swagger UI: http://localhost:8686/docs
- ReDoc: http://localhost:8686/redoc
- OpenAPI JSON: http://localhost:8686/openapi.json

---

## Technology Stack

**Backend:**
- FastAPI (Python 3.11+)
- SQLAlchemy + Alembic
- SQLite / PostgreSQL
- JWT Authentication
- OIDC/OAuth2 Support

**Frontend:**
- React 18
- TypeScript
- Tailwind CSS
- Recharts (analytics)
- Lucide React (icons)

---

## License

MIT License - see [LICENSE](LICENSE) file for details.

---

## Support

- **Website**: [homelabforge.io/builds/mygarage](https://homelabforge.io/builds/mygarage/)
- **Issues**: [GitHub Issues](https://github.com/homelabforge/mygarage/issues)
- **Discussions**: [GitHub Discussions](https://github.com/homelabforge/mygarage/discussions)

---

## Acknowledgments

Built for homelabbers who want to track vehicle maintenance without sending their data to third-party services.

VIN decoding powered by the [NHTSA vPIC API](https://vpic.nhtsa.dot.gov/).
