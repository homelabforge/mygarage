# MyGarage Home Assistant Add-on

Wraps the published [`ghcr.io/homelabforge/mygarage`](https://ghcr.io/homelabforge/mygarage) image for Home Assistant OS / Supervised.

## Install

1. **Settings → Add-ons → Add-on store → ⋮ → Repositories**
2. Add `https://github.com/homelabforge/mygarage` (the `homeassistant/` folder publishes via `repository.yaml`)
3. Install **MyGarage**, start it, open the UI via Ingress
4. In MyGarage → Settings → Integrations, create a **Widget API key**
5. Install the **MyGarage** HACS integration (same repo) and paste the key

## Options

| Option | Description |
|--------|-------------|
| `log_level` | Application log verbosity |
| `auth_mode` | `none`, `local`, or `oidc` (configure OIDC inside the app) |
| `timezone` | Container timezone (IANA) |
| `scheduler_enabled` | Background maintenance / recall / LiveLink jobs |

## Ports

- **8686** — web UI + REST (map if the HACS integration cannot reach the add-on hostname)

## Data

Persisted under the Supervisor `/data` volume (`mygarage.db`, attachments, photos, `secret.key`).
