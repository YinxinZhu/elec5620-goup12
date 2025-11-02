# LangChain AI Agent

This service wraps a LangChain-based agent that generates Australian DKT theory test variants. It exposes the API service, so the Flask app can request for ai-generated variant questions.

## Features

- ReAct-style LangChain agent with dedicated tools for analysing the knowledge point, planning variations, drafting questions, and validating the output.
- REST API: `POST /api/generateVariant`
- Preserves the caller's language and always returns single-choice questions with four options.

## Quick Start

1. Create a virtual environment if desired and install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` and populate your OpenAI key. You can also change the model or port:
   ```bash
   cp .env.example .env
   ```
3. Run the server (defaults to port 28899):
   ```bash
   uvicorn server:app --host 0.0.0.0 --port 28899
   ```
   Important notes: 
   - You can not run by `python server.py`, errors will occur.
   - You need to restart the LangChain server when you make changes to codes. The Flask main server does not need restarting for changes to be effective.
4. Call the API (matches the Node proxy):
   ```bash
   curl -X POST http://localhost:28899/api/generateVariant \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer 9786534210" \
     -d '{"question": "...", "num": 3}'
   ```

## Configuration

| Variable           | Default       | Description                                  |
| ------------------ | ------------- | -------------------------------------------- |
| `OPENAI_API_KEY`   | _required_    | OpenAI-compatible API key.                   |
| `OPENAI_BASE_URL`  | `https://api.openai.com/v1` | Optional custom base URL.          |
| `OPENAI_MODEL`     | `gpt-5-mini`  | Chat model used for the agent and tools.     |
| `OPENAI_TEMPERATURE` | _(unset)_   | Optional override; omit to use model default.|
| `OPENAI_STREAM`    | `false`       | Enable streaming if the model/account permits.|
| `AUTH_BEARER`      | `9786534210`  | Simple bearer token guard for the endpoint.  |
| `PORT`             | `28899`       | Suggested port when running via uvicorn.     |
| `LOG_INTERMEDIATE` | `false`       | Print intermediate agent/tool steps.         |

## Project Layout

```
langchain/
├── server.py              # FastAPI app exposing /api/generateVariant
├── variant_agent/
│   ├── __init__.py
│   ├── config.py          # Settings and env loading
│   ├── models.py          # Pydantic request/response schemas
│   ├── agent.py           # Agent factory and orchestration helpers
│   ├── tools.py           # LangChain tools used by the agent
│   ├── prompts.py         # Prompt templates for tools
│   └── usage.py           # Token tracking helpers
├── requirements.txt
└── .env.example
```

## Testing

You can run a quick sanity check script once the server is up:

```bash
python -m http.client localhost 28899
```

Or use the included `curl` example above. The service returns the same response shape as the Node proxy (`knowledge_point_*`, `variant_questions`, `time`, `usage`).
