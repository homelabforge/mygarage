# Translation Status

MyGarage supports multiple languages through community contributions. This page is automatically updated by CI.

> Last updated: 2026-04-13

## Overview

| | Language | Code | Progress | Keys |
|---|----------|------|----------|------|
| 🇺🇸 | English | `en` | `████████████████████` 100% | 1226/1226 |
| 🇺🇦 | Ukrainian | `uk` | `████████████████████` 100% | 1221/1226 |
| 🇷🇺 | Russian | `ru` | `████████████████████` 100% | 1221/1226 |
| 🇵🇱 | Polish | `pl` | `████████████████████` 99% | 1211/1226 |

**Overall: 100%** across 3 languages

---

## Contributing Translations

We welcome translation contributions! Here's how to help:

1. **Fork** the repository
2. Translation files are in `frontend/public/locales/{language_code}/`
3. English source files (the reference) are in `frontend/src/locales/en/`
4. Each namespace has its own JSON file: `common.json`, `nav.json`, `settings.json`, `vehicles.json`, `forms.json`, `analytics.json`
5. Copy the English file structure and translate the values (keep the keys the same)
6. Preserve `{{variable}}` interpolation placeholders exactly as they appear
7. Run `bun run validate:translations` to check your work
8. Submit a **Pull Request**

### Adding a New Language

1. Create a new directory under `frontend/public/locales/` with the [ISO 639-1 code](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes) (e.g., `fr` for French)
2. Copy all JSON files from `frontend/src/locales/en/` into your new directory
3. Translate the values
4. The language will be automatically detected and available in the app

---

## Contributors

Thank you to everyone who has contributed translations!

| Contributor | Languages |
|-------------|-----------|
| [Antonio (f0rZzZ)](https://github.com/f0rZzZ) | 🇵🇱 Polish, 🇷🇺 Russian, 🇺🇦 Ukrainian |
