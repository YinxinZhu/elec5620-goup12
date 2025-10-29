# AI Variant Question Proxy

This project exposes a minimal Express server that proxies requests to OpenAI in order to generate variant questions for the Australian DKT learner driver theory test.

## Prerequisites
- Node.js 18 or newer (I am using nodejs 22 LTS version)
- An OpenAI API key with access to the `gpt-5-mini` model

## Installation
```
npm install
```

## Configuration
Copy `.env.example` to `.env` and fill in your secrets:
```
OPENAI_API_KEY=sk-your-key
# Optional overrides
# OPENAI_BASE_URL=https://api.openai.com/v1
# OPENAI_MODEL=gpt-5-mini
# LOG_OPENAI_RESPONSE=false
# AUTH_BEARER=9786534210
# PORT=18899
```

You can edit the URL here if you uses OpenAI API proxy services.

You can edit the model here if you want to use another model.

You can both edit the URL and model here if you want to use another OpanAI API format compatible service, such as SiliconFlow.

## Usage
Start the server:
```bash
node server.js
```

Send a POST request to `http://localhost:18899/api/generateVariant` (or your chosen port):
```bash
curl -X POST http://localhost:18899/api/generateVariant \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer 9786534210" \
  -d '{
    "question": "LANGUAGE: ENGLISH\nQuestion: What should you do when you see a stop sign at an intersection?\nOptions: ...\nAnswer: ...\nExplanation: ...",
    "num": 3
  }'
```
The server validates the payload, forwards it to OpenAI, and returns a JSON object with the knowledge point metadata plus the requested variant questions.

## Error Handling
- Validation failures return HTTP 400 with a brief message.
- Errors from OpenAI are proxied with their original status code when available; unexpected issues return HTTP 500.

## Notes
- Payloads are limited to 1 MB to prevent accidental large submissions.
- The prompt instructs the model to preserve the input language and emit strict JSON, so the client can consume the response directly.
- Set `OPENAI_MODEL` if you need to target a different compatible OpenAI model; it defaults to `gpt-5-mini`.
- Flip `LOG_OPENAI_RESPONSE=true` in `.env` when you want the server to dump the raw OpenAI JSON response to the console for debugging.
- Requests must include an `Authorization: Bearer ...` header that matches `AUTH_BEARER` (default `9786534210`) or the server returns HTTP 401.
- The response has a `time` object to tell you the generation time. It will be around 10 seconds.
- The response attaches a simplified `usage` object with the model's token consumption metrics (input, output, reasoning, total).
