# Translating MyGarage

Thank you for helping translate MyGarage! This guide explains how to contribute translations, even if you're not a developer.

## File Structure

Translations are simple JSON files organized by language and namespace:

```
frontend/public/locales/
  pl/                    # Polish
    common.json          # Shared strings (buttons, errors, auth)
    nav.json             # Navigation labels
    settings.json        # Settings page
    vehicles.json        # Vehicle-related screens
    forms.json           # Form labels and modals
    analytics.json       # Analytics pages
  uk/                    # Ukrainian (same structure)
  ru/                    # Russian (same structure)
  pt-BR/                 # Brazilian Portuguese (same structure)
```

The **canonical English** files live in `frontend/src/locales/en/` and serve as the reference.

## How to Translate

### 1. Pick a Language

Check the `frontend/public/locales/` directory. If your language folder exists, you can improve existing translations. If not, create a new folder using the [ISO 639-1 code](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes) (e.g., `de` for German, `fr` for French).

### 2. Copy English Files as a Starting Point

If starting a new language, copy all files from `frontend/src/locales/en/` into your new `public/locales/{lang}/` folder.

### 3. Translate the Values (Not the Keys)

Each JSON file looks like this:

```json
{
  "save": "Save",
  "cancel": "Cancel",
  "login": {
    "title": "Sign In to MyGarage",
    "submit": "Sign In"
  }
}
```

Translate the **values** (right side) only. Never change the **keys** (left side):

```json
{
  "save": "Zapisz",
  "cancel": "Anuluj",
  "login": {
    "title": "Zaloguj sie do MyGarage",
    "submit": "Zaloguj sie"
  }
}
```

### 4. Preserve Interpolation Variables

Some strings contain `{{variables}}` — keep these exactly as-is:

```json
"footer": "MyGarage v{{version}} - Self-hosted vehicle maintenance tracker"
```

Translate the text around them:

```json
"footer": "MyGarage v{{version}} - Samodzielnie hostowany tracker konserwacji pojazdow"
```

### 5. Recommended Translation Order

Start with the files users see most:

1. `nav.json` (15 keys) — navigation labels
2. `common.json` (~160 keys) — buttons, errors, auth pages
3. `settings.json` (~220 keys) — settings page
4. `vehicles.json` (~620 keys) — vehicle screens, lists, detail pages
5. `forms.json` (~350 keys) — form labels, modals
6. `analytics.json` — analytics pages (if populated)

### 6. Validate Your Work

Run the validation script to check for missing or extra keys:

```bash
cd frontend
bun run validate:translations
```

## Key Naming Conventions

- **Dot notation** groups related strings: `fuelList.addFillUp`, `fuelList.noRecords`
- **Namespace prefixes** in code (`t('common:save')`) reference keys in other JSON files
- Keys are in English camelCase — they're identifiers, not translated

## Things NOT to Translate

- **Unit abbreviations**: gal, L, mi, km, MPG, L/100km, PSI, bar, lbs, kg, Nm, lb-ft
- **Technical terms**: VIN, OIDC, MQTT, API, CSV, JSON, PDF
- **Brand names**: MyGarage, NHTSA, Authentik, WiCAN

## Submitting Translations

1. Fork the [MyGarage repository](https://github.com/homelabforge/mygarage)
2. Add/update your language files in `frontend/public/locales/{lang}/`
3. Run `bun run validate:translations` to verify
4. Open a Pull Request with your changes

## Supported Languages

Every key is translated in all of them. See [TRANSLATIONS.md](TRANSLATIONS.md) for
the live percentages — they sit just under 100% because strings like `VIN`,
`MyGarage` and `Diesel` are correctly identical to English (see
[Things NOT to Translate](#things-not-to-translate)), not because anything is missing.

| Code | Language |
|------|----------|
| en | English (canonical source) |
| fr | French |
| pl | Polish |
| uk | Ukrainian |
| ru | Russian |
| pt-BR | Brazilian Portuguese |

To add a new language, translating the files is not enough — a locale directory
that isn't registered in **all three** allowlists is never loaded, and
`validate:translations` fails on it:

- `backend/app/constants/i18n.py` — add to `SUPPORTED_LANGUAGES`
- `frontend/src/constants/i18n.ts` — add to the `SUPPORTED_LANGUAGES` array **and** `languageToLocale()`
- `frontend/src/i18n.ts` — add to the `supportedLngs` array

Use the full region tag (`pt-BR`) only when the language ships as a region
variant; `load: 'currentOnly'` means a base tag like `pt` will not serve `pt-BR`
users, and vice versa.

## Questions?

Open a [Discussion](https://github.com/homelabforge/mygarage/discussions) on GitHub.
