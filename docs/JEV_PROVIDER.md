# TypeSafe Jev highlight selection

The self-hosted clip pipeline can use TypeSafe Jev to rank transcript candidates. Gemini and OpenAI-compatible backends remain available. Jev is a remote decision API: each candidate's transcript text is sent to TypeSafe. Use only media you are authorized to process and review the provider's terms and pricing.

Set these in the ignored `.env` file (never commit credentials):

```dotenv
HIGHLIGHT_PROVIDER=jev
JEV_API_KEY=your_key_here
# JEV_MODEL=jev-latest
# JEV_MAX_CANDIDATES=20
```

The upstream Compose file does not automatically pass `.env` values to the container. Add a `docker-compose.override.yml` with the backend `env_file` setting (merge with any existing override):

```yaml
services:
  backend:
    env_file: .env
    volumes:
      - /dev/null:/app/.env:ro
```

The mask lets you keep the host `.env` private (`chmod 600 .env`) while Compose passes settings into the container environment. Restart the backend with `docker compose up -d --no-deps backend`. `/api/config` reports the configured provider and model, not the API key. A Jev job sends one request per candidate (default at most 20); each request asks six score questions, so usage and cost scale with source length and the candidate limit. A provider failure fails the job instead of silently switching providers. Set `HIGHLIGHT_PROVIDER=gemini` and `LLM_PROVIDER=gemini` to select Gemini, or remove `HIGHLIGHT_PROVIDER` and configure `LLM_BASE_URL` for the existing OpenAI-compatible path.

Jev rates hook, standalone comprehensibility, emotional impact, information value, transcript clarity and boundaries. The code builds overlapping candidates locally from word timestamps, scores them, removes overlaps and selects the highest scores. Jev does not generate text here: the title and descriptions use an excerpt, and the hook is empty. Boundaries are word-aligned, but not guaranteed to be complete thoughts. Review clips before publishing. There is no verified audio-quality score; clarity is inferred from the transcript. Sparse or silent footage still requires Gemini's visual path, and Gemini-powered layout picking remains optional.

Configure `JEV_MODEL` with a model returned by TypeSafe's `/v1/models` if the default is unavailable. Check https://api.typesafe.ai/redoc for the current schema and https://help.typesafe.ai/articles/5974925716-how-is-submitted-data-used-or-retained for data handling. No particular accuracy in Indonesian or English is guaranteed: evaluate with representative authorized content. Tests cover mocked API errors and selection. On 2026-10-30, a live Jev request and candidate selection succeeded with a synthetic English transcript; real podcast quality and Indonesian speech remain unverified.
