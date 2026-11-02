# AI features

MyGarage has three opt-in helpers that talk to a language model. All three are off by default, all three use the same OpenAI-compatible endpoint, and none of them is a required path: everything they fill in can be typed by hand.

| Feature | Setting | What is sent to the endpoint |
|---|---|---|
| Receipt draft parsing | `llm_receipt_parse_enabled` | The text of a fuel receipt (OCR'd on your server), to draft a fill-up you then confirm |
| Ask My Garage | `llm_garage_assistant_enabled` | Your question plus a compact digest of that vehicle's specs, service history and DTCs |
| Document reading | `llm_document_reading_enabled` | **Images** (at most two JPEG pages, 1600 px on the long side, about 2 MB in total) of a registration certificate or an insurance document you import as a photo or a scan |

Document reading is the one with a privacy consequence, which is why its toggle in Settings → Integrations spells it out: an image of the document itself leaves your server for the endpoint you configured. A PDF that contains a text layer is read with PyMuPDF on your server and never reaches a model, whatever the toggle says.

## The endpoint

Settings → Integrations → LLM Features holds one endpoint for all three features:

- **Provider preset**: fills in the base URL for OpenRouter, a local Ollama or OpenAI; *Custom* leaves it to you. A preset never chooses a model for you.
- **API base URL**: the `/v1` root of an OpenAI-compatible API. It must be an `http(s)://` URL; the settings API refuses anything else.
- **Model**: the text model, used by receipt parsing, Ask My Garage and, when the vision model is blank, document reading.
- **API key**: optional, stored encrypted, sent as a `Bearer` token.
- **Vision model (optional)**: shown once document reading is on. A model that accepts images; blank means the text model above is used for images too (fine on OpenRouter or OpenAI with a multimodal model, wrong on Ollama with a text-only model).
- **Test connection**: saves the card, sends a one-word text completion to the endpoint and, when document reading is on, a 64×64 image to the vision model. The result says which of the two passed, with the endpoint's own error when one did not (a wrong key, a model the endpoint does not have, a timeout).

### OpenRouter

One key, every model, pay per request.

1. Preset **OpenRouter** (base URL `https://openrouter.ai/api/v1`).
2. Paste an API key from <https://openrouter.ai/keys>.
3. Choose a model from <https://openrouter.ai/models>; for document reading pick one whose input modalities include **image** and put its id (`vendor/model`) in *Vision model*, or in *Model* to use it for everything.
4. Test connection.

MyGarage sends OpenRouter's optional `HTTP-Referer` and `X-Title` headers so the app shows up by name in your OpenRouter dashboard.

### Ollama (local)

Nothing leaves your network.

1. Preset **Ollama (local)** (base URL `http://127.0.0.1:11434/v1`; change the host if Ollama runs elsewhere, and make sure the MyGarage container can reach it).
2. `ollama pull llama3.2` for text and, for document reading, a vision model such as `ollama pull llava` or `ollama pull qwen2.5vl`; put its name in *Vision model*.
3. No API key. Test connection.

Reading a two-page document with a 7B vision model takes from a few seconds on a GPU to a minute or two on a CPU; the request allows 90 seconds.

### OpenAI

1. Preset **OpenAI** (base URL `https://api.openai.com/v1`).
2. Paste an API key.
3. A multimodal model (`gpt-4o-mini`, `gpt-4o`) reads images, so *Vision model* can stay blank.

### Anything else

Any server that speaks the OpenAI chat completions API works: LM Studio, vLLM, llama.cpp's server, LiteLLM, a corporate gateway. Preset **Custom**, type the base URL, and test.

## What document reading does

When you import a registration certificate (carte grise, Zulassungsbescheinigung, kentekenbewijs…) or an insurance document:

1. A PDF with a text layer is read on your server with PyMuPDF; no model is involved and the toggle is not consulted.
2. Otherwise, if document reading is on, the file (PDF scan, JPEG, PNG, HEIC) is turned into at most two JPEG pages, oriented, no larger than 1600 px on the long side and about 2 MB in total, and sent to the vision model with a prompt that asks for a JSON object of the document's harmonised fields (the EU certificate codes A, B, D.1, E, P.3… or the insurer, policy number, dates, premium, coverages) and for `null` whenever a value is absent or illegible.
3. Otherwise the import answers `409` with the code `ai_reading_not_configured`, and the form says to configure document reading in Settings or to type the values by hand.

Every value a model returns is validated like a typed one before it is applied (a VIN must be 17 valid characters, a date must parse, a fuel code must be known); anything that fails is dropped with a warning, and the form always shows you the fields before anything is saved. A model guesses; the certificate does not.

## Limits and costs

- At most two pages per document, so a reading costs two images and a short JSON answer (`max_tokens` 2000). On a paid endpoint that is a fraction of a cent to a few cents depending on the model.
- Timeouts: 60 s for text, 90 s for images.
- Uploads keep the document size limit of the instance (`max_document_size_bytes`); the images sent to the model are always reduced from it.
- The endpoint sees what the toggles allow and nothing more: no vehicle data goes with a document image, no document goes with an Ask My Garage question.

## API

- `POST /api/settings/test/llm` (admin): runs the connection test and returns `{valid, message, text_ok, vision_ok, model, vision_model}`; `vision_ok` is `null` when document reading is off.
- `GET /api/settings/public` serves `llm_receipt_parse_enabled`, `llm_garage_assistant_enabled` and `llm_document_reading_enabled`, so a non-admin's forms know which helpers to offer.
- Settings keys: `llm_base_url`, `llm_model`, `llm_api_key`, `llm_vision_model`, `llm_provider_preset` (`custom`, `openrouter`, `ollama`, `openai`) and the three flags above.
