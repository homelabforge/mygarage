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

1. `nav.json` — navigation labels
2. `common.json` — buttons, errors, auth pages
3. `settings.json` — settings page
4. `vehicles.json` — vehicle screens, lists, detail pages
5. `forms.json` — form labels and modals
6. `analytics.json` — analytics pages

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
- **Toll system names**: E-ZPass, Touch 'n Go, Telepass. They're saved exactly as listed and shown as-is in every language, so don't relabel them in a locale file. To add your country's systems, see the next section.

## Adding Your Country's Toll Systems

The toll tag form asks for a country, then lists that country's toll systems. The list lives in one file, `frontend/src/constants/tollSystems.ts`, and adding a country is one row. Malaysia's looks like this:

```ts
{
  country: 'MY',
  currencies: ['MYR'],
  languages: ['ms'],
  systems: ['SmartTAG', 'Touch \'n Go Card', 'Touch \'n Go RFID'],
},
```

- `country`: the two-letter ISO 3166-1 code. The app shows the country's name in each user's language by itself, so there's nothing to translate.
- `systems`: each name exactly as the brand writes it. That's what gets saved and shown, in every language. A system sold in several countries goes under each of them, spelled the same.
- `currencies` and `languages`: only used to preselect the country on a new tag. Use codes from `SUPPORTED_CURRENCIES` and `SUPPORTED_LANGUAGES` in `frontend/src/constants/i18n.ts`, and leave out a language spoken in lots of countries (English).

Don't rename a system that's already listed: tags saved with the old spelling keep it. Then check your row:

```bash
cd frontend
bun run test:run src/constants/__tests__/tollSystems.test.ts
```

The file is listed in `frontend/scripts/units.manifest.json`, so the Unit Manifest check fails on your PR until its digest is re-stamped. A maintainer does that when merging.

## Submitting Translations

1. Fork the [MyGarage repository](https://github.com/homelabforge/mygarage)
2. Add/update your language files in `frontend/public/locales/{lang}/`
3. Run `bun run validate:translations` to verify
4. Open a Pull Request with your changes

## Supported Languages

See [TRANSLATIONS.md](TRANSLATIONS.md) for live per-language coverage. No language
ever reads 100%, even when complete: shared terms like `VIN`, `MyGarage` and
`Diesel` are correctly identical to English (see
[Things NOT to Translate](#things-not-to-translate)) and count as untranslated.

| Code | Language |
|------|----------|
| en | English (canonical source) |
| de | German |
| fr | French |
| it | Italian |
| ms | Malay |
| pl | Polish |
| pt-BR | Brazilian Portuguese |
| ru | Russian |
| uk | Ukrainian |

To add a new language, translating the files is not enough — a locale directory
that isn't registered in **all three** allowlists is never loaded, and
`validate:translations` fails on it:

- `backend/app/constants/i18n.py` — add to `SUPPORTED_LANGUAGES`
- `frontend/src/constants/i18n.ts` — add to the `SUPPORTED_LANGUAGES` array **and** `languageToLocale()`
- `frontend/src/i18n.ts` — add to the `supportedLngs` array

Two more tables need the language, or parts of the app stay English:

- `frontend/src/utils/dateUtils.ts`: import the date-fns locale and add it to
  `DATE_FNS_LOCALES`, keyed by what `languageToLocale()` returns. Without it,
  relative dates ("3 months ago") stay English. A test fails if it's missing.
- `frontend/scripts/translation-utils.ts`: the name and flag in
  `LANGUAGE_NAMES` / `LANGUAGE_FLAGS`, used by `TRANSLATIONS.md`. Add yourself to
  the contributor table in `frontend/scripts/generate-translation-status.ts`, then
  run `bun run generate:translation-status`, and add a row to the table above.

Use the full region tag (`pt-BR`) only when the language ships as a region
variant; `load: 'currentOnly'` means a base tag like `pt` will not serve `pt-BR`
users, and vice versa.

## Questions?

Open a [GitHub Discussion](https://github.com/homelabforge/mygarage/discussions)
or ask in our [Discord community](https://discord.gg/6XttnVgG).
