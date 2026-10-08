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

## Document reading with a vision model

Disabled by default. Setting keys:

- `llm_document_reading_enabled` (images of imported documents are sent to `llm_base_url`)
- `llm_vision_model` (optional; blank reuses `llm_model`)
- `llm_provider_preset` (`custom`, `openrouter`, `ollama`, `openai`; a hint for the settings card)

A PDF with a text layer is read on the server without any model. `POST /api/settings/test/llm` (admin) checks the endpoint as text and, when document reading is on, as vision. What is sent, how to set up OpenRouter, Ollama or OpenAI, and the limits are in [AI features](ai-features.md).

## Registration certificate import

The EU registration certificate (Directive 1999/37/EC: carte grise, Zulassungsbescheinigung Teil I, kentekenbewijs, carta di circolazione, permiso de circulación…) prints the same harmonised field codes in every member state, so one parser reads them all.

- `POST /api/registration-certificate/parse` (multipart `file`: PDF, JPG, PNG or HEIC, 25 MB; optional `country` hint) reads a certificate without writing anything and returns `{source, country, confidence, fields, field_confidence, vehicle_patch, last_inspection_date, suggested_tax_records, warnings}`. The add-vehicle wizard uses it on its first step: the VIN (E), the plate (A), the first registration date (B), make (D.1), model (D.3), fuel (P.3), displacement (P.1), power (P.2), fiscal power (P.6), CO₂ (V.7), Euro class (V.9), the categories (J, J.1) and the country fill the form, which opens on step 2 with a notice to check every value.
- `POST /api/vehicles/{vin}/registration-certificate?overwrite=false` (owner) files the certificate under the vehicle's documents (type `registration`), fills the vehicle's empty fields (every field already set is kept unless `overwrite`; the VIN is never written, and a certificate whose VIN differs gets a warning), and records field X.1, the last periodic inspection, as a passed `state_inspection` service visit the inspection reminder then counts from. Reachable from the vehicle's settings sidecar.
- A PDF with a text layer is read by regex on the server. A photo or a scan goes through the vision model when document reading is on (see above) and every value a model returns is validated like a typed one (a VIN must be 17 valid characters, a date must parse, a P.3 code must be known); otherwise the request answers `409 ai_reading_not_configured` and the form says to type the values.
- Y.1 (regional tax) and Y.3 (CO₂ malus), or the total Y.6 when neither is printed, are offered as tax records on the wizard's review step; nothing is created unless ticked.

Answers are grounded in garage data only (identity, specs, recent service visits, notes, supplies, tires, reminders, trailer details) plus LiveLink `vehicle_dtcs` enriched with curated DTC definitions (`common_causes` / `symptoms` / `fix_guidance`). Codes mentioned in the question are looked up even if not currently active. The model must not invent fluid/torque specs or repair steps beyond that context; diagnostics are guidance, not a professional diagnosis.
