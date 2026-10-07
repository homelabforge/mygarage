# Country profiles

MyGarage adapts a few national things to where a vehicle lives: the name and
cadence of its periodic technical inspection, the fuel names on the pump, the
tax types, the low-emission-zone scheme, the insurance vocabulary and the open
data sources it can read. That knowledge is **data, not code**: one JSON file
per country under `backend/app/data/country_profiles/`, loaded and validated
once at startup and served read-only to the frontend.

## How a country is chosen

The country whose rules apply to a vehicle is resolved in this order, on the
backend (`country_profile_service.resolve_country`) and the frontend
(`useResolvedCountry`) alike:

1. the vehicle's **registration country** (Vehicle → Basic information): a
   cross-border household registers a car abroad;
2. the person's own **country** (Quick Settings);
3. the instance's **default country** (Settings → System, admins);
4. none: today's behaviour, no national rule, US-oriented defaults.

A country is a setting, never a fork: it drives defaults and labels, and it
never hides a feature.

## Which file a country reads

- A code with its own file reads it: `FR.json`, `LU.json`, `DE.json`,
  `BE.json`, `IT.json`, `NL.json`, `ES.json`.
- A member state of the European Union without a file reads the **`EU.json`
  baseline**: EU law harmonises the registration certificate (Directive
  1999/37/EC), the fuel labels (EN 16942) and the minimum roadworthiness
  cadence (Directive 2014/45/EU), so the baseline is a sensible default.
- Any other code has no profile. The code is still stored and shown; it just
  drives no national rule.

`GET /api/country-profiles` lists the shipped profiles and
`GET /api/country-profiles/{code}` returns the one a code resolves to (the
`EU` baseline answers for a member state without a file; 404 otherwise).

## The file

Every national file starts with `"extends": "EU"`. A section the file restates
**replaces** the baseline's section wholesale (there is no deep merge), so the
file reads as what applies in that country, not as a diff. `sources` are
concatenated instead: the baseline's citations come first, then the country's.

| Section | What it holds |
|---|---|
| `names` | Proper names shown as-is in every UI language: `inspection`, `registration_certificate`, `lez`… |
| `currency` | ISO 4217 code |
| `inspection` | `name`, `lead_window_months` (how early the test may be done), `retest_window_months` (after a failed test), and `schedules` |
| `fuel` | `octane_scale` (`RON` or `AKI`), `diesel_dyed_distinction` (US clear vs dyed diesel), `grades` (pump names mapped to EN 16942 labels, see below) |
| `taxes` | `types` in the order the form offers them, `names` for the national proper names |
| `lez` | low-emission-zone `scheme` (`critair`, `umweltplakette`, `lez_registration`, `ztl`, `dgt_label`), `name`, `url` |
| `insurance` | `policy_types`, `coverage_keys`, the `no_claims` scheme (CRM, SF-Klasse, classe di merito, bonus-malus) |
| `tolls` | brand names, for reference (the toll form reads `frontend/src/constants/tollSystems.ts`) |
| `data_sources` | recall providers (`rappelconso`…) and the fuel price provider |
| `registration_certificate` | markers that identify the document, plate regexes, field P.3 energy codes, national categories (J.1) |
| `sources` | where every figure comes from: title, URL, date retrieved |

The shape is strict: an unknown key or an out-of-range value fails
`tests/unit/services/test_country_profile_service.py`, which loads every
shipped file.

### Inspection schedules

A schedule applies to the listed `vehicle_types` (and, optionally,
`fuel_types`). Its `steps` are read like this:

- the first step says when the first inspection is due:
  `first_after_years` after the first registration date;
- every later step says how often it recurs (`every_years`) and, optionally,
  until what vehicle age that rhythm applies (`until_age_years`, exclusive);
- the next due date is the previous one plus `every_years` of the first step
  whose `until_age_years` is null or above the vehicle's age at the previous
  due date.

Examples:

| Country | Steps | Due at ages |
|---|---|---|
| France, cars | `4` then every `2` | 4, 6, 8, 10… |
| Luxembourg | `4`, every `2` until `6`, then every `1` | 4, 6, 7, 8… |
| Netherlands, petrol | `4`, every `2` until `8`, then every `1` | 4, 6, 8, 9, 10… |
| Spain | `4`, every `2` until `10`, then every `1` | 4, 6, 8, 10, 11… |

The `note` is shown next to the computed date: use it for regional rules and
exemptions the schedule cannot express (Belgium's regions, for instance).

### Fuel labels

Every nozzle sold in the EU carries an EN 16942 label: `E5`, `E10` or `E85`
in a circle for petrol, `B7`, `B10`, `B20`, `B30`, `B100` or `XTL` in a
square for diesel, `H2`, `CNG`, `LPG` or `LNG` in a diamond for gas. A
fill-up stores that label in `fuel_grade` (migration 144), next to the
octane rating and the US on/off-road diesel grade of #164.

The fuel form reads the `fuel` section of the resolved profile:

- `grades` lists the names drivers see on the pump (`SP95-E10`, `Super
  Plus`, `Gazole (B7)`, `HVO (XTL)`…), each mapped to a label, an octane
  rating when it has one, and the `fuel_type` it belongs to. The form offers
  the names that match the fuel dispensed; picking one fills in the label
  and the octane. « Other » opens the plain label list for that fuel type.
  A profile with no names for a fuel type still offers the plain list.
- `octane_scale` relabels the octane field « Octane (RON) » where Europe's
  research octane number applies; `AKI` (the US pump number) keeps the
  generic label.
- `diesel_dyed_distinction: false` hides the on/off-road diesel grade, a
  North-American question a European pump cannot answer.

Without a country, or with a country that has no profile, none of this
appears and the form behaves exactly as before.

### Tax types

A tax record's `tax_type` is a code from `backend/app/constants/tax.py`
(`registration`, `registration_tax`, `co2_malus`, `weight_malus`,
`circulation_tax`, `company_vehicle_tax`, `inspection`, `property_tax`,
`tolls`, `vignette`, `lez_sticker`, `parking_permit`, `other`). The UI shows
each code's translated label; a profile's `taxes.types` lists the codes the
country uses, in the order the form offers them, and `taxes.names` gives the
national proper name shown beside the label (« Malus écologique (Y.3) »,
« Kfz-Steuer »). Codes the profile does not list follow, so every type stays
reachable. A profile that names a code the constants do not know fails to
load (`test_tax.py` checks every shipped file). Adding a type is code-only
since migration 146: the constant, the schema Literal, the frontend list and
the two bundles; the database has no CHECK to update.

## Adding a country

1. Copy `EU.json` to `<CC>.json` (uppercase ISO 3166-1 alpha-2), set
   `"country"` and `"extends": "EU"`, and keep only the sections that differ.
2. Fill `names` with the proper names drivers use (« Contrôle technique »,
   « Kfz-Steuer »). They are shown as-is in every language; generic labels
   (« Technical inspection ») live in the i18n bundles, not here.
3. Cite every figure in `sources` with the official page you read and the
   date. Prefer the authority's own site (a ministry, the inspection body,
   the vehicle registry) over secondary guides.
4. Run `cd backend && pytest tests/unit/services/test_country_profile_service.py`.
5. Mention the country in `CHANGELOG.md`.

Figures change: an inspection cadence is reformed, a sticker scheme is
replaced. The UI treats every computed date and badge as indicative and links
to the official source, so correct the data file when the rule changes rather
than working around it in code.
