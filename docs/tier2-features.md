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

Optional `&vin=XXXXXXXXXXXXXXXXX`.

After the Tier 1 webhook PR merges, non-UI automations can also `POST /api/v1/webhooks/fuel` with `X-Webhook-Token`.

## Opt-in LLM receipt parse

Disabled by default. Settings keys:

- `llm_receipt_parse_enabled`
- `llm_base_url` (default Ollama `http://127.0.0.1:11434/v1`)
- `llm_model`
- `llm_api_key` (optional)

`POST /api/vehicles/{vin}/fuel/parse-receipt` (multipart `text` and/or `file`) returns a **draft only** — it never writes a fuel record until the user confirms in the UI.
