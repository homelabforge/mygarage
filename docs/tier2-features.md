# Tier 2 features

## Reminder packs

Built-in packs live under `backend/app/data/reminder_packs/`.

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

After the Tier 1 webhook PR merges, non-UI automations can also `POST /api/v1/webhooks/fuel` with `X-Webhook-Token`.

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
