# Tier 2 features

## Periodic technical inspection reminders

With a country set (Quick Settings → Country, or the vehicle's registration
country, or the instance default) and a first registration date on the
vehicle, MyGarage keeps one reminder for the country's periodic
roadworthiness test (contrôle technique, HU, APK, ITV, revisione…) up to
date on its own. The cadence comes from the country profile
(`docs/country-profiles.md`, section « Inspection schedules »):

- nothing on record: the reminder counts from the last theoretical due date
  (or the first registration) and is due on the next one;
- a service record typed `state_inspection` (« Contrôle technique », « TÜV »,
  « APK »… are recognised) completes it and the next one counts from that
  date; a line item marked failed schedules the re-test within the country's
  retest window;
- the rule carries `lead_days` (France: 180): the reminder says « can be done
  from », and the scheduler sends one notification when that window opens.
  The due-soon status keeps its 30-day horizon.

The engine writes one rule of type `state_inspection` with
`source='inspection'` per vehicle and never touches a rule a person made
(an existing manual rule of the type is adopted). Dismissing the reminder
stops it, like any recurring reminder; changing the country, the first
registration date or the preference turns it back on. It pauses for
archived or sold vehicles and for countries without a profile.

Off switch: Quick Settings → « Schedule the periodic technical inspection
automatically » (per person, `PUT /api/auth/me {"inspection_auto_schedule":
false}`); the instance setting `inspection_auto_schedule` covers vehicles
without an owner. A daily job (06:00 UTC) catches up with instance setting
or profile changes; `POST /api/vehicles/{vin}/reminders/reconcile` does it
on demand.

## Reminder packs

Built-in packs live under `backend/app/data/reminder_packs/`. Their names
and descriptions are translated from the `vehicles:reminderPacks` bundle by
pack id; a pack saved on the instance keeps the name it was given.

- `GET /api/reminder-packs` — list packs
- `POST /api/vehicles/{vin}/reminders/apply-pack` with `{"pack_id":"..."}` — creates pending reminders

Apply from the vehicle Tracking → Reminders UI (“Apply pack”).

## Tow pairing

Trailer-like vehicles (Trailer / FifthWheel / TravelTrailer) can set hitch/brake details and a **tow vehicle** on Overview. Tow vehicles list linked trailers via `GET /api/vehicles/{vin}/towed-trailers`.

## Matrix notifications

Settings → Notifications → Matrix: homeserver URL, access token, room ID. Test with `POST /api/notifications/test/matrix`.

## Quick Entry deep links / Shortcuts

PWA shortcuts and Apple Shortcuts can open:

- `/quick-entry?action=add-fuel`
- `/quick-entry?action=add-service`
- `/quick-entry?action=odometer`
- `/quick-entry?action=hours`

Optional `&vin=XXXXXXXXXXXXXXXXX`.

Non-UI automations can also `POST /api/v1/webhooks/fuel` with `X-Webhook-Token` (inbound webhooks shipped in v3.1.0).

## Opt-in LLM receipt parse

Disabled by default. Settings keys:

- `llm_receipt_parse_enabled`
- `llm_base_url` (default Ollama `http://127.0.0.1:11434/v1`)
- `llm_model`
- `llm_api_key` (optional)

`POST /api/vehicles/{vin}/fuel/parse-receipt` (multipart `text` and/or `file`) returns a **draft only** — it never writes a fuel record until the user confirms in the UI.

## Ask My Garage (specs + diagnostics)

Disabled by default. Setting key:

- `llm_garage_assistant_enabled` (reuses `llm_base_url` / `llm_model` / `llm_api_key`)

Structured maintenance fields on the vehicle record (Overview → Fluids & torque):

- `oil_viscosity`, `oil_capacity_liters`, `oil_filter_part_number`
- `lug_nut_torque_nm` (canonical Nm; UI converts to lb-ft)
- `coolant_type`, `brake_fluid_type`, `transmission_fluid_type`, `maintenance_specs_notes`

`POST /api/vehicles/{vin}/assistant/chat` with `{"message":"...","history":[]}` returns `{answer, citations, missing}`.

Answers are grounded in garage data only (identity, specs, recent service visits, notes, supplies, tires, reminders, trailer details) plus LiveLink `vehicle_dtcs` enriched with curated DTC definitions (`common_causes` / `symptoms` / `fix_guidance`). Codes mentioned in the question are looked up even if not currently active. The model must not invent fluid/torque specs or repair steps beyond that context; diagnostics are guidance, not a professional diagnosis.

## Document reading with a vision model

Disabled by default. Setting keys:

- `llm_document_reading_enabled` (images of imported documents are sent to `llm_base_url`)
- `llm_vision_model` (optional; blank reuses `llm_model`)
- `llm_provider_preset` (`custom`, `openrouter`, `ollama`, `openai`; a hint for the settings card)

A PDF with a text layer is read on the server without any model. `POST /api/settings/test/llm` (admin) checks the endpoint as text and, when document reading is on, as vision. What is sent, how to set up OpenRouter, Ollama or OpenAI, and the limits are in [AI features](ai-features.md).

## Recall sources (NHTSA, RappelConso)

A recall now records where it came from: `source` (`nhtsa`, `rappelconso` or `manual`), the provider's own `external_id` (an NHTSA campaign number, a RappelConso notice number), the notice's `external_url`, and a `match_confidence` (migration 148). Which sources a vehicle gets follows its country profile's `data_sources.recalls`: NHTSA where no profile applies (today's behaviour), RappelConso for France.

- `POST /api/vehicles/{vin}/recalls/check` asks every source that covers the vehicle, stores what is new, and answers `{providers_checked, new_count, warnings}` with the list; `check-nhtsa` still exists. The weekly job walks the same sources.
- **RappelConso** is the French government's product recall register (data.economie.gouv.fr, open data, Licence Ouverte 2.0). It has no VIN: a notice is matched on the make (with a few aliases: Citroën and DS, VW and Volkswagen…), on the model (every word of the vehicle's model as a whole word of the notice's models, so « 3 » never matches « 3008 ») and on the production or registration dates printed in the notice against the vehicle's first registration date: inside a range scores 95, outside every range 55 (not stored), no range printed 75. A stored notice is never resolved automatically. Settings: `rappelconso_enabled`, `rappelconso_api_url` (https on `data.economie.gouv.fr` only), `rappelconso_last_check`.
- The Recalls tab shows the source chip, the confidence when below 100, and a link to the notice; « Check recalls » replaces « Check NHTSA » and says when no source covers the vehicle's country.

## European VINs

NHTSA's vPIC decodes North American VINs in full. On a European VIN it knows the manufacturer (« RENAULT GROUP »), leaves the make and the model empty, reports a check-digit error that is not one (the check digit is a North American rule), and reads a model year off position 10 that most European makers use for a plant or series character. `app/services/vin_decoder.py` keeps everything NHTSA says and completes it from the bundled `app/data/wmi.json` (ISO 3780 regions, country ranges, and about 170 common WMIs with the makers that do use position 10 as a model year flagged):

- `make` and `manufacturer` are filled from the WMI when NHTSA has none; the `year` is dropped outside North America unless the maker is flagged.
- `GET`/`POST /api/vin/decode` adds `region` (AF, AS, EU, NA, OC, SA), `wmi_country`, `decode_quality` (`full`, `partial`, `wmi_only`, `none`) and `notes` (`eu_vin_no_model`, `year_unreliable`, `check_digit_not_applicable`).
- `GET /api/vin/validate/{vin}` adds `region`, `country` and `make` from the table, before any decode.
- The VIN input shows a notice on a partial decode (« European VIN: the maker is Renault… ») with the decoder's notes and a link to the registration certificate import; the wizard no longer clears a typed year or model when the decode has none.

## Registration certificate import

The EU registration certificate (Directive 1999/37/EC: carte grise, Zulassungsbescheinigung Teil I, kentekenbewijs, carta di circolazione, permiso de circulación…) prints the same harmonised field codes in every member state, so one parser reads them all.

- `POST /api/registration-certificate/parse` (multipart `file`: PDF, JPG, PNG or HEIC, 25 MB; optional `country` hint) reads a certificate without writing anything and returns `{source, country, confidence, fields, field_confidence, vehicle_patch, last_inspection_date, suggested_tax_records, warnings}`. The add-vehicle wizard uses it on its first step: the VIN (E), the plate (A), the first registration date (B), make (D.1), model (D.3), fuel (P.3), displacement (P.1), power (P.2), fiscal power (P.6), CO₂ (V.7), Euro class (V.9), the categories (J, J.1) and the country fill the form, which opens on step 2 with a notice to check every value.
- `POST /api/vehicles/{vin}/registration-certificate?overwrite=false` (owner) files the certificate under the vehicle's documents (type `registration`), fills the vehicle's empty fields (every field already set is kept unless `overwrite`; the VIN is never written, and a certificate whose VIN differs gets a warning), and records field X.1, the last periodic inspection, as a passed `state_inspection` service visit the inspection reminder then counts from. Reachable from the vehicle's settings sidecar.
- A PDF with a text layer is read by regex on the server. A photo or a scan goes through the vision model when document reading is on (see above) and every value a model returns is validated like a typed one (a VIN must be 17 valid characters, a date must parse, a P.3 code must be known); otherwise the request answers `409 ai_reading_not_configured` and the form says to type the values.
- Y.1 (regional tax) and Y.3 (CO₂ malus), or the total Y.6 when neither is printed, are offered as tax records on the wizard's review step; nothing is created unless ticked.

## European insurance (formulas, coverages, no-claims class, French documents)

Insurance in Europe is sold « au tiers », « tiers étendu » or « tous risques », with garanties a North American declarations page never prints, and every driver carries a no-claims class (the bonus-malus coefficient in France and Luxembourg, the Schadenfreiheitsklasse in Germany, the classe di merito in Italy). #211 adds them without changing anything for a household that never sets a country.

- **Formulas**: `policy_type` accepts `Third Party` and `Third Party Extended` beside the six existing values (« tous risques » is `Full Coverage`). The vocabulary lives in `app/constants/insurance.py`; migration 149 drops the database CHECK that carried the old list, the way 146 did for tax types, so the schemas hold it on every write path and the CSV importer refuses an unknown type as a row error. With a country set, the policy form and « Add to existing policy » offer the profile's formulas first (`insurance.policy_types`), then the rest.
- **Coverages**: nine European entries join the catalogue (`app/utils/insurance_coverages.py`, `frontend/src/constants/insuranceCoverages.ts`): `third_party_liability`, `driver_protection`, `theft`, `fire`, `natural_disasters`, `all_accidents_damage`, `legal_protection`, `assistance`, `replacement_vehicle`; `glass` is sold on both markets. Each coverage names its `regions`, published as `x-coverage-regions` beside `x-coverage-slots`. With a country set, the coverage checklist shows the profile's `insurance.coverage_keys` first, in its order, and folds the rest behind « More coverages » (opened on its own when one of them is carried). The line parser reads the French, German, Italian and Spanish phrases (« bris de glace », « garantie du conducteur », Teilkasko, furto, defensa jurídica…), the words that pin an amount (franchise, plafond, cotisation, jours…), and European figures (`1 234,56 €`, `1.234,56`, `300,00`) on any line priced in euros; a line without a euro mark is read exactly as before, so migration 108's conversion of older text is unchanged. « non souscrite », « sans objet » and « exclue » keep a line from becoming a row, like « not covered ».
- **No-claims class**: `insurance_policy_vehicles.no_claims_class` (VARCHAR(10), migration 149), on every vehicle link (`PolicyVehicleCreate/Update/Upsert`, `PolicyVehicleResponse`), ten characters of plain text; a French comma (« 0,50 ») is stored with a point. It follows the vehicle through a renewal and, carried over by VIN, through a switch of insurer (the relevé d'information carries it). The form shows the field under the profile's own name (« Bonus-malus (CRM) », « Schadenfreiheitsklasse (SF) », « Classe di merito (CU) ») with its example as placeholder, and only where the profile names a scheme or the vehicle already has a value. Exported as the `No-Claims Class` CSV column (CSV schema 8) and the `no_claims_class` backup key (JSON schema 9).
- **Documents**: `POST /api/insurance/parse-pdf` now goes through the document reader (see « Document reading with a vision model »): a PDF with a text layer is read on the server, a photo or a scan (JPEG, PNG, HEIC) by the vision model when document reading is on, else `409 ai_reading_not_configured`; the answer says which (`source`). A new French parser (`app/services/document_parsers/insurance_fr.py`) reads an avis d'échéance, a certificat or the conditions particulières of any French insurer: the insurer (a list of the common ones, the first printed on the page), the n° de contrat, the period « du … au … » (or the échéance, or the date d'effet, as a yearly term), the cotisation and how it is paid, the franchise, the formule, the coefficient de réduction-majoration, the plates (`plates_found`) and any VIN. The vision model's answer is mapped onto the same fields (`from_llm_fields`), every value validated, a formula classified from its printed words in French, German, Italian, Spanish and English, and a coverage name outside the catalogue reported as a warning. A document that names a plate and no VIN is matched to the garage's vehicles by plate (`matched_by: "plate"`); one that names nothing the garage knows still fills the vehicle whose tab opened the form.

