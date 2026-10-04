<div align="center">

# MyGarage

Self-hosted vehicle maintenance tracking for the whole household: service history, reminders, fuel, tires, insurance, documents and live OBD2 telemetry.

[![CI](https://github.com/homelabforge/mygarage/actions/workflows/ci.yml/badge.svg)](https://github.com/homelabforge/mygarage/actions/workflows/ci.yml)
[![CodeQL](https://github.com/homelabforge/mygarage/actions/workflows/codeql.yml/badge.svg)](https://github.com/homelabforge/mygarage/actions/workflows/codeql.yml)
[![Publish](https://github.com/homelabforge/mygarage/actions/workflows/publish.yml/badge.svg)](https://github.com/homelabforge/mygarage/actions/workflows/publish.yml)
[![Translations](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/homelabforge/mygarage/main/.github/badges/translations.json)](TRANSLATIONS.md)

[![Docker](https://img.shields.io/badge/Docker-Available-2496ED?logo=docker&logoColor=white)](https://github.com/homelabforge/mygarage/pkgs/container/mygarage)
[![Python 3.14](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev)
[![Bun](https://img.shields.io/badge/dynamic/regex?url=https://raw.githubusercontent.com/homelabforge/mygarage/main/.bun-version&search=^([\d.]%2B)&label=Bun&color=000000&logo=bun&logoColor=white&prefix=v)](https://bun.sh)
[![Node](https://img.shields.io/badge/dynamic/regex?url=https://raw.githubusercontent.com/homelabforge/mygarage/main/.nvmrc&search=^([\d.]%2B)&label=Node&color=5FA04E&logo=nodedotjs&logoColor=white&prefix=v)](https://nodejs.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Discord](https://img.shields.io/badge/Discord-Community-5865F2?logo=discord&logoColor=white)](https://discord.gg/6XttnVgG)

</div>

---

## Features

- **Vehicles** - Cars, motorcycles, boats, RVs and equipment. VIN decoding via NHTSA, maintenance specs, photos, window stickers, recalls and warranties.
- **Service history** - Visits with line items and attachments, with parts drawn from your own supplies inventory.
- **Reminders** - Recurring rules by distance, months or engine hours, anchored on real service history. Reminder packs, snooze, and notifications to Discord, Telegram, ntfy, Pushover, Gotify, Slack, Matrix or email.
- **Fuel and charging** - Fill-ups, DEF and propane, EV/PHEV charge sessions, economy trends, and imports from Fuelio, Drivvo and Tesla/ABRP.
- **Tires** - Tread and pressure per position, mount history, rotations, seasonal sets, storage and wear projection.
- **LiveLink** - Live OBD2 data, drive sessions, GPS trips and DTCs from a WiCAN device (HTTPS or MQTT), Torque Pro, any MQTT source, or Mopeka propane sensors. See the [LiveLink setup guide](docs/LIVELINK_SETUP.md).
- **Insurance** - Household policies spanning vehicles, standard coverages, renewals, and import from a declarations page.
- **Documents and places** - Registration, insurance and manuals with OCR, plus a map of nearby shops, fuel and charging.
- **Household** - Separate accounts, vehicle sharing and transfers, and a family dashboard. Run with no auth, local accounts, or any OIDC provider.
- **Units and languages** - Imperial, metric or any mix per quantity, a per-vehicle odometer unit, nine languages and 17 currencies.
- **Also** - Analytics and PDF reports, calendar, global search, a [gethomepage](https://gethomepage.dev) widget API, inbound webhooks and Telegram fuel commands, JSON and CSV backup and export, an installable PWA, and an opt-in [Ask My Garage](docs/tier2-features.md) assistant.

---

## Get started

One container with a `/data` volume. Follow the [Quick Start](https://github.com/homelabforge/mygarage/wiki/Quick-Start), or the [Installation guide](https://github.com/homelabforge/mygarage/wiki/Installation) for reverse proxies, subpath hosting, PostgreSQL and authentication.

MyGarage starts without authentication so you can look around. Turn on local accounts or OIDC in Settings before exposing it.

---

## Support

- **Documentation**: [GitHub Wiki](https://github.com/homelabforge/mygarage/wiki)
- **Website**: [homelabforge.io/builds/mygarage](https://homelabforge.io/builds/mygarage/)
- **Bug reports**: [GitHub Issues](https://github.com/homelabforge/mygarage/issues)
- **Discussions**: [GitHub Discussions](https://github.com/homelabforge/mygarage/discussions) or [Discord](https://discord.gg/6XttnVgG)

---

## Translations

See [Translation Status](TRANSLATIONS.md) for language coverage and how to contribute.

---

## License

MIT License. See [LICENSE](LICENSE).

---

## Acknowledgments

Built for homelabbers who want to track vehicle maintenance without sending data to third-party services.

VIN decoding powered by the [NHTSA vPIC API](https://vpic.nhtsa.dot.gov/).

### Development Assistance

MyGarage was developed through AI-assisted pair programming with **Claude** and **Codex**, combining human vision with AI capabilities for architecture, security patterns, and implementation.
